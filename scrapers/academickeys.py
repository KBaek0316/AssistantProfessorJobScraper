import re
from typing import List
from urllib.parse import urljoin
from bs4 import BeautifulSoup
from .base import BaseScraper, JobPosting


class AcademicKeysScraper(BaseScraper):
    """Scraper for AcademicKeys Engineering job board."""

    SEARCH_URL = "https://engineering.academickeys.com/seeker_search.php"

    def __init__(self):
        super().__init__("AcademicKeys")

    def scrape(self, query: str = "Assistant Professor Transportation", max_results: int = 25) -> List[JobPosting]:
        self.logger.info(f"Querying AcademicKeys with: '{query}'")
        postings: List[JobPosting] = []

        try:
            params = {"q": query}
            response = self.session.get(self.SEARCH_URL, params=params, timeout=15)
            if response.status_code != 200:
                self.logger.warning(f"Failed to fetch AcademicKeys: HTTP {response.status_code}")
                return postings

            soup = BeautifulSoup(response.text, "html.parser")
            
            # Find all links to job display pages
            job_links = soup.find_all("a", href=re.compile(r"/job/[a-zA-Z0-9]+/[^\"']+"))
            seen_urls = set()

            for a in job_links:
                if len(postings) >= max_results:
                    break

                href = a.get("href", "")
                full_url = urljoin("https://engineering.academickeys.com", href)
                # Strip query parameter for clean unique URL
                clean_url = full_url.split("?")[0]
                if clean_url in seen_urls:
                    continue
                seen_urls.add(clean_url)

                title = a.get_text(strip=True)
                if not title:
                    continue

                # Locate the parent container or row to extract institution & details
                parent = a.find_parent("tr") or a.find_parent("div")
                parent_text = parent.get_text(" ", strip=True) if parent else ""

                # Extract basic info
                institution = "AcademicKeys Listed Institution"
                location = "United States"
                field_name = "Transportation Engineering"

                # Try parsing institution from parent row if present
                if parent:
                    # AcademicKeys rows often format as Title - Institution - Location
                    parts = [p.strip() for p in parent_text.split("-") if p.strip()]
                    if len(parts) >= 2:
                        institution = parts[1]
                    if len(parts) >= 3:
                        location = parts[2]

                job_id = JobPosting.generate_id("academickeys", clean_url)
                postings.append(
                    JobPosting(
                        id=job_id,
                        title=title,
                        institution=institution,
                        field=field_name,
                        location=location,
                        deadline="Review begins immediately / Open",
                        salary="Not specified",
                        link=clean_url,
                        source="AcademicKeys",
                        raw_description=parent_text or title,
                    )
                )

        except Exception as e:
            self.logger.error(f"Error scraping AcademicKeys: {e}", exc_info=True)

        self.logger.info(f"Retrieved {len(postings)} listings from AcademicKeys")
        return postings
