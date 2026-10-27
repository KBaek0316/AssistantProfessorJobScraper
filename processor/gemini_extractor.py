import json
import logging
import os
from typing import List, Optional
from scrapers.base import JobPosting
from processor.cv_matcher import CVProfileManager


class GeminiExtractor:
    """Uses Google Gemini to parse unstructured job descriptions into structured fields,
    evaluating candidate fit (1-10) using candidate CV profile and user-editable prompt.
    """

    DEFAULT_PROMPT_FILE = "eval_prompt.txt"

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
        self.model_name = model_name or os.environ.get("GEMINI_MODEL", "gemini-3.7-flash").strip()
        self.prompt_file = prompt_file or self.DEFAULT_PROMPT_FILE
        self.min_fit_score = min_fit_score
        self.cv_matcher = CVProfileManager(cv_path=cv_path)
        self.client = None

        if self.api_key:
            try:
                from google import genai
                self.client = genai.Client(api_key=self.api_key)
                self.logger.info(f"Initialized Gemini client successfully with model: {self.model_name}")
            except ImportError:
                # Fallback to google.generativeai if google-genai is not yet installed
                try:
                    import google.generativeai as genai_legacy
                    genai_legacy.configure(api_key=self.api_key)
                    self.client = genai_legacy
                    self.logger.info("Initialized legacy google.generativeai client.")
                except ImportError:
                    self.logger.warning("Neither google-genai nor google-generativeai is installed.")
        else:
            self.logger.warning("GEMINI_API_KEY not found in environment. Running in fallback mode without LLM summarization.")

    def _get_prompt_template(self) -> str:
        """Load prompt template from user-editable text file or fall back to default."""
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

If multiple positions with distinct research topics are advertised, select the single most relevant track to the candidate (e.g. Transportation Systems Engineering).
Extract JSON with fields: is_faculty (bool), fit_score (int 1-10), fit_reason (str), clean_title, institution, department, targeted_track (str or null), tenure_track, deadline, salary, city_state, research_topics (list), concise_summary (str, starting with "[<Track Name>] ..." if multiple positions advertised).
"""

    def _get_evaluation_instructions(self) -> str:
        """Extract the evaluation instructions section from the prompt template (eval_prompt.txt).

        Allows custom user instructions in eval_prompt.txt to govern both batch and single evaluations.
        """
        template = self._get_prompt_template()
        if "=== EVALUATION INSTRUCTIONS ===" in template:
            parts = template.split("=== EVALUATION INSTRUCTIONS ===")
            after = parts[1]
            if "=== REQUIRED JSON OUTPUT FORMAT ===" in after:
                instructions = after.split("=== REQUIRED JSON OUTPUT FORMAT ===")[0].strip()
            elif "=== OUTPUT FORMAT ===" in after:
                instructions = after.split("=== OUTPUT FORMAT ===")[0].strip()
            else:
                instructions = after.strip()
            if instructions:
                return instructions

        return """1. Determine Position Eligibility & Seniority:
   - Target positions: Tenure-track Assistant Professor, Open Rank Faculty searches that explicitly include Assistant Professor, and career-track university faculty appointments.
   - EXCLUDE (set "is_faculty" to false or assign fit_score: 1 with explanatory fit_reason):
     * Seniority-only roles: Pure Associate Professor (without Assistant), Full Professor, Department Chair, Division Chair, Dean.
     * Contingent / part-time / non-degree roles: Adjunct Faculty/Professor, Lecturer in Continuing Education, Adult Education, Extension.
     * Trainees and non-faculty staff: Postdocs, research fellows, technicians, staff.
2. Evaluate Geographic Scope:
   - Target Regions: US, Canada, Europe, Hong Kong, Singapore, Japan, South Korea, Taiwan.
   - EXCLUDE: Non-target countries (e.g. Mainland China, Middle East, Latin America, South Asia, Africa). Set fit_score: 1 with fit_reason explaining location.
3. Candidate Fit Score (1 to 10 scale):
   Evaluate the posting against candidate's Core Field, Target Departments, and Research Specialties in the CANDIDATE PROFILE:
   - 9-10 (Core Match): Dedicated Assistant Professor position directly matching candidate's primary field and core research specialties.
   - 7-8 (Strong Interdisciplinary Match): Assistant Professor in related disciplines or target departments seeking candidate's core expertise.
   - 5-6 (Broad Fit): Broad department search where candidate's subfield is an acceptable focus area.
   - 3-4 (Low Fit): General department faculty searches with peripheral overlap.
   - 1-2 (Screened Out / Irrelevant): Completely unrelated fields or non-matching subfields.
   - Generic Titles with Missing / Snippet-Only Descriptions: If a posting only provides a generic faculty title without explicit departmental or research specialization details in the text, DO NOT assume or fabricate a core match. Cap fit_score at 3-5 (typically 3-4) with fit_reason explaining that specific department/specialization details are unavailable.
4. Handling Multiple Positions / Tracks / Research Topics in a Single Posting:
   - If multiple positions with distinct research topics are advertised, identify the single most relevant position/track (e.g. "Transportation Systems Engineering (TSE)"), evaluate fit_score, fit_reason, and research_topics based on that track, specify "targeted_track", and ensure "concise_summary" starts with "[<Track Name>] ...".
5. Department, Campus & Location Extraction:
   - Extract official Department, School, or Division name from the posting body.
   - For multi-campus systems or satellite institutes (e.g., Texas A&M Corpus Christi, Cornell Tech NYC, Northeastern Seattle, Purdue Indianapolis, Penn State Altoona), ALWAYS retain the specific campus in "institution" and specify the actual physical city/state in "city_state", NEVER collapsing branch campuses into only the flagship name or flagship city.
6. Provide a concise, 1-sentence "fit_reason"."""

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
        import time

        # Pre-filter obvious non-faculty and out-of-scope locations (only for fresh evaluation, preserve existing jobs in update mode)
        to_call_llm = []
        for p in postings:
            if not is_update_mode and not JobPosting.is_valid_faculty_posting(p.title, p.raw_description or p.summary):
                p.status = "Filtered (Non-Faculty / Seniority / Adjunct)"
                p.fit_score = 1
                p.fit_reason = f"Screened out: Position title '{p.title}' is senior-only, adjunct, continuing education, or non-faculty."
            elif not is_update_mode and p.location and not JobPosting.is_allowed_location(p.location):
                p.status = "Filtered (Location Outside Scope)"
                p.fit_score = 1
                p.fit_reason = f"Screened out: Location '{p.location}' is outside target geographic scope."
            else:
                to_call_llm.append(p)

        if to_call_llm:
            if len(to_call_llm) > 1:
                batch_size = 5
                for i in range(0, len(to_call_llm), batch_size):
                    chunk = to_call_llm[i:i + batch_size]
                    success = self._enrich_batch(chunk, is_update_mode=is_update_mode)
                    if not success:
                        for p in chunk:
                            self._enrich_single(p, is_update_mode=is_update_mode)
                    if i + batch_size < len(to_call_llm):
                        time.sleep(1.5)
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

        batch_input = []
        desc_cache = self._load_description_cache()
        for p in batch:
            if not p.raw_description or len(p.raw_description.strip()) < 300:
                cached = desc_cache.get(p.id) or desc_cache.get(p.link)
                if cached and len(cached.strip()) >= 300:
                    p.raw_description = cached
                else:
                    fetched = self._fetch_description_fallback(p)
                    if fetched and len(fetched.strip()) > len(p.raw_description or ""):
                        p.raw_description = fetched
                        desc_cache[p.id] = fetched
                        desc_cache[p.link] = fetched
                    elif not p.raw_description:
                        p.raw_description = (
                            f"Position Title: {p.title}. "
                            f"Institution: {p.institution}. "
                            f"Department: {p.field or 'Academic Department'}. "
                            f"Location: {p.location or 'Not specified'}. "
                            f"Summary Context: {p.summary or 'Tenure-track academic faculty position'}. "
                            f"Link: {p.link}"
                        )
            if p.raw_description and len(p.raw_description.strip()) < 300:
                if "[Note: Detailed job description" not in p.raw_description:
                    p.raw_description = f"{p.raw_description.strip()} [Note: Detailed job description could not be retrieved from the source board; evaluate conservatively based only on verified text.]"
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
        candidate_models = [
            self.model_name,
            "gemini-3.5-flash-lite",
            "gemini-3.1-flash-lite",
            "gemini-3.1-flash-lite-preview",
            "gemini-3-flash-preview",
            "gemini-3.7-flash",
            "gemini-3.6-flash",
            "gemini-3.8-flash",
            "gemini-3.5-flash",
        ]
        candidate_models = list(dict.fromkeys(candidate_models))

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
        for m in candidate_models:
            try:
                if hasattr(self.client, "models"):
                    kwargs = {"model": m, "contents": prompt}
                    if gen_config:
                        kwargs["config"] = gen_config
                    resp = self.client.models.generate_content(**kwargs)
                    response_text = resp.text
                else:
                    model_obj = self.client.GenerativeModel(m)
                    resp = model_obj.generate_content(prompt)
                    response_text = resp.text
                if response_text:
                    break
            except Exception as err:
                err_msg = str(err)
                if any(x in err_msg for x in ("503", "429", "UNAVAILABLE", "RESOURCE_EXHAUSTED", "high demand", "quota")):
                    self.logger.warning(f"Batch call on '{m}' hit rate limit/service spike ({err}). Sleeping 10s before retry...")
                    import time
                    time.sleep(10)
                else:
                    self.logger.warning(f"Batch call failed on '{m}': {err}. Trying next model...")
                continue

        if not response_text:
            return False

        try:
            raw_data = self._parse_llm_json(response_text)
            if isinstance(raw_data, dict) and "jobs" in raw_data:
                raw_data = raw_data["jobs"]
            if not isinstance(raw_data, list):
                return False

            results_by_id = {item["id"]: item for item in raw_data if isinstance(item, dict) and "id" in item}

            for posting in batch:
                data = results_by_id.get(posting.id)
                if not data:
                    continue

                if data.get("is_faculty") is False:
                    if not is_update_mode:
                        posting.status = "Filtered (Non-Faculty / Seniority)"
                    posting.fit_score = 1
                    if data.get("fit_reason"):
                        posting.fit_reason = str(data["fit_reason"]).strip()
                else:
                    fit_score_raw = data.get("fit_score")
                    if fit_score_raw is not None:
                        try:
                            posting.fit_score = max(1, min(10, int(fit_score_raw)))
                        except (ValueError, TypeError):
                            posting.fit_score = None
                    if data.get("fit_reason"):
                        posting.fit_reason = str(data["fit_reason"]).strip()

                    if not is_update_mode:
                        if posting.fit_score is not None and posting.fit_score < self.min_fit_score:
                            posting.status = "Filtered (Low Relevance)"

                if data.get("clean_title"):
                    clean_t = data["clean_title"].strip()
                    if JobPosting.is_valid_faculty_posting(clean_t, posting.raw_description):
                        if not is_update_mode or not posting.title or posting.title.strip().lower() in ("faculty openings", "faculty position", "open rank", "professor"):
                            posting.title = clean_t
                if data.get("institution"):
                    inst = data["institution"].strip()
                    if not posting.institution or not is_update_mode:
                        posting.institution = inst
                if data.get("department"):
                    dept = data["department"].strip()
                    if not posting.field or not is_update_mode:
                        posting.field = dept
                if data.get("tenure_track"):
                    posting.tenure_track = data["tenure_track"].strip()
                if data.get("deadline"):
                    posting.deadline = data["deadline"].strip()
                    posting.deadline_date = JobPosting.extract_latest_deadline_date(posting.deadline)
                if data.get("salary") and data["salary"] != "Not specified":
                    posting.salary = data["salary"].strip()
                if data.get("city_state"):
                    posting.location = data["city_state"].strip()

                if not is_update_mode:
                    country = str(data.get("country", "")).strip()
                    if not JobPosting.is_allowed_location(posting.location, country):
                        posting.status = "Filtered (Location Outside Scope)"
                        posting.fit_score = 1
                        posting.fit_reason = f"Screened out: Location '{posting.location}' is outside target geographic scope."

                topics_data = data.get("research_topics", [])
                if isinstance(topics_data, list):
                    posting.research_topics = ", ".join(str(t).strip() for t in topics_data if t)
                elif isinstance(topics_data, str):
                    posting.research_topics = topics_data.strip()

                targeted_track = str(data.get("targeted_track") or "").strip()
                concise = data.get("concise_summary", "").strip() or data.get("summary", "").strip()
                if targeted_track and targeted_track.lower() not in ("null", "none"):
                    prefix = f"[{targeted_track}]"
                    if not concise.startswith(prefix) and not concise.lower().startswith(f"[{targeted_track.lower()}]"):
                        concise = f"{prefix} {concise}" if concise else prefix

                if concise:
                    if posting.research_topics:
                        posting.summary = f"{concise} | Research Topics: {posting.research_topics}"
                    else:
                        posting.summary = concise

                score_str = f"Fit: {posting.fit_score}/10" if posting.fit_score else "Fit: N/A"
                self.logger.info(f"Enriched (Batch): {posting.title} @ {posting.institution} ({score_str})")

            return True
        except Exception as parse_err:
            self.logger.warning(f"Failed parsing batch JSON response: {parse_err}. Falling back to single enrichment.")
            return False

    CACHE_DIR = ".cache"
    DESCRIPTIONS_CACHE = os.path.join(CACHE_DIR, "job_descriptions.json")

    def _load_description_cache(self) -> dict:
        if os.path.exists(self.DESCRIPTIONS_CACHE):
            try:
                with open(self.DESCRIPTIONS_CACHE, "r", encoding="utf-8") as f:
                    return json.load(f)
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
        """Fetch full job description on-the-fly if missing during evaluation."""
        clean_link = (posting.link or "").strip()
        if not clean_link:
            return ""

        src = (posting.source or "").lower()
        try:
            if "academickeys" in src or "academickeys.com" in clean_link:
                from scrapers.academickeys import AcademicKeysScraper
                scraper = AcademicKeysScraper()
                full_text, dept, dl = scraper._fetch_detail(clean_link)
                if dept and (not posting.field or posting.field.strip().lower() in ("not specified", "unspecified", "none", "", "transportation / civil engineering")):
                    posting.field = dept
                if dl and (not posting.deadline or posting.deadline.strip().lower() in ("not specified", "unspecified", "none", "")):
                    posting.deadline = dl
                return full_text

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
                        return div.get_text(" ", strip=True)

            elif "linkedin" in src or "linkedin.com" in clean_link:
                import re
                from scrapers.linkedin import LinkedInScraper
                m = re.search(r"(\d{8,})", clean_link)
                if m:
                    scraper = LinkedInScraper()
                    return scraper._fetch_job_description(m.group(1))

            elif "chronicle" in src or "chronicle.com" in clean_link:
                from scrapers.chronicle import ChronicleScraper
                scraper = ChronicleScraper()
                full_desc, dl, sal, inst, loc = scraper._fetch_detail_page(clean_link)
                if dl and (not posting.deadline or posting.deadline.strip().lower() in ("not specified", "unspecified", "none", "")):
                    posting.deadline = dl
                return full_desc

            elif "jobsacuk" in src or "jobs.ac.uk" in clean_link:
                from scrapers.jobsacuk import JobsAcUkScraper
                scraper = JobsAcUkScraper()
                return scraper._fetch_job_description(clean_link)

        except Exception as e:
            self.logger.debug(f"Could not fetch description fallback for {clean_link}: {e}")
        return ""

    @staticmethod
    def _parse_llm_json(response_text: str) -> dict:
        """Robustly parse JSON from LLM output, extracting code fences or {...} blocks."""
        import re
        text = response_text.strip()
        # 1. Direct parse attempt
        try:
            return json.loads(text)
        except Exception:
            pass

        # 2. Extract ```json ... ``` blocks
        m_block = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text, re.IGNORECASE)
        if m_block:
            try:
                return json.loads(m_block.group(1).strip())
            except Exception:
                pass

        # 3. Extract outermost { ... }
        m_curly = re.search(r"\{[\s\S]*\}", text)
        if m_curly:
            try:
                return json.loads(m_curly.group(0).strip())
            except Exception:
                pass

        raise ValueError(f"Could not parse valid JSON from LLM response: {text[:200]}...")

    def _enrich_single(self, posting: JobPosting, is_update_mode: bool = False):
        # 0. Immediate Title-Level Seniority, Adjunct & Continuing Ed Pre-Filter (only in fresh evaluation)
        if not is_update_mode and not JobPosting.is_valid_faculty_posting(posting.title, posting.raw_description or posting.summary):
            posting.status = "Filtered (Non-Faculty / Seniority / Adjunct)"
            posting.fit_score = 1
            posting.fit_reason = f"Screened out: Position title '{posting.title}' is senior-only, adjunct, continuing education, or non-faculty."
            return

        if not self.client:
            return

        # Ensure raw_description is populated via cache, on-demand fetch, or metadata synthesis
        desc_cache = self._load_description_cache()
        if not posting.raw_description or len(posting.raw_description.strip()) < 300:
            cached_desc = desc_cache.get(posting.id) or desc_cache.get(posting.link)
            if cached_desc and len(cached_desc.strip()) >= 300:
                posting.raw_description = cached_desc
            else:
                fetched_desc = self._fetch_description_fallback(posting)
                if fetched_desc and len(fetched_desc.strip()) > len(posting.raw_description or ""):
                    posting.raw_description = fetched_desc
                    desc_cache[posting.id] = fetched_desc
                    desc_cache[posting.link] = fetched_desc
                    self._save_description_cache(desc_cache)
                elif not posting.raw_description:
                    # Synthesize description from available metadata rather than leaving it empty
                    posting.raw_description = (
                        f"Position Title: {posting.title}. "
                        f"Institution: {posting.institution}. "
                        f"Department / Division: {posting.field or 'Academic Department'}. "
                        f"Location: {posting.location or 'Not specified'}. "
                        f"Summary Context: {posting.summary or 'Tenure-track academic faculty position'}. "
                        f"Official Application Link: {posting.link}"
                    )
            if posting.raw_description and len(posting.raw_description.strip()) < 300:
                if "[Note: Detailed job description" not in posting.raw_description:
                    posting.raw_description = f"{posting.raw_description.strip()} [Note: Detailed job description could not be retrieved from the source board; evaluate conservatively based only on verified text.]"
        else:
            # Store in cache
            if posting.id not in desc_cache or len(posting.raw_description) > len(desc_cache.get(posting.id, "")):
                desc_cache[posting.id] = posting.raw_description
                desc_cache[posting.link] = posting.raw_description
                self._save_description_cache(desc_cache)

        template = self._get_prompt_template()
        candidate_profile_text = self.cv_matcher.get_prompt_context()

        # Safe variable replacement without interfering with JSON template braces
        prompt = template.replace("{candidate_profile}", candidate_profile_text)
        prompt = prompt.replace("{title}", posting.title or "")
        prompt = prompt.replace("{institution}", posting.institution or "")
        prompt = prompt.replace("{location}", posting.location or "")
        prompt = prompt.replace("{source}", posting.source or "")
        prompt = prompt.replace("{raw_description}", posting.raw_description or "")

        # Prepare JSON format config if supported by google-genai
        gen_config = None
        try:
            from google.genai import types
            gen_config = types.GenerateContentConfig(
                response_mime_type="application/json",
                automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
            )
        except Exception:
            pass

        # Call Google GenAI SDK with verified multi-model fallback cascade
        response_text = ""
        candidate_models = [
            self.model_name,
            "gemini-3.5-flash-lite",
            "gemini-3.1-flash-lite",
            "gemini-3.1-flash-lite-preview",
            "gemini-3-flash-preview",
            "gemini-3.7-flash",
            "gemini-3.6-flash",
            "gemini-3.8-flash",
            "gemini-3.5-flash",
        ]
        candidate_models = list(dict.fromkeys(candidate_models))

        last_error = None
        for m in candidate_models:
            try:
                if hasattr(self.client, "models"):
                    kwargs = {"model": m, "contents": prompt}
                    if gen_config:
                        kwargs["config"] = gen_config
                    response = self.client.models.generate_content(**kwargs)
                    response_text = response.text
                else:
                    # Legacy SDK
                    model_obj = self.client.GenerativeModel(m)
                    response = model_obj.generate_content(prompt)
                    response_text = response.text
                if response_text:
                    break
            except Exception as err:
                last_error = err
                err_msg = str(err)
                if any(x in err_msg for x in ("503", "429", "UNAVAILABLE", "RESOURCE_EXHAUSTED", "high demand", "quota")):
                    self.logger.warning(f"Single enrichment call on '{m}' hit rate limit/service spike ({err}). Sleeping 10s before retry...")
                    import time
                    time.sleep(10)
                else:
                    self.logger.warning(f"Model '{m}' call failed: {err}. Trying next candidate model...")
                continue

        if not response_text:
            if last_error:
                raise last_error
            return

        data = self._parse_llm_json(response_text)

        # 1. Non-faculty / senior role check from LLM
        if data.get("is_faculty") is False:
            if not is_update_mode:
                posting.status = "Filtered (Non-Faculty / Seniority)"
            posting.fit_score = 1
            if data.get("fit_reason"):
                posting.fit_reason = str(data["fit_reason"]).strip()
            return

        # 2. Fit evaluation (1-10 score & reason)
        fit_score_raw = data.get("fit_score")
        if fit_score_raw is not None:
            try:
                fit_score_int = int(fit_score_raw)
                posting.fit_score = max(1, min(10, fit_score_int))
            except (ValueError, TypeError):
                posting.fit_score = None

        if data.get("fit_reason"):
            posting.fit_reason = str(data["fit_reason"]).strip()

        # Weak screening filter: flag jobs with fit score below threshold (only in fresh evaluation)
        if not is_update_mode and posting.fit_score is not None and posting.fit_score < self.min_fit_score:
            posting.status = "Filtered (Low Relevance)"

        # 3. Update posting attributes
        if data.get("clean_title"):
            clean_t = data["clean_title"].strip()
            if JobPosting.is_valid_faculty_posting(clean_t, posting.raw_description):
                if not is_update_mode or not posting.title or posting.title.strip().lower() in ("faculty openings", "faculty position", "open rank", "professor"):
                    posting.title = clean_t
        if data.get("institution"):
            inst = data["institution"].strip()
            if not posting.institution or not is_update_mode:
                posting.institution = inst
        if data.get("department"):
            dept = data["department"].strip()
            if not posting.field or not is_update_mode:
                posting.field = dept
        if data.get("tenure_track"):
            posting.tenure_track = data["tenure_track"].strip()
        if data.get("deadline"):
            posting.deadline = data["deadline"].strip()

        # Deterministic deadline fallback: if LLM returned unspecified/open or missing, check raw description
        if not posting.deadline or posting.deadline.lower() in ("not specified", "unspecified", "see full listing", "open until filled"):
            extracted_dl = JobPosting.extract_deadline_from_text(posting.raw_description)
            if extracted_dl:
                posting.deadline = extracted_dl

        if posting.deadline:
            posting.deadline_date = JobPosting.extract_latest_deadline_date(posting.deadline)

        if data.get("salary") and data["salary"] != "Not specified":
            posting.salary = data["salary"].strip()
        if data.get("city_state"):
            posting.location = data["city_state"].strip()

        # 4. Geographic scope validation
        if not is_update_mode:
            country = str(data.get("country", "")).strip()
            if not JobPosting.is_allowed_location(posting.location, country):
                posting.status = "Filtered (Location Outside Scope)"
                posting.fit_score = 1
                posting.fit_reason = f"Screened out: Location '{posting.location}' is outside target geographic scope (US, Europe, HK, Singapore, Japan, Korea, Taiwan; excluding Mainland China)."

        # Handle research topics
        topics_data = data.get("research_topics", [])
        if isinstance(topics_data, list):
            posting.research_topics = ", ".join(str(t).strip() for t in topics_data if t)
        elif isinstance(topics_data, str):
            posting.research_topics = topics_data.strip()

        # Format concise summary
        targeted_track = str(data.get("targeted_track") or "").strip()
        concise = data.get("concise_summary", "").strip() or data.get("summary", "").strip()
        if targeted_track and targeted_track.lower() not in ("null", "none"):
            prefix = f"[{targeted_track}]"
            if not concise.startswith(prefix) and not concise.lower().startswith(f"[{targeted_track.lower()}]"):
                concise = f"{prefix} {concise}" if concise else prefix

        if concise:
            if posting.research_topics:
                posting.summary = f"{concise} | Research Topics: {posting.research_topics}"
            else:
                posting.summary = concise
