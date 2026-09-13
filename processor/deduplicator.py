import csv
import json
import logging
import os
from datetime import datetime, timezone
from typing import Dict, List, Set, Tuple
from scrapers.base import JobPosting


class JobDeduplicator:
    """Manages deduplication, historical tracking, and filtered posting caching across daily scraper runs."""

    FILTERED_CACHE_FILE = os.path.join(".cache", "filtered_jobs.json")

    def __init__(self, csv_filepath: str = "jobs.csv"):
        self.csv_filepath = csv_filepath
        self.logger = logging.getLogger("processor.deduplicator")

    def load_filtered_ids(self) -> Set[str]:
        """Load IDs and links of previously screened-out jobs."""
        filtered_identifiers: Set[str] = set()
        if os.path.exists(self.FILTERED_CACHE_FILE):
            try:
                with open(self.FILTERED_CACHE_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    for item in data:
                        if isinstance(item, dict):
                            if item.get("id"):
                                filtered_identifiers.add(item["id"])
                            if item.get("link"):
                                filtered_identifiers.add(item["link"].strip().rstrip("/"))
            except Exception as e:
                self.logger.warning(f"Error reading filtered jobs cache {self.FILTERED_CACHE_FILE}: {e}")
        return filtered_identifiers

    def save_filtered_jobs(self, filtered_jobs: List[JobPosting]):
        """Append filtered jobs to persistent cache so they aren't re-scraped or re-evaluated."""
        if not filtered_jobs:
            return
        os.makedirs(os.path.dirname(self.FILTERED_CACHE_FILE), exist_ok=True)
        existing_list = []
        seen_ids = set()
        if os.path.exists(self.FILTERED_CACHE_FILE):
            try:
                with open(self.FILTERED_CACHE_FILE, "r", encoding="utf-8") as f:
                    existing_list = json.load(f)
                    for item in existing_list:
                        if isinstance(item, dict) and item.get("id"):
                            seen_ids.add(item["id"])
            except Exception:
                existing_list = []

        for j in filtered_jobs:
            if j.id not in seen_ids:
                existing_list.append({
                    "id": j.id,
                    "title": j.title,
                    "institution": j.institution,
                    "link": j.link,
                    "status": j.status,
                    "fit_score": j.fit_score,
                    "fit_reason": j.fit_reason,
                    "date_filtered": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                })
                seen_ids.add(j.id)

        try:
            with open(self.FILTERED_CACHE_FILE, "w", encoding="utf-8") as f:
                json.dump(existing_list, f, indent=2)
            self.logger.info(f"Recorded {len(filtered_jobs)} filtered jobs to {self.FILTERED_CACHE_FILE}")
        except Exception as e:
            self.logger.warning(f"Failed writing to {self.FILTERED_CACHE_FILE}: {e}")

    def load_existing_jobs(self) -> Dict[str, JobPosting]:
        """Load previously saved jobs from CSV file."""
        jobs: Dict[str, JobPosting] = {}
        if not os.path.exists(self.csv_filepath):
            return jobs

        filtered_to_cache: List[JobPosting] = []

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

                    fit_score_val = norm_row.get("fit score (1-10)") or norm_row.get("fit score") or norm_row.get("fit_score", "")
                    try:
                        fit_score = int(fit_score_val) if fit_score_val and fit_score_val != "None" else None
                    except (ValueError, TypeError):
                        fit_score = None
                    fit_reason = norm_row.get("fit reason") or norm_row.get("fit_reason", "")

                    title = norm_row.get("title", "")
                    status = norm_row.get("status", "Active")

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
                        fit_score=fit_score,
                        fit_reason=fit_reason,
                        tenure_track=norm_row.get("tenure track") or norm_row.get("tenure_track", "Unspecified"),
                        date_first_seen=norm_row.get("date added") or norm_row.get("date_first_seen", ""),
                        date_last_verified=norm_row.get("last verified") or norm_row.get("date_last_verified", ""),
                        status=status,
                        latitude=lat,
                        longitude=lon,
                    )

                    # If this posting is non-faculty or previously filtered, keep in filtered cache instead of active jobs
                    if not JobPosting.is_valid_faculty_posting(title) or status.startswith("Filtered"):
                        posting.status = "Filtered (Non-Faculty)" if not JobPosting.is_valid_faculty_posting(title) else status
                        filtered_to_cache.append(posting)
                        continue

                    jobs[job_id] = posting

            if filtered_to_cache:
                self.save_filtered_jobs(filtered_to_cache)

            self.logger.info(f"Loaded {len(jobs)} active jobs from {self.csv_filepath}")
        except Exception as e:
            self.logger.error(f"Error reading existing {self.csv_filepath}: {e}", exc_info=True)

        return jobs

    def process_incoming(
        self, scraped_jobs: List[JobPosting]
    ) -> Tuple[List[JobPosting], List[JobPosting]]:
        """
        Deduplicate scraped jobs against historical records and filtered jobs cache.
        Returns:
            Tuple[List[JobPosting] new_jobs_to_process, List[JobPosting] all_updated_jobs]
        """
        existing_jobs = self.load_existing_jobs()
        filtered_identifiers = self.load_filtered_ids()

        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        new_jobs: List[JobPosting] = []

        # Index existing active jobs by both id and normalized link
        link_to_id = {j.link.strip().rstrip("/"): j.id for j in existing_jobs.values() if j.link}

        for job in scraped_jobs:
            normalized_link = job.link.strip().rstrip("/")

            # Check if previously screened out by weak filter or non-faculty rule
            if job.id in filtered_identifiers or normalized_link in filtered_identifiers:
                continue

            # Instant title-based non-faculty check
            if not JobPosting.is_valid_faculty_posting(job.title, job.raw_description):
                job.status = "Filtered (Non-Faculty)"
                self.save_filtered_jobs([job])
                filtered_identifiers.add(job.id)
                filtered_identifiers.add(normalized_link)
                continue

            matched_id = job.id if job.id in existing_jobs else link_to_id.get(normalized_link)

            if matched_id:
                # Existing active job: update verification date
                existing = existing_jobs[matched_id]
                existing.date_last_verified = today
                existing.status = "Active"
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
            f"Deduplication complete: {len(new_jobs)} new jobs, {len(existing_jobs)} active tracked jobs."
        )
        return new_jobs, list(existing_jobs.values())
