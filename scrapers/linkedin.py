import re
from typing import List
from urllib.parse import urljoin
from bs4 import BeautifulSoup
from .base import BaseScraper, JobPosting


class LinkedInScraper(BaseScraper):
    """Scraper for public LinkedIn job postings using the guest search API."""

    GUEST_URL = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"

    def __init__(self):
        super().__init__("LinkedIn")

    def _fetch_job_description(self, job_key: str) -> str:
        """Fetch detailed job description snippet from LinkedIn guest API."""
        try:
            url = f"https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{job_key}"
            resp = self.session.get(url, timeout=10)
            if resp.status_code == 200:
                soup = BeautifulSoup(resp.text, "html.parser")
                desc = soup.find("div", class_=re.compile("description__text|show-more-less-html__markup"))
                if desc:
                    return desc.get_text(" ", strip=True)[:4000]
        except Exception as e:
            self.logger.debug(f"Failed fetching description for {job_key}: {e}")
        return ""

    TARGET_LOCATIONS = [
        "United States",
        "Canada",
        "Europe",
        "South Korea",
        "Japan",
        "Singapore",
        "Hong Kong",
    ]

    def scrape(self, query: str = "Assistant Professor Transportation", max_results: int = 20) -> List[JobPosting]:
        self.logger.info(f"Querying LinkedIn Guest API for: '{query}' across target locations: {', '.join(self.TARGET_LOCATIONS)}")
        postings: List[JobPosting] = []
        seen_ids = set()

        # Distribute max_results across locations
        per_location_max = max(4, max_results // len(self.TARGET_LOCATIONS) + 2)

        for loc in self.TARGET_LOCATIONS:
            if len(postings) >= max_results:
                break

            self.logger.info(f"  -> LinkedIn querying location: '{loc}'...")
            start = 0
            batch_size = 10
            loc_count = 0

            while loc_count < per_location_max and len(postings) < max_results and start < 30:
                try:
                    params = {
                        "keywords": query,
                        "location": loc,
                        "start": start,
                    }
                    resp = self.session.get(self.GUEST_URL, params=params, timeout=15)
                    if resp.status_code != 200:
                        self.logger.warning(f"LinkedIn Guest API returned status {resp.status_code} for {loc} at start={start}")
                        break

                    soup = BeautifulSoup(resp.text, "html.parser")
                    cards = soup.find_all("li")
                    if not cards:
                        break

                    card_count_this_page = 0
                    for card in cards:
                        if len(postings) >= max_results or loc_count >= per_location_max:
                            break

                        # Title and link
                        title_elem = (
                            card.find("h3", class_=re.compile(r"base-search-card__title|job-search-card__title", re.I))
                            or card.find("a", class_=re.compile(r"base-card__full-link", re.I))
                        )
                        link_elem = card.find("a", href=re.compile(r"/jobs/view/|linkedin\.com/jobs/"))

                        if not title_elem or not link_elem:
                            continue

                        title = title_elem.get_text(strip=True)
                        raw_link = link_elem.get("href", "").split("?")[0]
                        if not raw_link or not title:
                            continue

                        card_text = card.get_text(" ", strip=True)
                        if not JobPosting.is_valid_faculty_posting(title, card_text):
                            continue

                        # Extract job ID from link or card
                        id_match = re.search(r"/jobs/view/(?:[a-zA-Z0-9\-]+-)?(\d+)", raw_link) or re.search(r"(\d{8,})", raw_link)
                        job_key = id_match.group(1) if id_match else raw_link
                        if job_key in seen_ids:
                            continue
                        seen_ids.add(job_key)

                        # Subtitle / Institution
                        sub_elem = card.find("h4", class_=re.compile(r"base-search-card__subtitle|job-search-card__subtitle", re.I))
                        institution = sub_elem.get_text(strip=True) if sub_elem else "University / Institution"

                        # Location
                        loc_elem = card.find("span", class_=re.compile(r"job-search-card__location", re.I))
                        location = loc_elem.get_text(strip=True) if loc_elem else loc

                        # Geographic scope check
                        if not JobPosting.is_allowed_location(location):
                            continue

                        # Time / Date
                        time_elem = card.find("time")
                        posted_date = time_elem.get_text(strip=True) if time_elem else "Recently"

                        job_id = JobPosting.generate_id("linkedin", job_key)
                        detailed_desc = self._fetch_job_description(job_key) if job_key.isdigit() else ""
                        raw_description = detailed_desc if detailed_desc else card_text

                        # Check for explicit deadline mentioned in description
                        deadline = f"Posted {posted_date}"
                        text_dl = JobPosting.extract_deadline_from_text(raw_description)
                        if text_dl:
                            deadline = text_dl

                        postings.append(
                            JobPosting(
                                id=job_id,
                                title=title,
                                institution=institution,
                                field="Transportation Engineering",
                                location=location,
                                deadline=deadline,
                                salary="Not specified",
                                link=raw_link,
                                source="LinkedIn",
                                raw_description=raw_description,
                            )
                        )
                        card_count_this_page += 1
                        loc_count += 1

                    if card_count_this_page == 0:
                        break

                    start += batch_size
                    self.polite_sleep(1.2, 2.5)

                except Exception as e:
                    self.logger.error(f"Error scraping LinkedIn for {loc}: {e}", exc_info=True)
                    break

        self.logger.info(f"Retrieved {len(postings)} listings from LinkedIn across target locations")
        return postings
