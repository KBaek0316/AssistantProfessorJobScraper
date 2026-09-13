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

    @staticmethod
    def is_allowed_location(location: str, country: str = "") -> bool:
        """
        Validates whether a location or country falls within the target geographic scope:
        Allowed: US, European countries, Hong Kong, Singapore, Japan, South Korea, Taiwan.
        Strictly Excluded: Mainland China (PRC), other non-target countries (Middle East, Latin America, South Asia, Africa).
        """
        combined = f"{location} {country}".lower().strip()
        if not combined:
            return True

        import re

        # 1. Explicitly check Hong Kong or Taiwan first (preserves 'Hong Kong, China')
        if re.search(r"\b(hong\s*kong|hk|taiwan|taipei|hsinchu|tainan|taichung)\b", combined):
            return True

        # 2. Exclude Mainland China
        mainland_china_patterns = [
            r"\bchina\b", r"\bprc\b", r"\bmainland china\b", r"\bpeople's republic of china\b",
            r"\bbeijing\b", r"\bshanghai\b", r"\bshenzhen\b", r"\bguangzhou\b", r"\bwuhan\b",
            r"\bchengdu\b", r"\bhangzhou\b", r"\bnanjing\b", r"\btianjin\b", r"\bxi'?an\b",
            r"\bchongqing\b", r"\bharbin\b", r"\bsuzhou\b", r"\bzhejiang\b", r"\btsinghua\b",
            r"\bpeking university\b", r"\bfudan\b"
        ]
        for pat in mainland_china_patterns:
            if re.search(pat, combined):
                return False

        # 3. Exclude other non-target regions if explicitly mentioned
        excluded_regions = [
            r"\buae\b", r"\bunited arab emirates\b", r"\bsaudi arabia\b", r"\bqatar\b",
            r"\bkuwait\b", r"\boman\b", r"\bbahrain\b", r"\begypt\b", r"\bisrael\b",
            r"\bindia\b", r"\bpakistan\b", r"\bbangladesh\b",
            r"\bbrazil\b", r"\bmexico\b", r"\bchile\b", r"\bcolombia\b", r"\bargentina\b",
            r"\bsouth africa\b", r"\bnigeria\b", r"\bkenya\b",
            r"\brussia\b", r"\bbelarus\b", r"\bturkey\b", r"\btürkiye\b"
        ]
        for pat in excluded_regions:
            if re.search(pat, combined):
                return False

        # 4. Check Allowed Target Regions
        # US States and indicators
        us_patterns = [
            r"\b(al|ak|az|ar|ca|co|ct|de|fl|ga|hi|id|il|in|ia|ks|ky|la|me|md|ma|mi|mn|ms|mo|mt|ne|nv|nh|nj|nm|ny|nc|nd|oh|ok|or|pa|ri|sc|sd|tn|tx|ut|vt|va|wa|wv|wi|wy|dc)\b",
            r"\b(alabama|alaska|arizona|arkansas|california|colorado|connecticut|delaware|florida|georgia|hawaii|idaho|illinois|indiana|iowa|kansas|kentucky|louisiana|maine|maryland|massachusetts|michigan|minnesota|mississippi|missouri|montana|nebraska|nevada|new hampshire|new jersey|new mexico|new york|north carolina|north dakota|ohio|oklahoma|oregon|pennsylvania|rhode island|south carolina|south dakota|tennessee|texas|utah|vermont|virginia|washington|west virginia|wisconsin|wyoming)\b",
            r"\b(usa|united states|u\.s\.a?\b|america|puerto rico)\b"
        ]
        for pat in us_patterns:
            if re.search(pat, combined):
                return True

        # Canada (Provinces, territories, and major university cities)
        canada_patterns = [
            r"\b(canada|canadian)\b",
            r"\b(ontario|quebec|québec|british columbia|alberta|manitoba|saskatchewan|nova scotia|new brunswick|newfoundland)\b",
            r"\b(toronto|montreal|montréal|vancouver|ottawa|calgary|edmonton|waterloo|quebec city|winnipeg|halifax|hamilton|victoria)\b",
            r",\s*(on|qc|bc|ab|mb|sk|ns|nb|nl|pe)\b",
        ]
        for pat in canada_patterns:
            if re.search(pat, combined):
                return True

        # European countries
        european_patterns = [
            r"\b(united kingdom|uk|great britain|england|scotland|wales|northern ireland|london)\b",
            r"\b(germany|deutschland|berlin|munich|hamburg|frankfurt|stuttgart|aachen)\b",
            r"\b(france|paris|lyon|toulouse|marseille)\b",
            r"\b(netherlands|holland|amsterdam|delft|rotterdam|eindhoven|utrecht)\b",
            r"\b(switzerland|zurich|zürich|geneva|lausanne|eth zurich|epfl)\b",
            r"\b(sweden|stockholm|gothenburg|uppsala|kth)\b",
            r"\b(norway|oslo|trondheim|ntnu|bergen)\b",
            r"\b(denmark|copenhagen|aarhus|dtu)\b",
            r"\b(finland|helsinki|aalto|tampere|oulu)\b",
            r"\b(italy|italia|rome|milan|turin|politecnico di milano|politecnico di torino|bologna)\b",
            r"\b(spain|españa|madrid|barcelona|valencia)\b",
            r"\b(belgium|brussels|leuven|ghent)\b",
            r"\b(austria|vienna|wien|graz)\b",
            r"\b(ireland|dublin|cork|galway)\b",
            r"\b(poland|warsaw|krakow|kraków|gdansk)\b",
            r"\b(portugal|lisbon|porto)\b",
            r"\b(czech republic|czechia|prague|brno)\b",
            r"\b(greece|athens|thessaloniki)\b",
            r"\b(hungary|budapest)\b",
            r"\b(slovakia|bratislava)\b",
            r"\b(luxembourg)\b",
            r"\b(iceland|reykjavik)\b",
            r"\b(estonia|tallinn|tartu)\b",
            r"\b(latvia|riga)\b",
            r"\b(lithuania|vilnius|kaunas)\b",
            r"\b(slovenia|ljubljana)\b",
            r"\b(croatia|zagreb)\b",
            r"\b(cyprus|nicosia)\b",
            r"\b(malta|valletta)\b"
        ]
        for pat in european_patterns:
            if re.search(pat, combined):
                return True

        # Target Asian countries/regions
        target_asia = [
            r"\b(singapore|ntu|nus|smu)\b",
            r"\b(japan|tokyo|kyoto|osaka|nagoya|tohoku|hokkaido|kyushu|tsukuba)\b",
            r"\b(korea|south korea|republic of korea|seoul|daejeon|busan|incheon|kaist|postech|yonsei|korea university|snu)\b"
        ]
        for pat in target_asia:
            if re.search(pat, combined):
                return True

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
