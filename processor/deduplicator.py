import csv
import logging
import os
from datetime import datetime, timezone
from typing import Dict, List, Tuple
from scrapers.base import JobPosting


class JobDeduplicator:
    """Manages deduplication and historical tracking across daily scraper runs."""

    def __init__(self, csv_filepath: str = "jobs.csv"):
        self.csv_filepath = csv_filepath
        self.logger = logging.getLogger("processor.deduplicator")

    def load_existing_jobs(self) -> Dict[str, JobPosting]:
        """Load previously saved jobs from CSV file."""
        jobs: Dict[str, JobPosting] = {}
        if not os.path.exists(self.csv_filepath):
            return jobs

        try:
            with open(self.csv_filepath, mode="r", encoding="utf-8-sig") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    # Normalize keys to lowercase for robust matching
                    norm_row = {k.strip().lower(): (v.strip() if v else "") for k, v in row.items() if k}
                    
                    job_link = norm_row.get("link", "")
                    job_source = norm_row.get("source", "unknown")
                    job_id = norm_row.get("id") or JobPosting.generate_id(job_source, job_link)

                    lat_str = norm_row.get("latitude", "")
                    lon_str = norm_row.get("longitude", "")
                    lat = float(lat_str) if lat_str and lat_str != "None" else None
                    lon = float(lon_str) if lon_str and lon_str != "None" else None

                    title = norm_row.get("title", "")
                    # Filter out non-faculty postings (drivers, postdocs, etc.)
                    if not JobPosting.is_valid_faculty_posting(title):
                        continue

                    posting = JobPosting(
                        id=job_id,
                        title=title,
                        institution=norm_row.get("institution", ""),
                        field=norm_row.get("field/division") or norm_row.get("field", ""),
                        location=norm_row.get("location", ""),
                        deadline=norm_row.get("deadline", ""),
                        salary=norm_row.get("salary", ""),
                        link=job_link,
                        source=job_source,
                        raw_description=norm_row.get("raw_description", ""),
                        summary=norm_row.get("summary (gemini)") or norm_row.get("summary", ""),
                        research_topics=norm_row.get("research topics") or norm_row.get("research_topics", ""),
                        tenure_track=norm_row.get("tenure track") or norm_row.get("tenure_track", "Unspecified"),
                        date_first_seen=norm_row.get("date added") or norm_row.get("date_first_seen", ""),
                        date_last_verified=norm_row.get("last verified") or norm_row.get("date_last_verified", ""),
                        status=norm_row.get("status", "Active"),
                        latitude=lat,
                        longitude=lon,
                    )
                    jobs[job_id] = posting
            self.logger.info(f"Loaded {len(jobs)} valid faculty jobs from {self.csv_filepath}")
        except Exception as e:
            self.logger.error(f"Error reading existing {self.csv_filepath}: {e}", exc_info=True)

        return jobs

    def process_incoming(
        self, scraped_jobs: List[JobPosting]
    ) -> Tuple[List[JobPosting], List[JobPosting]]:
        """
        Deduplicate scraped jobs against historical records.
        Returns:
            Tuple[List[JobPosting] new_jobs_to_process, List[JobPosting] all_updated_jobs]
        """
        existing_jobs = self.load_existing_jobs()
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        new_jobs: List[JobPosting] = []

        # Index existing by both id and normalized link for robustness
        link_to_id = {j.link.strip().rstrip("/"): j.id for j in existing_jobs.values() if j.link}

        for job in scraped_jobs:
            if not JobPosting.is_valid_faculty_posting(job.title, job.raw_description):
                continue

            normalized_link = job.link.strip().rstrip("/")
            matched_id = job.id if job.id in existing_jobs else link_to_id.get(normalized_link)

            if matched_id:
                # Existing job: update verification date
                existing = existing_jobs[matched_id]
                existing.date_last_verified = today
                existing.status = "Active"
                # Preserve raw_description or any richer data if missing
                if not existing.raw_description and job.raw_description:
                    existing.raw_description = job.raw_description
            else:
                # Brand new job
                job.date_first_seen = today
                job.date_last_verified = today
                job.status = "Active"
                existing_jobs[job.id] = job
                link_to_id[normalized_link] = job.id
                new_jobs.append(job)

        self.logger.info(
            f"Deduplication complete: {len(new_jobs)} new jobs, {len(existing_jobs)} total tracked jobs."
        )
        return new_jobs, list(existing_jobs.values())
