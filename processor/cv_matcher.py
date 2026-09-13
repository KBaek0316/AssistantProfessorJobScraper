import json
import logging
import os
from typing import Any, Dict, Optional


class CVProfileManager:
    """Manages extraction and caching of candidate research profile from CV.pdf."""

    CACHE_FILE = os.path.join(".cache", "cv_profile.json")
    DEFAULT_CV_PATH = "CV.pdf"

    # Built-in fallback profile in case CV.pdf is not present (e.g. on GitHub Actions runner)
    FALLBACK_PROFILE = {
        "candidate_name": "Kwangho Baek, Ph.D.",
        "primary_field": "Transportation Engineering & Planning",
        "research_specialties": [
            "Travel Behavior Analysis",
            "Transit Planning and Operations",
            "AI-Integrated Discrete Choice Modeling",
            "Passive/Active Data Fusion",
            "Mobility-as-a-Service (MaaS)",
            "Rural Transit & Transportation Equity",
            "Shared Mobility & Intelligent Transportation Systems",
        ],
        "target_departments": [
            "Civil and Environmental Engineering (Transportation Engineering track)",
            "Transportation Engineering",
            "Urban Planning and Policy (Transportation / Mobility track)",
            "Industrial and Systems Engineering (Mobility systems)",
            "Interdisciplinary Computing / Data Science for Mobility",
        ],
        "irrelevant_subfields": [
            "Water Resources and Hydrology",
            "Structural Engineering",
            "Geotechnical Engineering",
            "Environmental Chemistry & Water Treatment",
            "Pavement and Materials Engineering",
            "Non-transportation staff or general administration",
        ],
    }

    def __init__(self, cv_path: Optional[str] = None):
        self.logger = logging.getLogger("processor.cv_matcher")
        self.cv_path = cv_path or ("CV.pdf" if os.path.exists("CV.pdf") else ("cv.pdf" if os.path.exists("cv.pdf") else None))
        self.profile: Dict[str, Any] = self._load_or_create_profile()

    def _load_or_create_profile(self) -> Dict[str, Any]:
        # 1. Check existing disk cache
        if os.path.exists(self.CACHE_FILE):
            try:
                with open(self.CACHE_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    # If CV file exists and is newer than cache, re-extract
                    if self.cv_path and os.path.getmtime(self.cv_path) > os.path.getmtime(self.CACHE_FILE):
                        self.logger.info("CV file updated since last cache. Re-analyzing...")
                    else:
                        self.logger.info("Loaded candidate research profile from cache.")
                        return data
            except Exception as e:
                self.logger.warning(f"Failed loading {self.CACHE_FILE}: {e}")

        # 2. If CV.pdf exists on disk, parse it
        if self.cv_path and os.path.exists(self.cv_path):
            try:
                import pypdf
                reader = pypdf.PdfReader(self.cv_path)
                full_text = "".join([page.extract_text() or "" for page in reader.pages])
                if len(full_text) > 300:
                    profile = self._extract_profile_with_gemini(full_text[:10000])
                    if profile:
                        self._save_cache(profile)
                        return profile
            except Exception as e:
                self.logger.error(f"Error parsing CV from {self.cv_path}: {e}")

        # 3. Fallback to default candidate profile
        self.logger.info("Using built-in candidate profile.")
        self._save_cache(self.FALLBACK_PROFILE)
        return self.FALLBACK_PROFILE

    def _extract_profile_with_gemini(self, cv_text: str) -> Optional[Dict[str, Any]]:
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            return None

        try:
            from google import genai
            client = genai.Client(api_key=api_key)
            prompt = f"""
Analyze this academic CV and extract a concise research profile for matching faculty job openings:
\"\"\"{cv_text}\"\"\"

Return strictly valid JSON with this structure:
{{
  "candidate_name": "Full name and highest degree",
  "primary_field": "Primary research field (e.g. Transportation Engineering & Planning)",
  "research_specialties": ["List 5-8 primary research areas"],
  "target_departments": ["Academic departments where this candidate is a strong fit"],
  "irrelevant_subfields": ["Subfields in civil/urban/engineering that this candidate does NOT do (e.g. Water Resources, Structures, Geotech)"]
}}
"""
            resp = client.models.generate_content(model="gemini-3.6-flash", contents=prompt)
            clean_json = resp.text.strip()
            if clean_json.startswith("```"):
                clean_json = clean_json.strip("`")
                if clean_json.startswith("json"):
                    clean_json = clean_json[4:].strip()
            data = json.loads(clean_json)
            self.logger.info("Extracted candidate profile from CV using Gemini successfully.")
            return data
        except Exception as e:
            self.logger.warning(f"Failed extracting profile via Gemini: {e}")
            return None

    def _save_cache(self, profile: Dict[str, Any]):
        try:
            os.makedirs(os.path.dirname(self.CACHE_FILE), exist_ok=True)
            with open(self.CACHE_FILE, "w", encoding="utf-8") as f:
                json.dump(profile, f, indent=2)
        except Exception as e:
            self.logger.warning(f"Failed writing cache to {self.CACHE_FILE}: {e}")

    def get_prompt_context(self) -> str:
        """Format candidate profile as prompt context for job evaluation."""
        p = self.profile
        specialties = ", ".join(p.get("research_specialties", []))
        departments = ", ".join(p.get("target_departments", []))
        irrelevant = ", ".join(p.get("irrelevant_subfields", []))

        return f"""Candidate Research Profile:
- Name: {p.get('candidate_name', 'Candidate')}
- Core Field: {p.get('primary_field', 'Transportation Engineering')}
- Target Departments: {departments}
- Core Research Specialties: {specialties}
- Irrelevant / Non-Matching Subfields: {irrelevant} (e.g. water resources, structures, environmental chemistry without transportation, or non-transportation disciplines)
"""
