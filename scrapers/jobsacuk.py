import re
from typing import List, Optional
from urllib.parse import urljoin
from bs4 import BeautifulSoup
from .base import BaseScraper, JobPosting


class JobsAcUkScraper(BaseScraper):
    """Scraper for jobs.ac.uk faculty and academic listings in the UK and Europe."""

    SEARCH_URL = "https://www.jobs.ac.uk/search/"

    def __init__(self):
        super().__init__("JobsAcUk")

    def _fetch_job_description(self, full_url: str) -> str:
        """Fetch detailed job description from jobs.ac.uk detail page."""
        try:
            resp = self.session.get(full_url, timeout=12)
            if resp.status_code == 200:
                soup = BeautifulSoup(resp.text, "html.parser")
                content_div = (
                    soup.find("div", class_="enhanced-content")
                    or soup.find("div", class_=re.compile(r"job-description|j-job-details|content"))
                    or soup.find("main")
                )
                if content_div:
                    return content_div.get_text(" ", strip=True)[:5000]
        except Exception as e:
            self.logger.debug(f"Failed fetching jobs.ac.uk description for {full_url}: {e}")
        return ""

    def scrape(self, query: str = "Assistant Professor Transportation", max_results: int = 25) -> List[JobPosting]:
        self.logger.info(f"Querying jobs.ac.uk with: '{query}'")
        postings: List[JobPosting] = []
        seen_links = set()

        try:
            params = {
                "keywords": query,
                "sortType": 1,
            }
            response = self.session.get(self.SEARCH_URL, params=params, timeout=15)
            if response.status_code != 200:
                self.logger.warning(f"Failed to fetch jobs.ac.uk: HTTP {response.status_code}")
                return postings

            soup = BeautifulSoup(response.text, "html.parser")
            results = soup.find_all("div", class_=lambda c: c and "j-search-result__text" in c)

            for res in results:
                if len(postings) >= max_results:
                    break

                title_a = res.find("a", href=lambda h: h and "/job/" in h)
                if not title_a:
                    continue

                title = title_a.get_text(strip=True)
                href = title_a.get("href", "")
                full_url = urljoin("https://www.jobs.ac.uk", href).split("?")[0]

                if not title or full_url in seen_links:
                    continue
                seen_links.add(full_url)

                parent = res.parent
                card_text = parent.get_text(" ", strip=True) if parent else res.get_text(" ", strip=True)

                if not JobPosting.is_valid_faculty_posting(title, card_text):
                    continue

                # Extract metadata from card
                dept_elem = res.find(class_=lambda c: c and "department" in c)
                dept = dept_elem.get_text(strip=True) if dept_elem else "Transportation / Civil Engineering"

                emp_elem = res.find(class_=lambda c: c and "employer" in c)
                institution = emp_elem.get_text(strip=True) if emp_elem else "UK/European University"

                loc_elem = res.find(lambda tag: tag.name == "div" and "location:" in tag.get_text().lower())
                raw_loc = re.sub(r"^location\s*:\s*", "", loc_elem.get_text(" ", strip=True), flags=re.IGNORECASE).strip() if loc_elem else "United Kingdom"
                if raw_loc.lower() in ("leeds", "oxford", "cambridge", "london", "birmingham", "manchester", "edinburgh", "glasgow", "bristol", "sheffield", "nottingham", "southampton", "newcastle", "liverpool", "cardiff", "belfast", "warwick"):
                    location = f"{raw_loc}, United Kingdom"
                elif raw_loc.lower() in ("dublin", "cork", "galway", "limerick"):
                    location = f"{raw_loc}, Ireland"
                elif raw_loc.lower() in ("hong kong", "macao", "macau"):
                    location = raw_loc
                else:
                    location = raw_loc or "United Kingdom"

                salary_elem = res.find(class_=lambda c: c and "salary" in c)
                raw_salary = salary_elem.get_text(" ", strip=True) if salary_elem else "Not specified"
                salary = re.sub(r"^salary\s*:\s*", "", raw_salary, flags=re.IGNORECASE).strip() or "Not specified"

                # Extract closing date from card (e.g. "Closes 05 Oct")
                deadline = "Open until filled"
                date_elem = parent.find(class_=lambda c: c and "date" in c) if parent else None
                if date_elem:
                    date_text = date_elem.get_text(" ", strip=True)
                    text_dl = JobPosting.extract_deadline_from_text(date_text)
                    if text_dl:
                        deadline = text_dl

                # Fetch full description if possible
                detailed_desc = self._fetch_job_description(full_url)
                raw_description = detailed_desc if detailed_desc else card_text

                # Check if full description has a more precise deadline
                desc_dl = JobPosting.extract_deadline_from_text(raw_description)
                if desc_dl and deadline == "Open until filled":
                    deadline = desc_dl

                # Geographic scope filter
                if not JobPosting.is_allowed_location(location):
                    continue

                job_id_match = re.search(r"/job/([a-zA-Z0-9]+)/", full_url)
                job_key = job_id_match.group(1) if job_id_match else full_url
                job_id = JobPosting.generate_id("jobsacuk", job_key)

                postings.append(
                    JobPosting(
                        id=job_id,
                        title=title,
                        institution=institution,
                        field=dept,
                        location=location,
                        deadline=deadline,
                        salary=salary,
                        link=full_url,
                        source="Jobs.ac.uk",
                        raw_description=raw_description,
                    )
                )

                self.polite_sleep(0.5, 1.2)

        except Exception as e:
            self.logger.error(f"Error scraping jobs.ac.uk: {e}", exc_info=True)

        self.logger.info(f"Retrieved {len(postings)} listings from jobs.ac.uk")
        return postings
