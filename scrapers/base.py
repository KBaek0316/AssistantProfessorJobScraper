import hashlib
import logging
import random
import time
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
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
    deadline_date: str = ""

    def __post_init__(self):
        if not self.deadline_date and self.deadline:
            self.deadline_date = self.extract_latest_deadline_date(self.deadline)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @staticmethod
    def generate_id(source: str, identifier: str) -> str:
        """Create a deterministic unique ID for a posting."""
        raw = f"{source.lower().strip()}:{identifier.strip()}".encode("utf-8")
        return hashlib.sha256(raw).hexdigest()[:16]

    @staticmethod
    def extract_latest_deadline_date(deadline_str: Optional[str], ref_date: Optional[date] = None) -> str:
        """
        Parses deadline string and returns the strictly formatted date 'YYYY-MM-DD'.
        If multiple deadlines are present (e.g. 'Priority: 2026-09-15 / Final: 2026-11-01'),
        the later deadline is selected per system specification.
        Returns empty string if no valid date is found (e.g. 'Open until filled', 'Not specified').
        """
        if not deadline_str:
            return ""

        if ref_date is None:
            ref_date = date.today()

        import re
        s = str(deadline_str).strip()
        month_names = (
            "january|february|march|april|may|june|july|august|september|october|november|december|"
            "jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec"
        )
        found_dates: List[date] = []

        # 1. ISO format: YYYY-MM-DD
        for m in re.finditer(r"\b(202\d)-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])\b", s):
            try:
                found_dates.append(date(int(m.group(1)), int(m.group(2)), int(m.group(3))))
            except ValueError:
                pass

        # 2. Month DD, YYYY (e.g. October 15, 2026 or Oct 15 2026)
        for m in re.finditer(rf"\b({month_names})[\.]?\s+(\d{{1,2}})(?:st|nd|rd|th)?,?\s+(\d{{4}})\b", s, re.IGNORECASE):
            m_str = m.group(1).replace(".", "")
            d_int = int(m.group(2))
            y_int = int(m.group(3))
            for fmt in ("%B %d %Y", "%b %d %Y"):
                try:
                    found_dates.append(datetime.strptime(f"{m_str} {d_int} {y_int}", fmt).date())
                    break
                except ValueError:
                    pass

        # 3. Day Month Year (e.g. 15 October 2026, 15th Oct 2026)
        for m in re.finditer(rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+({month_names})[\.]?,?\s+(\d{{4}})\b", s, re.IGNORECASE):
            d_int = int(m.group(1))
            m_str = m.group(2).replace(".", "")
            y_int = int(m.group(3))
            for fmt in ("%d %B %Y", "%d %b %Y"):
                try:
                    found_dates.append(datetime.strptime(f"{d_int} {m_str} {y_int}", fmt).date())
                    break
                except ValueError:
                    pass

        # 4. Month DD without year (e.g. September 30, Oct 15)
        if not found_dates:
            for m in re.finditer(rf"\b({month_names})[\.]?\s+(\d{{1,2}})(?:st|nd|rd|th)?\b", s, re.IGNORECASE):
                m_str = m.group(1).replace(".", "")
                d_int = int(m.group(2))
                for fmt in ("%B %d", "%b %d"):
                    try:
                        dt = datetime.strptime(f"{m_str} {d_int}", fmt)
                        y_int = ref_date.year
                        if dt.month < ref_date.month and (ref_date.month - dt.month) > 2:
                            y_int = ref_date.year + 1
                        found_dates.append(date(y_int, dt.month, dt.day))
                        break
                    except ValueError:
                        pass

        # 5. Day Month without year (e.g. 15 October, 05 Oct)
        if not found_dates:
            for m in re.finditer(rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+({month_names})[\.]?\b", s, re.IGNORECASE):
                d_int = int(m.group(1))
                m_str = m.group(2).replace(".", "")
                for fmt in ("%d %B", "%d %b"):
                    try:
                        dt = datetime.strptime(f"{d_int} {m_str}", fmt)
                        y_int = ref_date.year
                        if dt.month < ref_date.month and (ref_date.month - dt.month) > 2:
                            y_int = ref_date.year + 1
                        found_dates.append(date(y_int, dt.month, dt.day))
                        break
                    except ValueError:
                        pass

        if found_dates:
            # Pick the later deadline if multiple dates exist
            sorted_dates = sorted(set(found_dates))
            return sorted_dates[-1].strftime("%Y-%m-%d")

        return ""

    @staticmethod
    def get_deadline_sort_key(posting: "JobPosting", ref_date: Optional[date] = None) -> Tuple[Any, ...]:
        """
        Computes 4-tier sorting key for job postings:
          - Tier 1: Active future/imminent deadlines (target_date >= ref_date),
                    sorted by urgency (closest to ref_date first).
          - Tier 2: 'Open until filled' / rolling deadlines.
          - Tier 3: 'Not specified' / unspecified deadlines.
          - Tier 4: Deadlines that have already passed (target_date < ref_date),
                    sorted by recency (most recently passed first).
        Within each tier, higher fit_score comes first, then institution, then title.
        """
        if ref_date is None:
            ref_date = date.today()

        dl_date_str = posting.deadline_date or JobPosting.extract_latest_deadline_date(posting.deadline, ref_date=ref_date)
        dl_text = (posting.deadline or "").lower().strip()
        fit_score_val = -(posting.fit_score or 0)
        inst_val = (posting.institution or "").lower()
        title_val = (posting.title or "").lower()

        target_date: Optional[date] = None
        if dl_date_str:
            try:
                target_date = datetime.strptime(dl_date_str, "%Y-%m-%d").date()
            except ValueError:
                target_date = None

        if target_date is not None:
            if target_date >= ref_date:
                # Tier 1: Active future deadline (urgency: earliest date first)
                return (1, target_date, fit_score_val, inst_val, title_val)
            else:
                # Tier 4: Past deadline (most recent past date first: descending date)
                return (4, -target_date.toordinal(), fit_score_val, inst_val, title_val)

        # No parseable date
        if "open" in dl_text or "rolling" in dl_text:
            # Tier 2: Open until filled
            return (2, 0, fit_score_val, inst_val, title_val)
        else:
            # Tier 3: Not specified
            return (3, 0, fit_score_val, inst_val, title_val)

    @staticmethod
    def extract_deadline_from_text(text: str, ref_date: Optional[date] = None) -> Optional[str]:
        """
        Deterministically extracts application deadline, priority date, or review date
        from raw job text or description snippets.
        """
        if not text:
            return None

        if ref_date is None:
            ref_date = date.today()

        import re

        month_names = (
            "january|february|march|april|may|june|july|august|september|october|november|december|"
            "jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec"
        )

        def normalize_found_date(month_str: str, day_str: str, year_str: Optional[str]) -> Optional[date]:
            m_str = month_str.replace(".", "")
            d_int = int(day_str)
            if year_str:
                y_int = int(year_str)
                for fmt in ("%B %d %Y", "%b %d %Y"):
                    try:
                        return datetime.strptime(f"{m_str} {d_int} {y_int}", fmt).date()
                    except ValueError:
                        pass
            else:
                for fmt in ("%B %d", "%b %d"):
                    try:
                        dt = datetime.strptime(f"{m_str} {d_int}", fmt)
                        y_int = ref_date.year
                        if dt.month < ref_date.month and (ref_date.month - dt.month) > 2:
                            y_int = ref_date.year + 1
                        return date(y_int, dt.month, dt.day)
                    except ValueError:
                        pass
            return None

        # 1. Look for explicit submission/priority deadline
        priority_pats = [
            # Day Month Year (e.g. 15 October 2026, 15th Oct 2026, Closes 05 Oct)
            rf"(?:full consideration|submitted|received|apply)(?:[^\.\n]*?)\b(?:by|is|before)\s+(\d{{1,2}})(?:st|nd|rd|th)?\s+({month_names})[\.]?,?\s*(\d{{4}})?\b",
            rf"(?:priority\s*(?:deadline|date)|target\s*date)(?:[^\.\n]*?)\b(?:is|:)?\s*(\d{{1,2}})(?:st|nd|rd|th)?\s+({month_names})[\.]?,?\s*(\d{{4}})?\b",
            rf"(?:deadline|closing date|due date|closes)(?:[^\.\n]*?)\b(?:is|:)?\s*(\d{{1,2}})(?:st|nd|rd|th)?\s+({month_names})[\.]?,?\s*(\d{{4}})?\b",
            # Month Day Year (e.g. October 15, 2026, Oct 15)
            rf"(?:full consideration|submitted|received|apply)(?:[^\.\n]*?)\b(?:by|is|before)\s+({month_names})[\.]?\s+(\d{{1,2}})(?:st|nd|rd|th)?(?:,?\s*(\d{{4}})\b|\b)",
            rf"(?:priority\s*(?:deadline|date)|target\s*date)(?:[^\.\n]*?)\b(?:is|:)?\s*({month_names})[\.]?\s+(\d{{1,2}})(?:st|nd|rd|th)?(?:,?\s*(\d{{4}})\b|\b)",
            rf"(?:deadline|closing date|due date|closes)(?:[^\.\n]*?)\b(?:is|:)?\s*({month_names})[\.]?\s+(\d{{1,2}})(?:st|nd|rd|th)?(?:,?\s*(\d{{4}})\b|\b)",
        ]

        priority_date = None
        for p in priority_pats:
            m = re.search(p, text, re.IGNORECASE)
            if m:
                g1, g2, g3 = m.group(1), m.group(2), m.group(3) if len(m.groups()) >= 3 else None
                if g1.isdigit():
                    priority_date = normalize_found_date(g2, g1, g3)
                else:
                    priority_date = normalize_found_date(g1, g2, g3)
                if priority_date:
                    break

        # 2. Look for review begins date
        review_pats = [
            rf"(?:review|screening)\s*(?:will\s*)?begin(?:s)?(?:\s*on)?\s+(\d{{1,2}})(?:st|nd|rd|th)?\s+({month_names})[\.]?,?\s*(\d{{4}})?\b",
            rf"(?:review|screening)\s*(?:will\s*)?begin(?:s)?(?:\s*on)?\s+({month_names})[\.]?\s+(\d{{1,2}})(?:st|nd|rd|th)?(?:,?\s*(\d{{4}})\b|\b)",
        ]
        review_date = None
        for p in review_pats:
            m = re.search(p, text, re.IGNORECASE)
            if m:
                g1, g2, g3 = m.group(1), m.group(2), m.group(3) if len(m.groups()) >= 3 else None
                if g1.isdigit():
                    review_date = normalize_found_date(g2, g1, g3)
                else:
                    review_date = normalize_found_date(g1, g2, g3)
                if review_date:
                    break

        # 3. ISO Date fallback (e.g. 2026-09-30)
        if not priority_date:
            iso_m = re.search(r"\b(202\d)-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])\b", text)
            if iso_m:
                try:
                    priority_date = date(int(iso_m.group(1)), int(iso_m.group(2)), int(iso_m.group(3)))
                except ValueError:
                    pass

        if priority_date and review_date and priority_date != review_date:
            return f"Priority: {priority_date.strftime('%Y-%m-%d')} / Review: {review_date.strftime('%Y-%m-%d')}"
        elif priority_date:
            return priority_date.strftime("%Y-%m-%d")
        elif review_date:
            return f"Review begins {review_date.strftime('%Y-%m-%d')}"

        if re.search(r"\bopen until filled\b", text, re.IGNORECASE):
            return "Open until filled"

        return None

    @staticmethod
    def is_valid_faculty_posting(title: str, text_snippet: str = "") -> bool:
        """
        Filter out:
          - Non-faculty / trainees (drivers, postdocs, technicians, staff, fellows)
          - Contingent / part-time (adjunct, continuing education, adult ed)
          - Seniority-only positions (pure associate professor, full professor, department chair, dean)
        Must be an Assistant Professor, Open Rank (including Assistant), or tenure-track faculty role.
        """
        import re
        t_lower = title.lower().strip()
        combined = f"{title} {text_snippet}".lower()

        # 1. Non-faculty staff, trainees, contingent, or continuing ed
        excluded_patterns = [
            r"\bdriver\b", r"\bbus driver\b", r"\bpostdoc\b", r"\bpost-doc\b",
            r"\bpostdoctoral\b", r"\bresearch fellow\b", r"\bproject officer\b",
            r"\bintern\b", r"\btechnician\b", r"\bcustodian\b", r"\belementary\b",
            r"\bk-12\b", r"\blab manager\b", r"\bundergraduate\b", r"\bgraduate student\b",
            r"\badjunct\b", r"\bcontinuing education\b", r"\badult education\b",
            r"\bcommunity education\b", r"\bextension agent\b", r"\bvisiting scholar\b",
        ]
        for pat in excluded_patterns:
            if re.search(pat, combined):
                return False

        # 2. Seniority filter: Exclude positions strictly seeking Associate/Full Professor or Department Chair/Dean
        seniority_patterns = [
            r"\bdepartment chair\b", r"\bdept\.?\s*chair\b", r"\bdivision chair\b",
            r"\bschool chair\b", r"\bchair of the department\b", r"\bendowed chair\b",
            r"\bdistinguished chair\b", r"\bdean\b", r"\bassociate dean\b",
            r"\bfull professor\b", r"\bendowed professor\b", r"\bdistinguished professor\b",
            r"\bchaired professor\b",
        ]
        for spat in seniority_patterns:
            # If title specifically matches a senior pattern, reject UNLESS it explicitly includes "assistant"
            if re.search(spat, t_lower) and not re.search(r"\bassistant\b", t_lower):
                return False

        # If title specifies Associate Professor without Assistant Professor
        if re.search(r"\bassociate professor\b", t_lower) and not re.search(r"\bassistant\b", t_lower):
            return False

        # If title specifies Professor (e.g. "Professor of Civil Engineering", "Professor & Department Chair")
        # without "assistant", "open rank", "open-rank"
        if re.search(r"\bprofessor\b", t_lower):
            if not re.search(r"\b(assistant|open rank|open-rank)\b", t_lower):
                return False

        # 3. Must indicate an academic faculty appointment
        faculty_indicators = [r"\bassistant\b", r"\bprofessor\b", r"\bfaculty\b", r"\blecturer\b", r"\binstructor\b", r"\bopen rank\b", r"\bopen-rank\b"]
        if not any(re.search(ind, t_lower) for ind in faculty_indicators):
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


def sort_postings_by_deadline(postings: List[JobPosting], ref_date: Optional[date] = None) -> List[JobPosting]:
    """
    Sort a list of job postings according to the 4-tier deadline urgency rules:
      1. Active future deadlines sorted by urgency (closest deadline first).
      2. 'Open until filled' / rolling deadlines.
      3. 'Not specified' / unspecified.
      4. Entries whose deadline has already passed.
    """
    return sorted(postings, key=lambda p: JobPosting.get_deadline_sort_key(p, ref_date=ref_date))

