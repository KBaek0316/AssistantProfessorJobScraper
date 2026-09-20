import json
import re
import xml.etree.ElementTree as ET
from typing import List, Optional, Tuple
from urllib.parse import urljoin
from bs4 import BeautifulSoup
from .base import BaseScraper, JobPosting


class ChronicleScraper(BaseScraper):
    """Scraper for The Chronicle of Higher Education Jobs."""

    SEARCH_URL = "https://jobs.chronicle.com/searchjobs/"
    RSS_URL = "https://jobs.chronicle.com/jobs/rss/"

    def __init__(self):
        super().__init__("Chronicle")

    def _fetch_detail_page(self, url: str, fallback_text: str = "") -> Tuple[str, str, str, Optional[str], Optional[str]]:
        """Fetches detail page to obtain complete description, salary, and deadline."""
        raw_text = fallback_text
        deadline = "Open until filled"
        salary = "Not specified"
        institution = None
        location = None

        try:
            resp = self.session.get(url, timeout=12)
            if resp.status_code == 200:
                soup = BeautifulSoup(resp.text, "html.parser")

                # Check for structured JSON-LD data
                for s in soup.find_all("script", type="application/ld+json"):
                    if s.string:
                        try:
                            data = json.loads(s.string)
                            if isinstance(data, dict):
                                if data.get("validThrough"):
                                    vt = str(data["validThrough"]).split("T")[0]
                                    if re.match(r"^\d{4}-\d{2}-\d{2}$", vt):
                                        deadline = vt
                                if data.get("baseSalary"):
                                    salary = str(data["baseSalary"])
                                if data.get("hiringOrganization") and isinstance(data["hiringOrganization"], dict):
                                    institution = data["hiringOrganization"].get("name")
                                if data.get("jobLocation"):
                                    loc_obj = data["jobLocation"]
                                    if isinstance(loc_obj, list) and loc_obj:
                                        loc_obj = loc_obj[0]
                                    if isinstance(loc_obj, dict) and loc_obj.get("address"):
                                        addr = loc_obj["address"]
                                        if isinstance(addr, dict):
                                            parts = [addr.get("addressLocality"), addr.get("addressRegion"), addr.get("addressCountry")]
                                            location = ", ".join(p for p in parts if p)
                        except Exception:
                            pass

                # Extract full description
                desc_div = soup.find("div", class_=lambda c: c and "job-description" in c) or soup.find("div", class_="mds-surface")
                if desc_div:
                    full_desc = desc_div.get_text(" ", strip=True)
                    if len(full_desc) > len(raw_text):
                        raw_text = full_desc

                # Deterministic deadline extraction from description text
                text_deadline = JobPosting.extract_deadline_from_text(raw_text)
                if text_deadline:
                    deadline = text_deadline

        except Exception as e:
            self.logger.debug(f"Could not fetch detail page for {url}: {e}")

        return raw_text, deadline, salary, institution, location

    def scrape(self, query: str = "Assistant Professor Transportation", max_results: int = 25) -> List[JobPosting]:
        self.logger.info(f"Querying Chronicle of Higher Ed with: '{query}'")
        postings: List[JobPosting] = []

        # Attempt 1: RSS Feed (fast, clean, and reliable)
        try:
            params = {"Keywords": query}
            rss_resp = self.session.get(self.RSS_URL, params=params, timeout=15)
            if rss_resp.status_code == 200 and "<rss" in rss_resp.text:
                root = ET.fromstring(rss_resp.content)
                items = root.findall(".//item")
                for item in items[:max_results]:
                    title_elem = item.find("title")
                    link_elem = item.find("link")
                    desc_elem = item.find("description")

                    title = title_elem.text.strip() if title_elem is not None and title_elem.text else ""
                    link = link_elem.text.strip() if link_elem is not None and link_elem.text else ""
                    desc = desc_elem.text.strip() if desc_elem is not None and desc_elem.text else ""

                    if not title or not link:
                        continue

                    if not JobPosting.is_valid_faculty_posting(title, desc):
                        continue

                    # Extract job id from link (e.g. /job/123456/...)
                    id_match = re.search(r"/job/(\d+)", link)
                    job_id_key = id_match.group(1) if id_match else link
                    job_id = JobPosting.generate_id("chronicle", job_id_key)

                    # Fetch full detail page for complete description and deadline
                    raw_text, deadline, salary, inst_detail, loc_detail = self._fetch_detail_page(link, fallback_text=desc or title)

                    institution = inst_detail or "Chronicle Listed University"
                    location = loc_detail or "United States"

                    postings.append(
                        JobPosting(
                            id=job_id,
                            title=title,
                            institution=institution,
                            field="Transportation / Civil Engineering",
                            location=location,
                            deadline=deadline,
                            salary=salary,
                            link=link,
                            source="Chronicle",
                            raw_description=raw_text,
                        )
                    )

                if postings:
                    self.logger.info(f"Retrieved {len(postings)} listings from Chronicle via RSS feed")
                    return postings
        except Exception as e:
            self.logger.warning(f"Chronicle RSS fetch encountered: {e}, falling back to HTML")

        # Attempt 2: HTML Search scraping
        try:
            params = {"Keywords": query}
            resp = self.session.get(self.SEARCH_URL, params=params, timeout=15)
            if resp.status_code == 200:
                soup = BeautifulSoup(resp.text, "html.parser")
                job_links = soup.find_all("a", href=re.compile(r"/job/\d+"))
                seen_urls = set()

                for a in job_links:
                    if len(postings) >= max_results:
                        break

                    href = a.get("href", "")
                    full_url = urljoin("https://jobs.chronicle.com", href)
                    if full_url in seen_urls:
                        continue
                    seen_urls.add(full_url)

                    title = a.get_text(strip=True)
                    if not title or len(title) < 4:
                        continue

                    parent = a.find_parent("li") or a.find_parent("div")
                    raw_text = parent.get_text(" ", strip=True) if parent else title

                    if not JobPosting.is_valid_faculty_posting(title, raw_text):
                        continue

                    # Extract actual institution and location from card metadata if present
                    rec_elem = parent.find(class_=lambda c: c and ("recruiter" in c or "employer" in c)) if parent else None
                    institution = rec_elem.get_text(strip=True) if rec_elem else "Chronicle Listed University"

                    loc_elem = parent.find(class_=lambda c: c and "location" in c) if parent else None
                    location = loc_elem.get_text(strip=True) if loc_elem else "United States"

                    # Fetch full job posting page to obtain complete description, salary, and deadlines
                    raw_text, deadline, salary, inst_detail, loc_detail = self._fetch_detail_page(full_url, fallback_text=raw_text)
                    if inst_detail:
                        institution = inst_detail
                    if loc_detail:
                        location = loc_detail

                    id_match = re.search(r"/job/(\d+)", full_url)
                    job_id_key = id_match.group(1) if id_match else full_url
                    job_id = JobPosting.generate_id("chronicle", job_id_key)

                    postings.append(
                        JobPosting(
                            id=job_id,
                            title=title,
                            institution=institution,
                            field="Transportation / Civil Engineering",
                            location=location,
                            deadline=deadline,
                            salary=salary,
                            link=full_url,
                            source="Chronicle",
                            raw_description=raw_text,
                        )
                    )
        except Exception as e:
            self.logger.error(f"Error scraping Chronicle HTML: {e}", exc_info=True)

        self.logger.info(f"Retrieved {len(postings)} listings from Chronicle")
        return postings
