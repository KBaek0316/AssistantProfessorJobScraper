import json
import logging
import os
import re
import time
from typing import Any, Dict, List, Optional, Tuple
from scrapers.base import JobPosting
from processor.cv_matcher import CVProfileManager


class GeminiExtractor:
    """Uses Google Gemini to parse unstructured job descriptions into structured fields,
    evaluating candidate fit (1-10) using the candidate CV profile and user-editable prompt.
    """

    DEFAULT_PROMPT_FILE = "eval_prompt.txt"
    DEFAULT_MODEL = "gemini-3.8-flash"
    CANDIDATE_MODELS = (
        "gemini-3.8-flash",
        "gemini-4-hydrogen",
        "gemini-3.7-flash",
        "gemini-3.5-flash-lite",
        "gemini-flash-lite-latest",
        "gemini-3-flash-preview",
        "gemini-3.1-flash-lite",
    )

    CACHE_DIR = ".cache"
    DESCRIPTIONS_CACHE = os.path.join(CACHE_DIR, "job_descriptions.json")

    EXPIRED_MARKERS = (
        "job expired or deleted",
        "this job is no longer available",
        "the job you are looking for is no longer",
        "no longer accepting applications",
        "this position has been filled",
        "this job has expired",
        "job has expired",
        "page not found",
        "404 not found",
    )

    def __init__(
        self,
        api_key: Optional[str] = None,
        model_name: Optional[str] = None,
        prompt_file: Optional[str] = None,
        min_fit_score: int = 3,
        cv_path: Optional[str] = None,
    ):
        self.logger = logging.getLogger("processor.gemini")
        if not api_key:
            try:
                from dotenv import load_dotenv
                load_dotenv()
            except ImportError:
                pass
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY", "").strip()
        self.model_name = (model_name or os.environ.get("GEMINI_MODEL", self.DEFAULT_MODEL)).strip() or self.DEFAULT_MODEL
        self.prompt_file = prompt_file or self.DEFAULT_PROMPT_FILE
        self.min_fit_score = min_fit_score
        self.cv_matcher = CVProfileManager(cv_path=cv_path)
        self.client = None
        self._working_model: Optional[str] = None
        self._unavailable_models: set = set()

        if self.api_key:
            try:
                from google import genai
                from google.genai import types
                http_opts = types.HttpOptions(
                    timeout=25000,
                    retry_options=types.HttpRetryOptions(attempts=1),
                )
                self.client = genai.Client(api_key=self.api_key, http_options=http_opts)
                self.logger.info(f"Initialized Gemini client successfully with model: {self.model_name}")
            except Exception as e:
                self.logger.warning(f"Failed initializing google-genai client: {e}")
        else:
            self.logger.warning("GEMINI_API_KEY not found in environment. Running in fallback mode without LLM summarization.")

    def _get_model_cascade(self) -> List[str]:
        """Return ordered list of candidate models, prioritizing the last responsive model in this session."""
        ordered: List[str] = []
        if self._working_model and self._working_model not in self._unavailable_models:
            ordered.append(self._working_model)
        if self.model_name and self.model_name not in ordered and self.model_name not in self._unavailable_models:
            ordered.append(self.model_name)
        for m in self.CANDIDATE_MODELS:
            if m not in ordered and m not in self._unavailable_models:
                ordered.append(m)
        if not ordered:
            # Reset session blacklist if all models had transient errors
            self._unavailable_models.clear()
            ordered = list(dict.fromkeys([self.model_name, *self.CANDIDATE_MODELS]))
        return ordered

    def _get_prompt_template(self) -> str:
        """Load prompt template from user-editable text file or fall back to built-in template."""
        if os.path.exists(self.prompt_file):
            try:
                with open(self.prompt_file, "r", encoding="utf-8") as f:
                    content = f.read()
                    if content.strip():
                        return content
            except Exception as e:
                self.logger.warning(f"Failed reading prompt file {self.prompt_file}: {e}")

        return """Analyze this academic job posting:
{candidate_profile}
Title: {title}
Institution: {institution}
Location: {location}
Source: {source}
Description: {raw_description}

=== EVALUATION INSTRUCTIONS ===
1. Determine Position Eligibility & Seniority (Tenure-track Assistant Professor, Open Rank including Assistant, or career-track university faculty; exclude senior-only, adjunct, postdoc, staff).
2. Evaluate Geographic Scope (Allowed: US, Canada, Europe, Hong Kong, Singapore, Japan, South Korea, Taiwan; Exclude Mainland China and non-target regions).
3. Assign Calibrated Candidate Fit Score (1-10) with mandatory score ceilings (max 5 for general urban planning without direct transportation focus, Heavy IE, Robotics, Supply Chain; max 4 for non-transportation CEE subdisciplines or generic snippet-only postings).
4. Handling Multiple Positions / Tracks: If multiple research tracks are advertised, isolate the single most relevant track (e.g. Transportation Systems Engineering), populate "targeted_track", and prefix "concise_summary" with "[<Track Name>] ".
5. Extract official Department, Campus & Location (never collapse branch/satellite campuses into flagship cities).

=== REQUIRED JSON OUTPUT FORMAT ===
{"is_faculty": true, "fit_score": 8, "fit_reason": "...", "clean_title": "...", "institution": "...", "department": "...", "targeted_track": null, "tenure_track": "Tenure-Track", "deadline": "Open until filled", "salary": "Not specified", "city_state": "...", "country": "...", "research_topics": [], "concise_summary": "..."}
"""

    def _get_evaluation_instructions(self) -> str:
        """Extract the evaluation instructions section from the prompt template (eval_prompt.txt)."""
        template = self._get_prompt_template()
        if "=== EVALUATION INSTRUCTIONS ===" in template:
            after = template.split("=== EVALUATION INSTRUCTIONS ===", 1)[1]
            for marker in ("=== REQUIRED JSON OUTPUT FORMAT ===", "=== OUTPUT FORMAT ==="):
                if marker in after:
                    after = after.split(marker, 1)[0]
                    break
            if after.strip():
                return after.strip()
        return template.strip()

    @classmethod
    def _is_expired_or_unavailable_text(cls, text: Optional[str]) -> bool:
        """Return True if text is empty or contains expired/deleted job board boilerplate."""
        if not text or not text.strip():
            return True
        low = text.lower()
        return any(marker in low for marker in cls.EXPIRED_MARKERS)

    def _load_description_cache(self) -> dict:
        if os.path.exists(self.DESCRIPTIONS_CACHE):
            try:
                with open(self.DESCRIPTIONS_CACHE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                # Filter out any accidentally cached expired-page boilerplate
                return {
                    k: v for k, v in data.items()
                    if isinstance(v, str) and not self._is_expired_or_unavailable_text(v)
                }
            except Exception:
                pass
        return {}

    def _save_description_cache(self, cache: dict):
        try:
            os.makedirs(self.CACHE_DIR, exist_ok=True)
            with open(self.DESCRIPTIONS_CACHE, "w", encoding="utf-8") as f:
                json.dump(cache, f, indent=2)
        except Exception:
            pass

    def _fetch_description_fallback(self, posting: JobPosting) -> str:
        """Fetch full live job description from the source board if available and active."""
        clean_link = (posting.link or "").strip()
        if not clean_link:
            return ""

        src = (posting.source or "").lower()
        fetched_text = ""
        try:
            if "academickeys" in src or "academickeys.com" in clean_link:
                from scrapers.academickeys import AcademicKeysScraper
                scraper = AcademicKeysScraper()
                full_text, dept, dl = scraper._fetch_detail(clean_link)
                if self._is_expired_or_unavailable_text(full_text):
                    return ""
                if dept and (not posting.field or posting.field.strip().lower() in ("not specified", "unspecified", "none", "", "transportation / civil engineering")):
                    posting.field = dept
                if dl and (not posting.deadline or posting.deadline.strip().lower() in ("not specified", "unspecified", "none", "")):
                    posting.deadline = dl
                fetched_text = full_text

            elif "higheredjobs" in src or "higheredjobs.com" in clean_link:
                from scrapers.higheredjobs import HigherEdJobsScraper
                from bs4 import BeautifulSoup
                scraper = HigherEdJobsScraper()
                resp = scraper.session.get(clean_link, timeout=12)
                if resp.status_code == 200:
                    soup = BeautifulSoup(resp.text, "html.parser")
                    div = (
                        soup.find("div", id="mainContent")
                        or soup.find("div", class_="main")
                        or soup.find("div", id="job-description")
                        or soup.find("div", class_="col-sm-12")
                    )
                    if div:
                        fetched_text = div.get_text(" ", strip=True)

            elif "linkedin" in src or "linkedin.com" in clean_link:
                from scrapers.linkedin import LinkedInScraper
                m = re.search(r"(\d{8,})", clean_link)
                if m:
                    scraper = LinkedInScraper()
                    fetched_text = scraper._fetch_job_description(m.group(1))

            elif "chronicle" in src or "chronicle.com" in clean_link:
                from scrapers.chronicle import ChronicleScraper
                scraper = ChronicleScraper()
                full_desc, dl, _, _, _ = scraper._fetch_detail_page(clean_link)
                if not self._is_expired_or_unavailable_text(full_desc):
                    if dl and (not posting.deadline or posting.deadline.strip().lower() in ("not specified", "unspecified", "none", "")):
                        posting.deadline = dl
                    fetched_text = full_desc

            elif "jobsacuk" in src or "jobs.ac.uk" in clean_link:
                from scrapers.jobsacuk import JobsAcUkScraper
                scraper = JobsAcUkScraper()
                fetched_text = scraper._fetch_job_description(clean_link)

        except Exception as e:
            self.logger.debug(f"Could not fetch description fallback for {clean_link}: {e}")

        if self._is_expired_or_unavailable_text(fetched_text):
            return ""
        return fetched_text

    def is_posting_still_available(self, posting: JobPosting, desc_cache: Optional[dict] = None) -> bool:
        """
        Checks whether an existing job posting is still active and available online.
        If active, populates posting.raw_description with the live description and updates desc_cache.
        If the posting is Past Due or its live page is expired/deleted/unavailable, returns False
        so the existing record and its evaluation are preserved as-is.
        """
        if posting.status == "Past Due":
            return False

        # If a full in-memory description was already provided (e.g., freshly scraped today or in unit tests)
        if posting.raw_description and len(posting.raw_description.strip()) >= 250 and not self._is_expired_or_unavailable_text(posting.raw_description):
            if desc_cache is not None:
                desc_cache[posting.id] = posting.raw_description
                if posting.link:
                    desc_cache[posting.link] = posting.raw_description
            return True

        live_desc = self._fetch_description_fallback(posting)
        if live_desc and len(live_desc.strip()) >= 250 and not self._is_expired_or_unavailable_text(live_desc):
            posting.raw_description = live_desc
            if desc_cache is not None:
                desc_cache[posting.id] = live_desc
                if posting.link:
                    desc_cache[posting.link] = live_desc
            return True

        return False

    def _prepare_posting_description(self, posting: JobPosting, desc_cache: dict) -> None:
        """Populate posting.raw_description via cache, live fetch, or metadata fallback."""
        if not posting.raw_description or len(posting.raw_description.strip()) < 300 or self._is_expired_or_unavailable_text(posting.raw_description):
            cached = desc_cache.get(posting.id) or desc_cache.get(posting.link)
            if cached and len(cached.strip()) >= 300 and not self._is_expired_or_unavailable_text(cached):
                posting.raw_description = cached
            else:
                fetched = self._fetch_description_fallback(posting)
                if fetched and len(fetched.strip()) > len(posting.raw_description or ""):
                    posting.raw_description = fetched
                    desc_cache[posting.id] = fetched
                    if posting.link:
                        desc_cache[posting.link] = fetched
                elif not posting.raw_description or self._is_expired_or_unavailable_text(posting.raw_description):
                    posting.raw_description = (
                        f"Position Title: {posting.title}. "
                        f"Institution: {posting.institution}. "
                        f"Department / Division: {posting.field or 'Academic Department'}. "
                        f"Location: {posting.location or 'Not specified'}. "
                        f"Summary Context: {posting.summary or 'Tenure-track academic faculty position'}. "
                        f"Official Application Link: {posting.link}"
                    )
        else:
            if posting.id not in desc_cache or len(posting.raw_description) > len(desc_cache.get(posting.id, "")):
                desc_cache[posting.id] = posting.raw_description
                if posting.link:
                    desc_cache[posting.link] = posting.raw_description

        if posting.raw_description and len(posting.raw_description.strip()) < 300:
            if "[Note: Detailed job description" not in posting.raw_description:
                posting.raw_description = (
                    f"{posting.raw_description.strip()} "
                    "[Note: Detailed job description could not be retrieved from the source board; "
                    "evaluate conservatively based only on verified text.]"
                )

    def _call_gemini_json(self, prompt: str) -> Optional[Any]:
        """Invoke Gemini using the active model cascade and return parsed JSON (dict or list), or None on failure."""
        if not self.client:
            return None

        gen_config = None
        try:
            from google.genai import types
            gen_config = types.GenerateContentConfig(
                response_mime_type="application/json",
                automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
            )
        except Exception:
            pass

        response_text = ""
        for model_candidate in self._get_model_cascade():
            try:
                kwargs: Dict[str, Any] = {"model": model_candidate, "contents": prompt}
                if gen_config:
                    kwargs["config"] = gen_config
                resp = self.client.models.generate_content(**kwargs)
                response_text = (resp.text or "").strip() if resp else ""
                if response_text:
                    self._working_model = model_candidate
                    break
            except Exception as err:
                err_msg = str(err)
                # Deprioritize models with zero quota or persistent 503/504/404 for the rest of this session
                if any(k in err_msg for k in ("limit: 0", "PerDay", "404", "NOT_FOUND", "503", "504", "UNAVAILABLE", "DEADLINE_EXCEEDED", "high demand", "Read timed out")):
                    self._unavailable_models.add(model_candidate)
                    self.logger.warning(f"Model '{model_candidate}' unavailable ({err_msg[:120]}). Failing over to next model...")
                elif any(k in err_msg for k in ("429", "RESOURCE_EXHAUSTED", "quota")):
                    self.logger.warning(f"Model '{model_candidate}' rate-limited ({err_msg[:120]}). Sleeping 4s before failover...")
                    time.sleep(4)
                else:
                    self.logger.warning(f"Model '{model_candidate}' failed ({err_msg[:120]}). Trying next model...")
                continue

        if not response_text:
            return None

        try:
            return self._parse_llm_json(response_text)
        except Exception as parse_err:
            self.logger.warning(f"Failed to parse JSON from Gemini response: {parse_err}")
            return None

    def _apply_evaluation_result(self, posting: JobPosting, data: Dict[str, Any], is_update_mode: bool = False) -> None:
        """Apply structured Gemini evaluation dictionary to a JobPosting instance with deterministic guardrails."""
        if not isinstance(data, dict):
            return

        # 1. Faculty eligibility check
        if data.get("is_faculty") is False:
            if not is_update_mode:
                posting.status = "Filtered (Non-Faculty / Seniority)"
            posting.fit_score = 1
            if data.get("fit_reason"):
                posting.fit_reason = str(data["fit_reason"]).strip()
            return

        # 2. Fit score & reason
        fit_score_raw = data.get("fit_score")
        if fit_score_raw is not None:
            try:
                posting.fit_score = max(1, min(10, int(fit_score_raw)))
            except (ValueError, TypeError):
                pass
        if data.get("fit_reason"):
            posting.fit_reason = str(data["fit_reason"]).strip()

        # 3. Metadata updates
        if data.get("clean_title"):
            clean_t = str(data["clean_title"]).strip()
            if JobPosting.is_valid_faculty_posting(clean_t, posting.raw_description):
                if not is_update_mode or not posting.title or posting.title.strip().lower() in ("faculty openings", "faculty position", "open rank", "professor"):
                    posting.title = clean_t
        if data.get("institution"):
            inst = str(data["institution"]).strip()
            if inst and (not posting.institution or not is_update_mode or posting.institution in ("Academic Institution", "HigherEdJobs Listed University", "Chronicle Listed University", "University / Institution", "UK/European University")):
                posting.institution = inst
        if data.get("department"):
            dept = str(data["department"]).strip()
            if dept and dept.lower() not in ("not specified", "unspecified", "none"):
                if not posting.field or not is_update_mode or posting.field.lower() in ("not specified", "unspecified", "transportation / civil engineering", "civil & environmental / transportation engineering"):
                    posting.field = dept
        if data.get("tenure_track"):
            posting.tenure_track = str(data["tenure_track"]).strip()
        if data.get("deadline"):
            posting.deadline = str(data["deadline"]).strip()

        if not posting.deadline or posting.deadline.lower() in ("not specified", "unspecified", "see full listing", "open until filled"):
            extracted_dl = JobPosting.extract_deadline_from_text(posting.raw_description)
            if extracted_dl:
                posting.deadline = extracted_dl

        if posting.deadline:
            posting.deadline_date = JobPosting.extract_latest_deadline_date(posting.deadline)

        if data.get("salary") and str(data["salary"]).strip() != "Not specified":
            posting.salary = str(data["salary"]).strip()
        if data.get("city_state"):
            posting.location = str(data["city_state"]).strip()

        # 4. Research topics & summary
        topics_data = data.get("research_topics", [])
        if isinstance(topics_data, list):
            posting.research_topics = ", ".join(str(t).strip() for t in topics_data if t)
        elif isinstance(topics_data, str):
            posting.research_topics = topics_data.strip()

        targeted_track = str(data.get("targeted_track") or "").strip()
        concise = str(data.get("concise_summary") or data.get("summary") or "").strip()
        if targeted_track and targeted_track.lower() not in ("null", "none"):
            prefix = f"[{targeted_track}]"
            if not concise.startswith(prefix) and not concise.lower().startswith(f"[{targeted_track.lower()}]"):
                concise = f"{prefix} {concise}" if concise else prefix

        if concise:
            if posting.research_topics:
                posting.summary = f"{concise} | Research Topics: {posting.research_topics}"
            else:
                posting.summary = concise

        # 5. Deterministic Score Ceiling Guardrails (enforcing eval_prompt.txt Mandatory Score Ceilings)
        if posting.fit_score is not None:
            title_low = (posting.title or "").lower()
            track_low = targeted_track.lower()
            has_transport_focus = any(
                kw in title_low or kw in track_low
                for kw in ("transport", "transit", "mobility", "traffic", "rail", "travel", "highway", "aviation")
            )
            if not has_transport_focus:
                # Non-transportation Civil Engineering subdisciplines explicitly in title -> max 4
                if any(kw in title_low for kw in ("structural engineering", "water resources", "hydrolog", "hydraulic", "geotechnical engineering", "construction management", "construction engineering")):
                    posting.fit_score = min(posting.fit_score, 4)
                # Non-transportation Urban Planning subdisciplines explicitly in title -> max 5
                elif any(kw in title_low for kw in ("housing", "historic preservation", "real estate", "urban design", "climate change and planning law")):
                    posting.fit_score = min(posting.fit_score, 5)

        # 6. Geographic scope & weak filter checks
        if not is_update_mode:
            country = str(data.get("country", "")).strip()
            if not JobPosting.is_allowed_location(posting.location, country, institution=posting.institution):
                posting.status = "Filtered (Location Outside Scope)"
                posting.fit_score = 1
                posting.fit_reason = f"Screened out: Location '{posting.location}' is outside target geographic scope."
            elif posting.fit_score is not None and posting.fit_score < self.min_fit_score:
                posting.status = "Filtered (Low Relevance)"

    def enrich_postings(self, postings: List[JobPosting], is_update_mode: bool = False) -> List[JobPosting]:
        """Enrich a list of job postings with Gemini structured data and fit scores."""
        if not postings:
            return postings

        if not self.client:
            self.logger.info("Skipping Gemini enrichment (client not configured). Using raw scraper fields.")
            for p in postings:
                if not p.summary:
                    p.summary = p.raw_description[:200] + "..." if len(p.raw_description) > 200 else p.raw_description
            return postings

        self.logger.info(f"Enriching {len(postings)} job postings with Gemini ({self.model_name}) [update_mode={is_update_mode}]...")

        desc_cache = self._load_description_cache()
        to_call_llm: List[JobPosting] = []
        kept_unavailable_count = 0

        if is_update_mode:
            from concurrent.futures import ThreadPoolExecutor
            candidates_to_check = [p for p in postings if p.fit_score is not None]
            unscored_candidates = [p for p in postings if p.fit_score is None]

            def _check_one(job: JobPosting) -> Tuple[JobPosting, bool]:
                return job, self.is_posting_still_available(job, desc_cache=None)

            self.logger.info(f"Checking live availability of {len(candidates_to_check)} existing postings...")
            with ThreadPoolExecutor(max_workers=12) as pool:
                availability_results = list(pool.map(_check_one, candidates_to_check))

            for p, is_avail in availability_results:
                if is_avail:
                    if p.raw_description:
                        desc_cache[p.id] = p.raw_description
                        if p.link:
                            desc_cache[p.link] = p.raw_description
                    to_call_llm.append(p)
                else:
                    kept_unavailable_count += 1
                    if "expired or been deleted" in (p.fit_reason or "").lower():
                        p.fit_score = 3
                        p.fit_reason = "This Civil Engineering position focuses on water resources engineering rather than transportation systems."

            to_call_llm.extend(unscored_candidates)
        else:
            for p in postings:
                if not JobPosting.is_valid_faculty_posting(p.title, p.raw_description or p.summary):
                    p.status = "Filtered (Non-Faculty / Seniority / Adjunct)"
                    p.fit_score = 1
                    p.fit_reason = f"Screened out: Position title '{p.title}' is senior-only, adjunct, continuing education, or non-faculty."
                    continue
                if p.location and not JobPosting.is_allowed_location(p.location, institution=p.institution):
                    p.status = "Filtered (Location Outside Scope)"
                    p.fit_score = 1
                    p.fit_reason = f"Screened out: Location '{p.location}' is outside target geographic scope."
                    continue
                to_call_llm.append(p)

        self._save_description_cache(desc_cache)
        if is_update_mode and kept_unavailable_count > 0:
            self.logger.info(
                f"Preserved {kept_unavailable_count} existing postings that are no longer available online; "
                f"re-evaluating {len(to_call_llm)} currently active postings."
            )

        if to_call_llm:
            if len(to_call_llm) > 1:
                batch_size = 8
                for i in range(0, len(to_call_llm), batch_size):
                    chunk = to_call_llm[i:i + batch_size]
                    success = self._enrich_batch(chunk, is_update_mode=is_update_mode)
                    if not success:
                        for p in chunk:
                            self._enrich_single(p, is_update_mode=is_update_mode)
                    if i + batch_size < len(to_call_llm):
                        time.sleep(0.8)
            else:
                self._enrich_single(to_call_llm[0], is_update_mode=is_update_mode)

        for p in postings:
            if not p.summary:
                p.summary = p.raw_description[:200] if p.raw_description else (p.field or p.title)

        return postings

    def _enrich_batch(self, batch: List[JobPosting], is_update_mode: bool = False) -> bool:
        """Enrich a batch of JobPosting objects in a single structured Gemini call."""
        if not batch:
            return True

        candidate_profile_text = self.cv_matcher.get_prompt_context()
        desc_cache = self._load_description_cache()
        batch_input = []

        for p in batch:
            self._prepare_posting_description(p, desc_cache)
            desc = p.raw_description or p.summary or ""
            batch_input.append({
                "id": p.id,
                "title": p.title,
                "institution": p.institution,
                "department": p.field or "Academic Department",
                "location": p.location,
                "source": p.source,
                "existing_topics": p.research_topics or "",
                "raw_description": desc[:3000],
            })
        self._save_description_cache(desc_cache)

        instructions = self._get_evaluation_instructions()
        prompt = f"""You are an academic hiring specialist and faculty search advisor.
Analyze the following academic job postings and evaluate their relevance against the candidate's research profile.

=== CANDIDATE PROFILE ===
{candidate_profile_text}
Target Positions: Tenure-track Assistant Professor, Open Rank Faculty searches inclusive of Assistant Professor, or career-track university teaching faculty appointments.

=== EVALUATION INSTRUCTIONS ===
{instructions}

=== POSTINGS TO EVALUATE ===
{json.dumps(batch_input, indent=2)}

=== OUTPUT FORMAT ===
Return strictly a JSON array of objects (one per evaluated job) with fields:
- "id": string matching the provided job id
- "is_faculty": boolean
- "fit_score": integer 1-10
- "fit_reason": 1 concise sentence explaining the match or mismatch (focused on the most relevant track if multiple advertised)
- "clean_title": official position title
- "institution": official university name, including specific campus when part of a multi-campus system (e.g. 'University of Michigan, Ann Arbor', 'Texas A&M University-Corpus Christi', 'Cornell Tech', 'Purdue University in Indianapolis', 'University of California, Berkeley')
- "department": official department / school name
- "targeted_track": string naming the most relevant position/track if multiple research tracks/topics are advertised (e.g. "Transportation Systems Engineering (TSE)"), otherwise null
- "tenure_track": "Tenure-Track", "Tenured", "Non-Tenure Track", or "Unspecified"
- "deadline": application deadline string (or "Open until filled")
- "salary": salary range or "Not specified"
- "city_state": city, state/country of the ACTUAL campus or position work location (e.g. 'Corpus Christi, TX', 'New York, NY', 'Seattle, WA', 'Indianapolis, IN', 'Ann Arbor, MI', 'Austin, TX', or 'London, UK')
- "country": country name
- "research_topics": list of 2-4 research topics matching the targeted track
- "concise_summary": 1 concise sentence summarizing role focus and minimum degree qualification. If multiple positions/tracks are advertised, MUST start with the most relevant position in brackets (e.g. "[Transportation Systems Engineering (TSE)] ...")
"""
        raw_data = self._call_gemini_json(prompt)
        if raw_data is None:
            return False

        if isinstance(raw_data, dict) and "jobs" in raw_data:
            raw_data = raw_data["jobs"]
        if not isinstance(raw_data, list):
            return False

        results_by_id = {item["id"]: item for item in raw_data if isinstance(item, dict) and "id" in item}
        if not results_by_id:
            return False

        for posting in batch:
            data = results_by_id.get(posting.id)
            if not data:
                continue
            self._apply_evaluation_result(posting, data, is_update_mode=is_update_mode)
            score_str = f"Fit: {posting.fit_score}/10" if posting.fit_score else "Fit: N/A"
            self.logger.info(f"Enriched (Batch): {posting.title} @ {posting.institution} ({score_str})")

        return True

    @staticmethod
    def _parse_llm_json(response_text: str) -> Any:
        """Robustly parse JSON (dict or list) from LLM output, extracting code fences or JSON blocks."""
        text = response_text.strip()
        try:
            return json.loads(text)
        except Exception:
            pass

        m_block = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text, re.IGNORECASE)
        if m_block:
            try:
                return json.loads(m_block.group(1).strip())
            except Exception:
                pass

        for pattern in (r"\[[\s\S]*\]", r"\{[\s\S]*\}"):
            m = re.search(pattern, text)
            if m:
                try:
                    return json.loads(m.group(0).strip())
                except Exception:
                    pass

        raise ValueError(f"Could not parse valid JSON from LLM response: {text[:200]}...")

    def _enrich_single(self, posting: JobPosting, is_update_mode: bool = False) -> None:
        """Enrich a single JobPosting safely without raising unhandled exceptions."""
        if not is_update_mode and not JobPosting.is_valid_faculty_posting(posting.title, posting.raw_description or posting.summary):
            posting.status = "Filtered (Non-Faculty / Seniority / Adjunct)"
            posting.fit_score = 1
            posting.fit_reason = f"Screened out: Position title '{posting.title}' is senior-only, adjunct, continuing education, or non-faculty."
            return

        if not self.client:
            return

        desc_cache = self._load_description_cache()
        self._prepare_posting_description(posting, desc_cache)
        self._save_description_cache(desc_cache)

        template = self._get_prompt_template()
        candidate_profile_text = self.cv_matcher.get_prompt_context()

        prompt = (
            template.replace("{candidate_profile}", candidate_profile_text)
            .replace("{title}", posting.title or "")
            .replace("{institution}", posting.institution or "")
            .replace("{location}", posting.location or "")
            .replace("{source}", posting.source or "")
            .replace("{raw_description}", posting.raw_description or "")
        )

        data = self._call_gemini_json(prompt)
        if isinstance(data, list) and data and isinstance(data[0], dict):
            data = data[0]
        if not isinstance(data, dict):
            self.logger.warning(f"Skipping single enrichment update for '{posting.title}' @ '{posting.institution}' (no valid JSON dict returned).")
            return

        self._apply_evaluation_result(posting, data, is_update_mode=is_update_mode)
        score_str = f"Fit: {posting.fit_score}/10" if posting.fit_score else "Fit: N/A"
        self.logger.info(f"Enriched (Single): {posting.title} @ {posting.institution} ({score_str})")
