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
            try:
                self._enrich_single(posting)
                score_str = f"Fit: {posting.fit_score}/10" if posting.fit_score else "Fit: N/A"
                self.logger.info(f"[{idx+1}/{len(postings)}] Enriched: {posting.title} @ {posting.institution} ({score_str})")
            except Exception as e:
                if "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e):
                    self.logger.warning(f"Rate limit encountered on '{posting.title}'. Waiting 15s before retry...")
                    time.sleep(15)
                    try:
                        self._enrich_single(posting)
                        self.logger.info(f"[{idx+1}/{len(postings)}] Retry succeeded: {posting.title}")
                    except Exception as retry_err:
                        self.logger.error(f"Retry failed for '{posting.title}': {retry_err}")
                else:
                    self.logger.error(f"Failed to enrich job '{posting.title}': {e}")
                if not posting.summary:
                    posting.summary = posting.raw_description[:200]

            # Polite delay between API calls to respect free tier rate limits
            if idx < len(postings) - 1:
                time.sleep(3.0)

        return postings

    def _enrich_single(self, posting: JobPosting):
        if not self.client:
            return

        template = self._get_prompt_template()
        candidate_profile_text = self.cv_matcher.get_prompt_context()

        # Safe variable replacement without interfering with JSON template braces
        prompt = template.replace("{candidate_profile}", candidate_profile_text)
        prompt = prompt.replace("{title}", posting.title or "")
        prompt = prompt.replace("{institution}", posting.institution or "")
        prompt = prompt.replace("{location}", posting.location or "")
        prompt = prompt.replace("{source}", posting.source or "")
        prompt = prompt.replace("{raw_description}", posting.raw_description or "")

        # Call Google GenAI SDK with multi-model fallback cascade
        response_text = ""
        candidate_models = [
            self.model_name,
            "gemini-3.5-flash-lite",
            "gemini-3.1-flash-lite",
            "gemini-3.7-flash",
            "gemini-3.8-flash",
            "gemini-3.5-flash",
            "gemini-3.6-flash",
        ]
        candidate_models = list(dict.fromkeys(candidate_models))

        last_error = None
        for m in candidate_models:
            try:
                if hasattr(self.client, "models"):
                    response = self.client.models.generate_content(
                        model=m,
                        contents=prompt,
                    )
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
                self.logger.warning(f"Model '{m}' failed with {err}. Trying next candidate model...")
                continue

        if not response_text:
            if last_error:
                raise last_error
            return

        # Clean markdown codeblocks if model wrapped in ```json ... ```
        cleaned_json = response_text.strip()
        if cleaned_json.startswith("```"):
            cleaned_json = cleaned_json.strip("`")
            if cleaned_json.startswith("json"):
                cleaned_json = cleaned_json[4:].strip()

        data = json.loads(cleaned_json)

        # 1. Non-faculty role check
        if data.get("is_faculty") is False:
            posting.status = "Filtered (Non-Faculty)"
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
            posting.title = data["clean_title"].strip()
        if data.get("institution"):
            posting.institution = data["institution"].strip()
        if data.get("department"):
            posting.field = data["department"].strip()
        if data.get("tenure_track"):
            posting.tenure_track = data["tenure_track"].strip()
        if data.get("deadline"):
            posting.deadline = data["deadline"].strip()
        if data.get("salary") and data["salary"] != "Not specified":
            posting.salary = data["salary"].strip()
        if data.get("city_state"):
            posting.location = data["city_state"].strip()

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
