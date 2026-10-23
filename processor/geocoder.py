import json
import logging
import os
import time
from typing import Dict, List, Optional, Tuple
from scrapers.base import JobPosting


class UniversityGeocoder:
    """Geocodes university names / locations to (lat, lon) with persistent disk caching."""

    CACHE_FILE = os.path.join(".cache", "geocache.json")

    # Built-in coordinates for common US universities to minimize network lookups
    FALLBACK_COORDINATES: Dict[str, Tuple[float, float]] = {
        "massachusetts institute of technology": (42.3601, -71.0942),
        "mit": (42.3601, -71.0942),
        "stanford university": (37.4275, -122.1697),
        "university of california, berkeley": (37.8719, -122.2585),
        "uc berkeley": (37.8719, -122.2585),
        "georgia institute of technology": (33.7756, -84.3963),
        "georgia tech": (33.7756, -84.3963),
        "purdue university": (40.4237, -86.9212),
        "university of michigan": (42.2780, -83.7382),
        "university of texas at austin": (30.2849, -97.7341),
        "ut austin": (30.2849, -97.7341),
        "texas a&m university": (30.6187, -96.3365),
        "university of illinois urbana-champaign": (40.1020, -88.2272),
        "uiuc": (40.1020, -88.2272),
        "cornell university": (42.4534, -76.4735),
        "carnegie mellon university": (40.4432, -79.9428),
        "cmu": (40.4432, -79.9428),
        "virginia tech": (37.2284, -80.4234),
        "northwestern university": (42.0565, -87.6753),
        "university of washington": (47.6553, -122.3035),
        "university of florida": (29.6436, -82.3549),
        "ohio state university": (40.0067, -83.0305),
        "penn state university": (40.7982, -77.8599),
        "arizona state university": (33.4242, -111.9281),
        "university of south carolina": (33.9929, -81.0269),
        "uofsc": (33.9929, -81.0269),
        "usc columbia": (33.9929, -81.0269),
        "brown university": (41.8268, -71.4025),
        "university of notre dame": (41.7046, -86.2382),
        "notre dame": (41.7046, -86.2382),
        "columbia university": (40.8078, -73.9625),
        # Canadian universities
        "university of toronto": (43.6629, -79.3957),
        "uoft": (43.6629, -79.3957),
        "university of british columbia": (49.2606, -123.2460),
        "ubc": (49.2606, -123.2460),
        "mcgill university": (45.5048, -73.5772),
        "mcgill": (45.5048, -73.5772),
        "university of waterloo": (43.4723, -80.5449),
        "waterloo": (43.4723, -80.5449),
        "mcmaster university": (43.2609, -79.9192),
        "university of alberta": (53.5232, -113.5263),
        "university of calgary": (51.0778, -114.1332),
        "polytechnique montréal": (45.5048, -73.6133),
        "university of manitoba": (49.8094, -97.1327),
        "university of ottawa": (45.4231, -75.6831),
        "université de montréal": (45.5017, -73.6187),
        "queen's university": (44.2253, -76.4951),
        "western university": (43.0096, -81.2737),
        "dalhousie university": (44.6366, -63.5917),
        "city colleges of chicago": (41.8837, -87.6324),
        "embry-riddle aeronautical university": (29.1895, -81.0494),
        # European universities
        "university of leeds": (53.8067, -1.5550),
        "university college dublin": (53.3082, -6.2238),
        "ucd": (53.3082, -6.2238),
        "imperial college london": (51.4988, -0.1749),
        "university college london": (51.5246, -0.1340),
        "ucl": (51.5246, -0.1340),
        "university of oxford": (51.7548, -1.2544),
        "university of cambridge": (52.2053, 0.1166),
        "university of birmingham": (52.4508, -1.9305),
        "eth zurich": (47.3763, 8.5477),
        "epfl": (46.5191, 6.5668),
        "tu delft": (52.0023, 4.3736),
        "delft university of technology": (52.0023, 4.3736),
        "kth royal institute of technology": (59.3498, 18.0707),
        "technical university of denmark": (55.7856, 12.5218),
        "dtu": (55.7856, 12.5218),
        "aalto university": (60.1869, 24.8270),
        "politecnico di milano": (45.4781, 9.2274),
        # Target Asian universities
        "the hong kong polytechnic university": (22.3045, 114.1797),
        "polyu": (22.3045, 114.1797),
        "university of macau": (22.1285, 113.5438),
        "nanyang technological university": (1.3483, 103.6831),
        "national university of singapore": (1.2966, 103.7764),
        "seoul national university": (37.4599, 126.9519),
        "kaist": (36.3722, 127.3604),
        "yonsei university": (37.5658, 126.9386),
        "korea university": (37.5908, 127.0278),
        "university of tokyo": (35.7128, 139.7620),
        "kyoto university": (35.0262, 135.7808),
        "national taiwan university": (25.0174, 121.5405),
        # Specific branch campuses / satellite locations
        "texas a&m university-corpus christi": (27.7128, -97.3234),
        "texas a&m university corpus christi": (27.7128, -97.3234),
        "texas a&m university at galveston": (29.3160, -94.8180),
        "cornell tech": (40.7548, -73.9564),
        "cornell tech, new york, ny": (40.7548, -73.9564),
        "cornell university, new york, ny": (40.7548, -73.9564),
        "purdue university in indianapolis": (39.7749, -86.1681),
        "purdue university, indianapolis, indiana": (39.7749, -86.1681),
        "purdue university, indianapolis, in": (39.7749, -86.1681),
        "northeastern university, seattle, washington": (47.6206, -122.3374),
        "northeastern university, seattle, wa": (47.6206, -122.3374),
        "cal poly, san luis obispo, vallejo, california": (38.0715, -122.2313),
        "cal maritime": (38.0715, -122.2313),
        "california maritime academy": (38.0715, -122.2313),
        "embry-riddle aeronautical university, prescott, az": (34.6484, -112.4204),
        "embry-riddle prescott": (34.6484, -112.4204),
        "penn state altoona": (40.5412, -78.4093),
        "penn state university, altoona, pa": (40.5412, -78.4093),
        "universidade de aveiro, viseu, portugal": (40.6575, -7.9139),
        "the american college of greece": (38.0033, 23.8317),
        "the american college of greece, athens": (38.0033, 23.8317),
    }

    # Campus conflict guards: if a query specifies any of these branch campus / city keywords,
    # the generic flagship fallback coordinates must NOT be used.
    BRANCH_CAMPUS_GUARDS: Dict[str, Tuple[str, ...]] = {
        "texas a&m university": ("corpus christi", "galveston", "san antonio", "kingsville", "commerce", "laredo", "central texas", "texarkana"),
        "cornell university": ("new york", "nyc", "roosevelt island", "cornell tech", "weill"),
        "purdue university": ("indianapolis", "fort wayne", "northwest"),
        "northeastern university": ("seattle", "silicon valley", "san francisco", "oakland", "vancouver", "toronto", "london", "charlotte", "portland", "arlington"),
        "embry-riddle aeronautical university": ("prescott",),
        "penn state university": ("altoona", "harrisburg", "erie", "behrend", "berks", "abington", "brandywine", "great valley"),
        "cal poly, san luis obispo": ("vallejo", "maritime"),
        "cal poly san luis obispo": ("vallejo", "maritime"),
        "university of california, berkeley": ("davis", "los angeles", "ucla", "san diego", "ucsd", "irvine", "uci", "santa barbara", "ucsb", "merced", "riverside", "santa cruz", "san francisco", "ucsf"),
        "university of illinois urbana-champaign": ("chicago", "uic", "springfield"),
        "university of michigan": ("flint", "dearborn"),
        "university of washington": ("bothell", "tacoma"),
        "university of colorado system": ("colorado springs", "uccs", "denver"),
        "universidade de aveiro": ("viseu",),
    }

    def __init__(self):
        self.logger = logging.getLogger("processor.geocoder")
        self.cache: Dict[str, List[float]] = self._load_cache()
        self._geolocator = None

    def _load_cache(self) -> Dict[str, List[float]]:
        if os.path.exists(self.CACHE_FILE):
            try:
                with open(self.CACHE_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                self.logger.warning(f"Failed reading geocache: {e}")
        return {}

    def _save_cache(self):
        try:
            os.makedirs(os.path.dirname(self.CACHE_FILE), exist_ok=True)
            with open(self.CACHE_FILE, "w", encoding="utf-8") as f:
                json.dump(self.cache, f, indent=2)
        except Exception as e:
            self.logger.warning(f"Failed writing geocache: {e}")

    def _get_geolocator(self):
        if self._geolocator is None:
            try:
                from geopy.geocoders import Nominatim
                self._geolocator = Nominatim(user_agent="AssistantProfessorJobScraper/1.0")
            except ImportError:
                self.logger.warning("geopy not installed. Using fallback coordinates only.")
        return self._geolocator

    def geocode(self, query: str) -> Optional[Tuple[float, float]]:
        """Look up coordinates for a given institution or location string."""
        if not query or query.lower() in ("united states", "unspecified", ""):
            return None

        clean_query = query.strip().lower()
        if clean_query in self.cache:
            coords = self.cache[clean_query]
            return (coords[0], coords[1])

        # 1. Exact match in fallback coordinates
        if clean_query in self.FALLBACK_COORDINATES:
            coords = self.FALLBACK_COORDINATES[clean_query]
            self.cache[clean_query] = [coords[0], coords[1]]
            self._save_cache()
            return coords

        # 2. Check built-in fallback lookup (sorted by length descending for specificity)
        for known_name, coords in sorted(self.FALLBACK_COORDINATES.items(), key=lambda x: len(x[0]), reverse=True):
            if known_name in clean_query or clean_query in known_name:
                # Check branch campus guard: if clean_query contains keywords for a branch campus / city,
                # do not return the generic flagship coordinates.
                if known_name in self.BRANCH_CAMPUS_GUARDS:
                    guard_keywords = self.BRANCH_CAMPUS_GUARDS[known_name]
                    if any(kw in clean_query for kw in guard_keywords):
                        continue
                self.cache[clean_query] = [coords[0], coords[1]]
                self._save_cache()
                return coords

        # 3. Query Nominatim
        geolocator = self._get_geolocator()
        if geolocator:
            try:
                time.sleep(1.0)  # Nominatim 1 req/sec rate limit
                location = geolocator.geocode(query, timeout=10)
                if location:
                    coords = (location.latitude, location.longitude)
                    self.cache[clean_query] = [coords[0], coords[1]]
                    self._save_cache()
                    return coords
            except Exception as e:
                self.logger.warning(f"Geocoding failed for '{query}': {e}")

        return None

    GENERIC_INSTITUTIONS = {
        "university / institution",
        "chronicle listed university",
        "higheredjobs listed university",
        "institution",
        "university",
    }

    def enrich_coordinates(self, postings: List[JobPosting]):
        """Populate latitude and longitude on postings where missing without overriding valid branch/satellite campuses."""
        for p in postings:
            # If coordinates already exist and are valid, do not overwrite
            if p.latitude is not None and p.longitude is not None:
                continue

            clean_inst = (p.institution or "").strip().lower()
            coords = None
            is_valid_inst = bool(
                clean_inst
                and clean_inst not in self.GENERIC_INSTITUTIONS
                and not clean_inst.startswith("state of ")
                and not clean_inst.startswith("commonwealth of ")
            )
            has_specific_loc = bool(
                p.location
                and p.location.strip().lower() not in ("united states", "unspecified", "see full listing", "")
            )

            # 1. Try institution + specific location (prevents branch campus / remote facility mismatches)
            if is_valid_inst and has_specific_loc:
                coords = self.geocode(f"{p.institution}, {p.location}")

            # 2. Try location alone (ensures correct physical campus city over distant flagship headquarters)
            if not coords and has_specific_loc:
                coords = self.geocode(p.location)

            # 3. Try institution alone or with USA
            if not coords and is_valid_inst:
                coords = self.geocode(f"{p.institution}, USA")
                if not coords:
                    coords = self.geocode(p.institution)

            # 3. Fallback to location alone
            if not coords and has_specific_loc:
                coords = self.geocode(p.location)

            if coords:
                p.latitude, p.longitude = coords
