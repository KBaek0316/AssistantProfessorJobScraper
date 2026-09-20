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

    def _fetch_detail(self, url: str):
        """Fetch AcademicKeys job display page for full description, department, deadline, and salary."""
        try:
            resp = self.session.get(url, timeout=12)
            if resp.status_code == 200:
                soup = BeautifulSoup(resp.text, "html.parser")
                full_text = soup.get_text(" ", strip=True)

                department = ""
                # AcademicKeys detail pages feature 'Department [Department Name]'
                for row in soup.find_all("tr"):
                    row_text = row.get_text(" ", strip=True)
                    if "department" in row_text.lower():
                        m = re.search(
                            r"department\s*[:\-]?\s*([A-Za-z0-9&/,\.\-\s]+?)(?=\s*(?:application\s+deadline|deadline|position\s+start|date\s+posted|salary|job\s+categories|$))",
                            row_text,
                            re.IGNORECASE,
                        )
                        if m:
                            dept_cand = m.group(1).strip()
                            if dept_cand.lower().startswith("department of "):
                                department = "Department of " + dept_cand[14:].strip()
                            elif dept_cand.lower().startswith("department "):
                                department = "Department of " + dept_cand[11:].strip()
                            elif dept_cand:
                                department = dept_cand
                            break

                deadline = ""
                dl_m = re.search(
                    r"(?:application\s+deadline|deadline)\s*[:\-]?\s*([A-Za-z0-9&/,\.\-\s]+?)(?=\s*(?:position\s+start|date\s+posted|salary|job\s+categories|$))",
                    full_text,
                    re.IGNORECASE,
                )
                if dl_m:
                    deadline = dl_m.group(1).strip()

                return full_text, department, deadline
        except Exception as e:
            self.logger.debug(f"Failed fetching AcademicKeys detail page {url}: {e}")
        return "", "", ""

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

                # Filter out non-faculty postings (postdocs, technicians, staff, drivers, adjunct, seniority)
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

                # Fetch full detail page for rich description and department
                detail_desc, detail_dept, detail_dl = self._fetch_detail(clean_url)
                if detail_dept:
                    field_name = detail_dept
                if detail_dl:
                    deadline = detail_dl

                raw_desc = detail_desc if detail_desc and len(detail_desc) > len(parent_text) else (parent_text or title)

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
                        raw_description=raw_desc,
                    )
                )

        except Exception as e:
            self.logger.error(f"Error scraping AcademicKeys: {e}", exc_info=True)

        self.logger.info(f"Retrieved {len(postings)} listings from AcademicKeys")
        return postings

