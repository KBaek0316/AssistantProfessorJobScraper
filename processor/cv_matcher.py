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
            "Civil and Environmental Engineering (Transportation Engineering / Systems track, or open/multi-track CEE searches)",
            "Transportation Engineering / Planning",
            "Urban and Regional Planning / Public Affairs (Transportation / Mobility track)",
            "Spatial Data Science / Urban Informatics for Mobility",
        ],
        "irrelevant_subfields": [
            "Heavy Industrial Engineering (Manufacturing, Production Systems, Ergonomics, Human Factors)",
            "Robotics & Mechanical Systems (Mechatronics, physical robotics, embodied AI, vehicle hardware)",
            "Supply Chain Management & Freight Logistics (Business school operations, inventory, warehousing)",
            "Water Resources and Hydrology",
            "Structural Engineering",
            "Geotechnical Engineering",
            "Environmental Chemistry & Water Treatment",
            "Pavement and Materials Engineering",
            "Non-transportation staff or general administration",
        ],
    }

    @staticmethod
    def _compute_cv_hash(filepath: Optional[str]) -> str:
        """Compute SHA-256 hash of CV file to detect content modifications."""
        if not filepath or not os.path.exists(filepath):
            return ""
        import hashlib
        try:
            with open(filepath, "rb") as f:
                return hashlib.sha256(f.read()).hexdigest()
        except Exception:
            return ""

    def __init__(self, cv_path: Optional[str] = None):
        self.logger = logging.getLogger("processor.cv_matcher")
        self.cv_path = cv_path or ("CV.pdf" if os.path.exists("CV.pdf") else ("cv.pdf" if os.path.exists("cv.pdf") else None))
        self.profile: Dict[str, Any] = self._load_or_create_profile()

    def _load_or_create_profile(self) -> Dict[str, Any]:
        current_hash = self._compute_cv_hash(self.cv_path) if self.cv_path else ""

        # 1. Check existing disk cache
        if os.path.exists(self.CACHE_FILE):
            try:
                with open(self.CACHE_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    cached_hash = data.get("_cv_hash", "")

                    # Re-extract if CV file exists and has changed (different hash or newer mtime)
                    cv_changed = False
                    if self.cv_path and os.path.exists(self.cv_path):
                        if current_hash and cached_hash and current_hash != cached_hash:
                            cv_changed = True
                        elif not cached_hash and os.path.getmtime(self.cv_path) > os.path.getmtime(self.CACHE_FILE):
                            cv_changed = True

                    if cv_changed:
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

        candidate_models = [
            os.environ.get("GEMINI_MODEL", "gemini-3.7-flash").strip(),
            "gemini-3.5-flash-lite",
            "gemini-3.7-flash",
            "gemini-3.6-flash",
            "gemini-3.8-flash",
        ]
        candidate_models = list(dict.fromkeys(candidate_models))

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
  "irrelevant_subfields": ["Subfields in the candidate's broader discipline that this candidate does NOT do (e.g. if civil engineering: Water Resources, Structures; if computer science: Graphics, Hardware; if other fields: subdisciplines outside their research)"]
}}
"""
            resp_text = None
            for model_name in candidate_models:
                try:
                    resp = client.models.generate_content(model=model_name, contents=prompt)
                    if resp and resp.text:
                        resp_text = resp.text
                        break
                except Exception as m_err:
                    self.logger.warning(f"Profile extraction with model '{model_name}' failed: {m_err}")

            if not resp_text:
                return None

            clean_json = resp_text.strip()
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
            to_save = dict(profile)
            if self.cv_path and os.path.exists(self.cv_path):
                h = self._compute_cv_hash(self.cv_path)
                if h:
                    to_save["_cv_hash"] = h
            with open(self.CACHE_FILE, "w", encoding="utf-8") as f:
                json.dump(to_save, f, indent=2)
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
- Core Field: {p.get('primary_field') or 'Academic Research & Teaching'}
- Target Departments: {departments}
- Core Research Specialties: {specialties}
- Irrelevant / Non-Matching Subfields: {irrelevant if irrelevant else 'None specified'}
"""
