import csv
import json
import logging
import os
from datetime import datetime, timezone
from typing import Dict, List, Optional, Set, Tuple
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

            # Prune duplicate (institution, department) pairings loaded from disk
            active_list, dupes = self.deduplicate_by_institution_department(list(jobs.values()))
            jobs = {j.id: j for j in active_list}

            if filtered_to_cache:
                self.save_filtered_jobs(filtered_to_cache)

            self.logger.info(f"Loaded {len(jobs)} active unique jobs from {self.csv_filepath}")
        except Exception as e:
            self.logger.error(f"Error reading existing {self.csv_filepath}: {e}", exc_info=True)

        return jobs

    DEPARTMENT_STOPWORDS = {
        "department", "dept", "school", "college", "division", "faculty", "program",
        "of", "and", "the", "in", "for", "at", "to", "&", "/", ",", "-", "ids",
        "engineering", "sciences", "science", "studies", "center", "institute",
    }

    TITLE_STOPWORDS = {
        "assistant", "associate", "full", "tenure", "track", "tenured", "tenure-track",
        "professor", "professorship", "faculty", "open", "rank", "in", "of", "for", "at",
        "and", "the", "to", "&", "/", "-", "position", "positions",
    }

    @classmethod
    def clean_institution(cls, inst: str) -> str:
        import re
        return re.sub(r"[\s,\-/]+", " ", (inst or "").lower()).strip()

    @classmethod
    def get_dept_tokens(cls, dept: str) -> Set[str]:
        import re
        if not dept:
            return set()
        return set(re.findall(r"[a-z0-9\.\']+", dept.lower())) - cls.DEPARTMENT_STOPWORDS

    @classmethod
    def get_title_tokens(cls, title: str) -> Set[str]:
        import re
        if not title:
            return set()
        return set(re.findall(r"[a-z0-9]+", title.lower())) - cls.TITLE_STOPWORDS

    @classmethod
    def is_same_position(cls, j1: JobPosting, j2: JobPosting) -> bool:
        """Determines if two postings represent the same position at the same institution."""
        if cls.clean_institution(j1.institution) != cls.clean_institution(j2.institution):
            return False

        # If both links are identical
        if j1.link and j2.link and j1.link.strip().rstrip("/") == j2.link.strip().rstrip("/"):
            return True

        d1 = cls.get_dept_tokens(j1.field)
        d2 = cls.get_dept_tokens(j2.field)
        t1 = cls.get_title_tokens(j1.title)
        t2 = cls.get_title_tokens(j2.title)

        dept_ov = len(d1 & d2) / min(len(d1), len(d2)) if (d1 and d2) else 0.0
        title_ov = len(t1 & t2) / min(len(t1), len(t2)) if (t1 and t2) else 0.0

        # 1. Exact or near-identical title at same institution (e.g. Wisconsin Madison)
        if title_ov >= 0.85:
            return True

        # 2. Strong title and department overlap (e.g. UIC Operations Management / IDS)
        if title_ov >= 0.6 and dept_ov >= 0.5:
            return True

        # 3. Same department at same institution (User rule: "If multiple jobs' institution and department are same, keep only the latest update")
        if dept_ov >= 0.75:
            return True

        return False

    def deduplicate_by_institution_department(
        self, jobs: List[JobPosting]
    ) -> Tuple[List[JobPosting], List[JobPosting]]:
        """
        Groups jobs representing the same position/department at an institution.
        Keeps only the single latest update per position group.
        The superseded duplicates are marked as 'Filtered (Duplicate)' and returned.

        Returns:
            Tuple[List[JobPosting] unique_active_jobs, List[JobPosting] duplicate_jobs]
        """
        kept_jobs: List[JobPosting] = []
        duplicates: List[JobPosting] = []
        visited_ids: Set[str] = set()

        for i, j1 in enumerate(jobs):
            if j1.id in visited_ids:
                continue

            cluster = [j1]
            visited_ids.add(j1.id)

            for j2 in jobs[i + 1:]:
                if j2.id in visited_ids:
                    continue
                if self.is_same_position(j1, j2):
                    cluster.append(j2)
                    visited_ids.add(j2.id)

            if len(cluster) == 1:
                kept_jobs.append(cluster[0])
            else:
                # Rank: latest update first
                # 1. date_first_seen (descending)
                # 2. date_last_verified (descending)
                # 3. fit_score (descending)
                # 4. id (deterministic)
                sorted_cluster = sorted(
                    cluster,
                    key=lambda x: (
                        x.date_first_seen or "",
                        x.date_last_verified or "",
                        x.fit_score or 0,
                        x.id or "",
                    ),
                    reverse=True,
                )
                winner = sorted_cluster[0]
                kept_jobs.append(winner)

                for loser in sorted_cluster[1:]:
                    loser.status = f"Filtered (Duplicate of {winner.id[:8]} - {winner.title[:30]})"
                    duplicates.append(loser)
                    self.logger.info(
                        f"Deduplicated: Kept '{winner.title}' ({winner.date_first_seen}), "
                        f"filtered duplicate '{loser.title}' ({loser.date_first_seen}) at {winner.institution}"
                    )

        if duplicates:
            self.save_filtered_jobs(duplicates)

        return kept_jobs, duplicates

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

            # Location pre-check if location is present in scraped card
            if job.location and not JobPosting.is_allowed_location(job.location):
                job.status = "Filtered (Location Outside Scope)"
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

        # Apply institution & department deduplication across all active jobs
        active_list, dupes = self.deduplicate_by_institution_department(list(existing_jobs.values()))
        active_ids = {j.id for j in active_list}
        new_jobs = [j for j in new_jobs if j.id in active_ids]

        self.logger.info(
            f"Deduplication complete: {len(new_jobs)} new jobs, {len(active_list)} active tracked jobs."
        )
        return new_jobs, active_list
