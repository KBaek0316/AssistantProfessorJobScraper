import re
from typing import List
from urllib.parse import urljoin
from bs4 import BeautifulSoup
from .base import BaseScraper, JobPosting


class HigherEdJobsScraper(BaseScraper):
    """Scraper for HigherEdJobs faculty listings."""

    SEARCH_URL = "https://www.higheredjobs.com/search/advanced_action.cfm"

    def __init__(self):
        super().__init__("HigherEdJobs")

    def scrape(self, query: str = "Assistant Professor Transportation", max_results: int = 25) -> List[JobPosting]:
        self.logger.info(f"Querying HigherEdJobs with: '{query}'")
        postings: List[JobPosting] = []

        try:
            params = {
                "PosType": 1,  # Faculty
                "Keyword": query,
            }
            response = self.session.get(self.SEARCH_URL, params=params, timeout=15)
            if response.status_code != 200:
                self.logger.warning(f"Failed to fetch HigherEdJobs: HTTP {response.status_code}")
                return postings

            soup = BeautifulSoup(response.text, "html.parser")
            job_links = soup.find_all("a", href=re.compile(r"details\.cfm\?JobCode=\d+"))
            seen_codes = set()

            for a in job_links:
                if len(postings) >= max_results:
                    break

                href = a.get("href", "")
                code_match = re.search(r"JobCode=(\d+)", href)
                if not code_match:
                    continue
                job_code = code_match.group(1)
                if job_code in seen_codes:
                    continue
                seen_codes.add(job_code)

                title = a.get_text(strip=True)
                if not title or len(title) < 4:
                    continue

                full_url = urljoin("https://www.higheredjobs.com/search/", href)

                # Look for parent or sibling details (Institution, Location)
                container = a.find_parent("div", class_=re.compile(r"row|item|job", re.I)) or a.find_parent("li")
                institution = "HigherEdJobs Listed University"
                location = "United States"
                field_name = "Civil & Environmental / Transportation Engineering"
                raw_text = title

                if container:
                    raw_text = container.get_text(" ", strip=True)
                    # Extract location or institution if possible from text patterns
                    lines = [line.strip() for line in container.stripped_strings if line.strip()]
                    if len(lines) > 1 and lines[1] != title:
                        institution = lines[1]
                    if len(lines) > 2:
                        location = lines[2]

                job_id = JobPosting.generate_id("higheredjobs", job_code)
                postings.append(
                    JobPosting(
                        id=job_id,
                        title=title,
                        institution=institution,
                        field=field_name,
                        location=location,
                        deadline="Open until filled",
                        salary="Not specified",
                        link=full_url,
                        source="HigherEdJobs",
                        raw_description=raw_text,
                    )
                )

        except Exception as e:
            self.logger.error(f"Error scraping HigherEdJobs: {e}", exc_info=True)

        self.logger.info(f"Retrieved {len(postings)} listings from HigherEdJobs")
        return postings
