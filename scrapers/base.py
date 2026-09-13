import hashlib
import logging
import random
import time
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(asctime)s - %(name)s: %(message)s")


@dataclass
class JobPosting:
    """Represents an academic job posting."""
    id: str
    title: str
    institution: str
    field: str
    location: str
    deadline: str
    salary: str
    link: str
    source: str
    raw_description: str = ""
    summary: str = ""
    research_topics: str = ""
    fit_score: Optional[int] = None
    fit_reason: str = ""
    tenure_track: str = "Unspecified"
    date_first_seen: str = field(default_factory=lambda: datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    date_last_verified: str = field(default_factory=lambda: datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    status: str = "Active"
    latitude: Optional[float] = None
    longitude: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @staticmethod
    def generate_id(source: str, identifier: str) -> str:
        """Create a deterministic unique ID for a posting."""
        raw = f"{source.lower().strip()}:{identifier.strip()}".encode("utf-8")
        return hashlib.sha256(raw).hexdigest()[:16]

    @staticmethod
    def is_valid_faculty_posting(title: str, text_snippet: str = "") -> bool:
        """Filter out non-faculty roles (drivers, postdocs, technicians, staff, fellows)."""
        combined = f"{title} {text_snippet}".lower()

        # Instant rejection patterns for non-professorial staff and trainees
        excluded_patterns = [
            r"\bdriver\b", r"\bbus driver\b", r"\bpostdoc\b", r"\bpost-doc\b",
            r"\bpostdoctoral\b", r"\bresearch fellow\b", r"\bproject officer\b",
            r"\bintern\b", r"\btechnician\b", r"\bcustodian\b", r"\belementary\b",
            r"\bk-12\b", r"\blab manager\b", r"\bundergraduate\b", r"\bgraduate student\b"
        ]
        import re
        for pat in excluded_patterns:
            if re.search(pat, combined):
                return False

        # Must indicate an academic faculty / professorship appointment
        faculty_indicators = ["professor", "faculty", "lecturer", "instructor", "chair", "open rank"]
        if not any(ind in title.lower() for ind in faculty_indicators):
            return False

        return True


class BaseScraper(ABC):
    """Abstract Base Class for all website scrapers."""

    def __init__(self, name: str):
        self.name = name
        self.logger = logging.getLogger(f"scraper.{name}")
        self.session = self._create_session()

    def _create_session(self) -> requests.Session:
        session = requests.Session()
        retries = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["HEAD", "GET", "POST", "OPTIONS"],
        )
        adapter = HTTPAdapter(max_retries=retries)
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "en-US,en;q=0.9",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        })
        return session

    def polite_sleep(self, min_sec: float = 1.0, max_sec: float = 2.5):
        """Random delay between requests to be respectful of host servers."""
        time.sleep(random.uniform(min_sec, max_sec))

    @abstractmethod
    def scrape(self, query: str = "Assistant Professor Transportation", max_results: int = 20) -> List[JobPosting]:
        """Execute scraping logic and return a list of JobPosting objects."""
        pass
