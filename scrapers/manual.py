import json
import logging
import os
from typing import List, Optional
from .base import JobPosting

logger = logging.getLogger("scraper.Manual")


def load_manual_jobs(filepath: Optional[str] = "manual_jobs.json") -> List[JobPosting]:
    """
    Load manually curated job postings from a JSON file (default: manual_jobs.json)
    for openings not listed on any of the scraped academic job boards.

    Each entry in the JSON array (or {"jobs": [...]}) supports:
      - title (str, required): Official job title
      - institution (str, required): University or institution name
      - field / department (str, optional): Department, school, or division
      - location (str, optional): Campus city/state/country (default: 'United States')
      - deadline (str, optional): Deadline text or YYYY-MM-DD (inferred from raw_description if omitted)
      - salary (str, optional): Salary range (default: 'Not specified')
      - link (str, optional): Application URL or form link (may be empty for email-only postings)
      - tenure_track (str, optional): e.g. 'Tenure-Track', 'Non-Tenure Track', 'Unspecified'
      - raw_description (str, optional): Full job posting text (e.g. from PDF or email) for Gemini evaluation
      - source (str, optional): Defaults to 'Manual'
      - id (str, optional): Deterministic ID generated automatically if omitted
    """
    if not filepath or not os.path.exists(filepath):
        return []

    try:
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        logger.warning(f"Could not parse manual jobs file '{filepath}': {e}")
        return []

    items = data.get("jobs", []) if isinstance(data, dict) else data
    if not isinstance(items, list):
        logger.warning(f"Manual jobs file '{filepath}' must contain a JSON list or {{\"jobs\": [...]}}.")
        return []

    postings: List[JobPosting] = []
    seen_ids = set()

    for idx, item in enumerate(items):
        if not isinstance(item, dict):
            continue

        title = str(item.get("title") or "").strip()
        institution = str(item.get("institution") or "").strip()
        if not title or not institution:
            logger.warning(f"Skipping manual job entry #{idx + 1}: missing required 'title' or 'institution'.")
            continue

        field_name = str(item.get("field") or item.get("department") or "Not specified").strip()
        location = str(item.get("location") or "United States").strip()
        salary = str(item.get("salary") or "Not specified").strip()
        link = str(item.get("link") or "").strip()
        raw_desc = str(item.get("raw_description") or item.get("description") or "").strip()
        tenure_track = str(item.get("tenure_track") or "Unspecified").strip()
        source = str(item.get("source") or "Manual").strip() or "Manual"

        deadline = str(item.get("deadline") or "").strip()
        if not deadline and raw_desc:
            deadline = JobPosting.extract_deadline_from_text(raw_desc) or "Open until filled"
        if not deadline:
            deadline = "Open until filled"

        explicit_id = str(item.get("id") or "").strip()
        id_seed = link if link else f"{institution.lower()}|{field_name.lower()}|{title.lower()}"
        job_id = explicit_id or JobPosting.generate_id(source, id_seed)

        if job_id in seen_ids:
            continue
        seen_ids.add(job_id)

        fit_score_val = item.get("fit_score")
        fit_score: Optional[int] = None
        if fit_score_val is not None and str(fit_score_val).strip() != "":
            try:
                fit_score = max(1, min(10, int(fit_score_val)))
            except (ValueError, TypeError):
                fit_score = None

        posting = JobPosting(
            id=job_id,
            title=title,
            institution=institution,
            field=field_name,
            location=location,
            deadline=deadline,
            salary=salary,
            link=link,
            source=source,
            raw_description=raw_desc,
            summary=str(item.get("summary") or "").strip(),
            research_topics=str(item.get("research_topics") or "").strip(),
            fit_score=fit_score,
            fit_reason=str(item.get("fit_reason") or "").strip(),
            tenure_track=tenure_track,
        )
        if item.get("date_first_seen"):
            posting.date_first_seen = str(item["date_first_seen"]).strip()

        postings.append(posting)

    logger.info(f"Loaded {len(postings)} manual job entries from '{filepath}'")
    return postings
