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

                title = a.get_text(" ", strip=True)
                if not title:
                    continue

                # Locate the parent row to extract real institution & details
                tr = a.find_parent("tr")
                parent_text = tr.get_text(" ", strip=True) if tr else a.parent.get_text(" ", strip=True)

                # Filter out non-faculty postings (postdocs, technicians, staff, drivers)
                if not JobPosting.is_valid_faculty_posting(title, parent_text):
                    continue

                # AcademicKeys structure: inside <td>, 1st <strong> is title, 2nd <strong> is Institution
                institution = "Academic Institution"
                location = "United States"
                deadline = "Open until filled"
                field_name = "Transportation / Civil Engineering"

                if tr:
                    strongs = tr.find_all("strong")
                    if len(strongs) > 1:
                        parsed_inst = strongs[1].get_text(strip=True)
                        if parsed_inst and parsed_inst != title:
                            institution = parsed_inst

                    text_lines = list(tr.stripped_strings)
                    for i, line in enumerate(text_lines):
                        if line == institution and i + 2 < len(text_lines):
                            location = text_lines[i + 2]
                        if "Deadline" in line and i + 1 < len(text_lines):
                            deadline = text_lines[i + 1]

                job_id = JobPosting.generate_id("academickeys", clean_url)
                postings.append(
                    JobPosting(
                        id=job_id,
                        title=title,
                        institution=institution,
                        field=field_name,
                        location=location,
                        deadline=deadline,
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
