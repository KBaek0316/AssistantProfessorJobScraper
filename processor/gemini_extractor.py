import json
import logging
import os
from typing import List, Optional
from scrapers.base import JobPosting


class GeminiExtractor:
    """Uses Google Gemini (e.g. Gemini 2.5 Pro or Flash) to parse unstructured job descriptions into structured fields and concise summaries."""

    def __init__(self, api_key: Optional[str] = None, model_name: Optional[str] = None):
        self.logger = logging.getLogger("processor.gemini")
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY", "").strip()
        self.model_name = model_name or os.environ.get("GEMINI_MODEL", "gemini-3.6-flash").strip()
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

    def enrich_postings(self, postings: List[JobPosting]) -> List[JobPosting]:
        """Enrich a list of newly found job postings with Gemini structured data."""
        if not postings:
            return postings

        if not self.client:
            self.logger.info("Skipping Gemini enrichment (client not configured). Using raw scraper fields.")
            for p in postings:
                if not p.summary:
                    p.summary = p.raw_description[:200] + "..." if len(p.raw_description) > 200 else p.raw_description
            return postings

        self.logger.info(f"Enriching {len(postings)} new job postings with Gemini ({self.model_name})...")

        for idx, posting in enumerate(postings):
            try:
                self._enrich_single(posting)
                self.logger.info(f"[{idx+1}/{len(postings)}] Enriched: {posting.title} @ {posting.institution}")
            except Exception as e:
                self.logger.error(f"Failed to enrich job '{posting.title}': {e}")
                if not posting.summary:
                    posting.summary = posting.raw_description[:200]

        return postings

    def _enrich_single(self, posting: JobPosting):
        prompt = f"""
Analyze this academic job posting for an Assistant Professor in Transportation / Civil Engineering:

Title: {posting.title}
Institution (scraped): {posting.institution}
Location (scraped): {posting.location}
Source: {posting.source}
Raw description / text snippet:
\"\"\"{posting.raw_description}\"\"\"

Extract the following in strict JSON format:
{{
  "clean_title": "The exact official position title (e.g. Assistant Professor of Transportation Engineering)",
  "institution": "Official university or college name (e.g. University of California, Berkeley)",
  "department": "Department, school, or division name",
  "tenure_track": "Tenure-Track, Tenured, Non-Tenure Track, or Unspecified",
  "deadline": "Application deadline (YYYY-MM-DD, or 'Open until filled', or 'Review begins [Date]')",
  "salary": "Salary range if mentioned, otherwise 'Not specified'",
  "city_state": "City and State in USA (e.g. Austin, TX)",
  "summary": "Strictly 1 to 2 sentences summarizing the core research/teaching focus and primary qualification required."
}}
Return ONLY valid JSON without markdown formatting or conversational text.
"""
        # Call Google GenAI SDK with multi-model fallback cascade
        response_text = ""
        candidate_models = [self.model_name, "gemini-3.6-flash", "gemini-3.1-pro-preview", "gemini-1.5-flash"]
        # Deduplicate while preserving order
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

        # Update posting attributes
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
        if data.get("summary"):
            posting.summary = data["summary"].strip()
