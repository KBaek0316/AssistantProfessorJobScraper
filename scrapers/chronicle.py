import re
import xml.etree.ElementTree as ET
from typing import List
from urllib.parse import urljoin
from bs4 import BeautifulSoup
from .base import BaseScraper, JobPosting


class ChronicleScraper(BaseScraper):
    """Scraper for The Chronicle of Higher Education Jobs."""

    SEARCH_URL = "https://jobs.chronicle.com/searchjobs/"
    RSS_URL = "https://jobs.chronicle.com/jobs/rss/"

    def __init__(self):
        super().__init__("Chronicle")

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
                    pub_elem = item.find("pubDate")

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

                    # Extract institution/location from description or title
                    institution = "Chronicle Listed University"
                    location = "United States"

                    postings.append(
                        JobPosting(
                            id=job_id,
                            title=title,
                            institution=institution,
                            field="Transportation / Civil Engineering",
                            location=location,
                            deadline="See full listing",
                            salary="Not specified",
                            link=link,
                            source="Chronicle",
                            raw_description=desc or title,
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

                    id_match = re.search(r"/job/(\d+)", full_url)
                    job_id_key = id_match.group(1) if id_match else full_url
                    job_id = JobPosting.generate_id("chronicle", job_id_key)

                    postings.append(
                        JobPosting(
                            id=job_id,
                            title=title,
                            institution="Chronicle Listed University",
                            field="Transportation / Civil Engineering",
                            location="United States",
                            deadline="See full listing",
                            salary="Not specified",
                            link=full_url,
                            source="Chronicle",
                            raw_description=raw_text,
                        )
                    )
        except Exception as e:
            self.logger.error(f"Error scraping Chronicle HTML: {e}", exc_info=True)

        self.logger.info(f"Retrieved {len(postings)} listings from Chronicle")
        return postings
