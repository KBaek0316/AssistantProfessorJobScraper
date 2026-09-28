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

Extract JSON with fields: is_faculty (bool), fit_score (int 1-10), fit_reason (str), clean_title, institution, department, tenure_track, deadline, salary, city_state, research_topics (list), concise_summary (str).
"""

    def enrich_postings(self, postings: List[JobPosting]) -> List[JobPosting]:
        """Enrich a list of job postings with Gemini structured data and fit scores."""
        if not postings:
            return postings

        if not self.client:
            self.logger.info("Skipping Gemini enrichment (client not configured). Using raw scraper fields.")
            for p in postings:
                if not p.summary:
                    p.summary = p.raw_description[:200] + "..." if len(p.raw_description) > 200 else p.raw_description
            return postings

        self.logger.info(f"Enriching {len(postings)} job postings with Gemini ({self.model_name})...")
        import time

        for idx, posting in enumerate(postings):
            max_retries = 4
            backoff_delays = [5, 15, 30, 60]
            for attempt in range(max_retries):
                try:
                    self._enrich_single(posting)
                    score_str = f"Fit: {posting.fit_score}/10" if posting.fit_score else "Fit: N/A"
                    self.logger.info(f"[{idx+1}/{len(postings)}] Enriched: {posting.title} @ {posting.institution} ({score_str})")
                    break
                except Exception as e:
                    err_str = str(e).upper()
                    is_transient = any(x in err_str for x in ("429", "RESOURCE_EXHAUSTED", "503", "UNAVAILABLE", "OVERLOADED"))
                    if is_transient and attempt < max_retries - 1:
                        delay = backoff_delays[attempt]
                        self.logger.warning(f"Rate limit / transient error on '{posting.title}' (attempt {attempt+1}/{max_retries}). Backing off {delay}s...")
                        time.sleep(delay)
                    else:
                        self.logger.error(f"Failed to enrich job '{posting.title}': {e}")
                        break
            if not posting.summary:
                posting.summary = posting.raw_description[:200] if posting.raw_description else (posting.field or posting.title)

            # Polite delay between API calls to respect free tier rate limits (15 RPM -> >= 4.0s)
            if idx < len(postings) - 1:
                time.sleep(4.0)

        return postings

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

    def _enrich_single(self, posting: JobPosting):
        # 0. Immediate Title-Level Seniority, Adjunct & Continuing Ed Pre-Filter
        if not JobPosting.is_valid_faculty_posting(posting.title, posting.raw_description or posting.summary):
            posting.status = "Filtered (Non-Faculty / Seniority / Adjunct)"
            posting.fit_score = 1
            posting.fit_reason = f"Screened out: Position title '{posting.title}' is senior-only, adjunct, continuing education, or non-faculty."
            return

        if not self.client:
            return

        # Ensure raw_description is populated via cache, on-demand fetch, or metadata synthesis
        desc_cache = self._load_description_cache()
        if not posting.raw_description:
            cached_desc = desc_cache.get(posting.id) or desc_cache.get(posting.link)
            if cached_desc:
                posting.raw_description = cached_desc
            else:
                fetched_desc = self._fetch_description_fallback(posting)
                if fetched_desc:
                    posting.raw_description = fetched_desc
                    desc_cache[posting.id] = fetched_desc
                    desc_cache[posting.link] = fetched_desc
                    self._save_description_cache(desc_cache)
                else:
                    # Synthesize description from available metadata rather than leaving it empty
                    posting.raw_description = (
                        f"Position Title: {posting.title}. "
                        f"Institution: {posting.institution}. "
                        f"Department / Division: {posting.field or 'Academic Department'}. "
                        f"Location: {posting.location or 'Not specified'}. "
                        f"Summary Context: {posting.summary or 'Tenure-track academic faculty position'}. "
                        f"Official Application Link: {posting.link}"
                    )
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
            "gemini-3.8-flash",
            "gemini-3.7-flash",
            "gemini-3.6-flash",
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
                self.logger.warning(f"Model '{m}' call failed: {err}. Trying next candidate model...")
                continue

        if not response_text:
            if last_error:
                raise last_error
            return

        data = self._parse_llm_json(response_text)

        # 1. Non-faculty / senior role check from LLM
        if data.get("is_faculty") is False:
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

        # Weak screening filter: flag jobs with fit score below threshold
        if posting.fit_score is not None and posting.fit_score < self.min_fit_score:
            posting.status = "Filtered (Low Relevance)"

        # 3. Update posting attributes
        if data.get("clean_title"):
            clean_t = data["clean_title"].strip()
            if JobPosting.is_valid_faculty_posting(clean_t, posting.raw_description):
                posting.title = clean_t
        if data.get("institution"):
            posting.institution = data["institution"].strip()
        if data.get("department"):
            posting.field = data["department"].strip()
        if data.get("tenure_track"):
            posting.tenure_track = data["tenure_track"].strip()
        if data.get("deadline"):
            posting.deadline = data["deadline"].strip()

        # Deterministic deadline fallback: if LLM returned unspecified/open or missing, check raw description
        if not posting.deadline or posting.deadline.lower() in ("not specified", "unspecified", "see full listing", "open until filled"):
            extracted_dl = JobPosting.extract_deadline_from_text(posting.raw_description)
            if extracted_dl:
                posting.deadline = extracted_dl

        if data.get("salary") and data["salary"] != "Not specified":
            posting.salary = data["salary"].strip()
        if data.get("city_state"):
            posting.location = data["city_state"].strip()

        # 4. Geographic scope validation
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
        concise = data.get("concise_summary", "").strip() or data.get("summary", "").strip()
        if concise:
            if posting.research_topics:
                posting.summary = f"{concise} | Research Topics: {posting.research_topics}"
            else:
                posting.summary = concise
