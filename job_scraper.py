#!/usr/bin/env python3
"""
Assistant Professor Job Board Aggregator & Summarizer
Aggregates job postings from AcademicKeys, HigherEdJobs, Chronicle of Higher Education, and LinkedIn.
Uses Google Gemini for candidate CV fit evaluation (1-10 scale), weak screening filter, and structured summarization.
Exports to CSV, styled Excel (.xlsx), Google Sheets, and an interactive Folium map.
"""

import argparse
import logging
import os
import sys
from dotenv import load_dotenv

# Ensure UTF-8 output encoding across Windows consoles
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from scrapers import (
    AcademicKeysScraper,
    ChronicleScraper,
    HigherEdJobsScraper,
    LinkedInScraper,
)
from processor import (
    CVProfileManager,
    GeminiExtractor,
    GoogleSheetsSync,
    JobDeduplicator,
    JobExporter,
    MapGenerator,
    UniversityGeocoder,
)

# Load environment variables from .env file if available
load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("main")


def parse_args():
    parser = argparse.ArgumentParser(
        description="Aggregate and summarize Assistant Professor jobs in Transportation Engineering."
    )
    parser.add_argument(
        "--query",
        type=str,
        default="Assistant Professor Transportation, Assistant Professor Mobility, Assistant Professor Public Transportation",
        help="Comma-separated search queries for job boards (default: Transportation, Mobility, Public Transportation)",
    )
    parser.add_argument(
        "--max-per-source",
        type=int,
        default=20,
        help="Maximum listings to fetch per source (default: 20)",
    )
    parser.add_argument(
        "--sources",
        type=str,
        default="academickeys,higheredjobs,chronicle,linkedin",
        help="Comma-separated list of sources to scrape: academickeys, higheredjobs, chronicle, linkedin",
    )
    parser.add_argument(
        "--skip-gemini",
        action="store_true",
        help="Skip Gemini LLM summarization even if API key is present",
    )
    parser.add_argument(
        "--skip-sheets",
        action="store_true",
        help="Skip Google Sheets synchronization",
    )
    parser.add_argument(
        "--model",
        type=str,
        default=os.environ.get("GEMINI_MODEL", "gemini-3.6-flash"),
        help="Gemini model to use (default: gemini-3.6-flash)",
    )
    parser.add_argument(
        "--min-fit-score",
        type=int,
        default=3,
        help="Minimum fit score (1-10) to include in active results (default: 3)",
    )
    parser.add_argument(
        "--eval-prompt",
        type=str,
        default="eval_prompt.txt",
        help="Path to user-editable Gemini evaluation prompt template (default: eval_prompt.txt)",
    )
    parser.add_argument(
        "--cv-path",
        type=str,
        default="CV.pdf",
        help="Path to candidate CV PDF file (default: CV.pdf)",
    )
    parser.add_argument(
        "--re-evaluate",
        action="store_true",
        help="Re-evaluate existing jobs in jobs.csv lacking a fit score",
    )
    parser.add_argument(
        "--include-filtered",
        action="store_true",
        help="Include filtered/screened-out jobs in outputs (default: False)",
    )
    parser.add_argument(
        "--csv-out",
        type=str,
        default="jobs.csv",
        help="Output CSV file path (default: jobs.csv)",
    )
    parser.add_argument(
        "--excel-out",
        type=str,
        default="jobs.xlsx",
        help="Output Excel file path (default: jobs.xlsx)",
    )
    parser.add_argument(
        "--map-out",
        type=str,
        default="map.html",
        help="Output HTML map path (default: map.html)",
    )
    return parser.parse_args()


def main():
    args = parse_args()

    print("=" * 70)
    print("  Assistant Professor Job Aggregator & Summarizer")
    print(f"  Search Query:       '{args.query}'")
    print(f"  Gemini Model:       '{args.model}'")
    print(f"  Min Fit Threshold:  {args.min_fit_score}/10")
    print(f"  Prompt Template:    '{args.eval_prompt}'")
    print("=" * 70)

    # 1. Initialize Scrapers
    active_sources = [s.strip().lower() for s in args.sources.split(",") if s.strip()]
    scrapers = []

    if "academickeys" in active_sources:
        scrapers.append(AcademicKeysScraper())
    if "higheredjobs" in active_sources:
        scrapers.append(HigherEdJobsScraper())
    if "chronicle" in active_sources:
        scrapers.append(ChronicleScraper())
    if "linkedin" in active_sources:
        scrapers.append(LinkedInScraper())

    # 2. Scrape Job Postings
    queries = [q.strip() for q in args.query.split(",") if q.strip()]
    scraped_postings = []
    seen_urls_overall = set()

    for scraper in scrapers:
        print(f"\n[SCRAPING] Fetching listings from {scraper.name} across {len(queries)} search terms...")
        for q in queries:
            try:
                results = scraper.scrape(query=q, max_results=args.max_per_source)
                new_results = []
                for r in results:
                    clean_link = r.link.strip().rstrip("/")
                    if clean_link not in seen_urls_overall:
                        seen_urls_overall.add(clean_link)
                        new_results.append(r)
                scraped_postings.extend(new_results)
                print(f"  -> [{scraper.name}] '{q}': {len(results)} found ({len(new_results)} new unique)")
            except Exception as e:
                logger.error(f"Failed scraping {scraper.name} for query '{q}': {e}", exc_info=True)

    print(f"\n[SUMMARY] Total unique raw listings fetched across all sources: {len(scraped_postings)}")

    # 3. Deduplicate and Track Historical Records
    deduplicator = JobDeduplicator(csv_filepath=args.csv_out)
    new_jobs, all_jobs = deduplicator.process_incoming(scraped_postings)
    print(f"[DEDUPLICATION] Brand new postings discovered today: {len(new_jobs)}")
    print(f"[DEDUPLICATION] Total active and tracked postings:   {len(all_jobs)}")

    # 4. Candidate Fit Evaluation & Gemini Structured Extraction
    if not args.skip_gemini:
        extractor = GeminiExtractor(
            model_name=args.model,
            prompt_file=args.eval_prompt,
            min_fit_score=args.min_fit_score,
            cv_path=args.cv_path,
        )

        jobs_to_enrich = list(new_jobs)
        if args.re_evaluate:
            unscored_existing = [j for j in all_jobs if j.fit_score is None and j not in new_jobs]
            if unscored_existing:
                print(f"[RE-EVALUATION] Found {len(unscored_existing)} existing jobs lacking fit score to evaluate...")
                jobs_to_enrich.extend(unscored_existing)

        if jobs_to_enrich:
            print(f"\n[GEMINI] Evaluating candidate fit (1-10) with {args.model} for {len(jobs_to_enrich)} postings...")
            extractor.enrich_postings(jobs_to_enrich)

            # Detect any jobs screened out by weak filter or non-faculty rule
            filtered_jobs = [j for j in all_jobs if j.status.startswith("Filtered")]
            if filtered_jobs:
                print(f"[FILTER] Screened out {len(filtered_jobs)} low-relevance / non-faculty positions.")
                deduplicator.save_filtered_jobs(filtered_jobs)
                if not args.include_filtered:
                    all_jobs = [j for j in all_jobs if not j.status.startswith("Filtered")]

            # Post-enrichment deduplication by (institution, department)
            all_jobs, post_dupes = deduplicator.deduplicate_by_institution_department(all_jobs)
            if post_dupes:
                print(f"[DEDUPLICATION] Pruned {len(post_dupes)} duplicate positions sharing same institution and department.")
        else:
            print("\n[GEMINI] No new postings to evaluate with Gemini.")
    else:
        print("\n[GEMINI] Gemini evaluation skipped via --skip-gemini flag.")

    # 5. Geocode Institutions / Locations
    print("\n[GEOCODING] Geocoding university locations for interactive map...")
    geocoder = UniversityGeocoder()
    geocoder.enrich_coordinates(all_jobs)

    # 6. Export to CSV and Excel (.xlsx)
    print("\n[EXPORT] Exporting results to disk...")
    exporter = JobExporter(csv_filepath=args.csv_out, excel_filepath=args.excel_out)
    exporter.export_csv(all_jobs, include_filtered=args.include_filtered)
    exporter.export_excel(all_jobs, include_filtered=args.include_filtered)
    print(f"  -> Saved CSV to: {os.path.abspath(args.csv_out)}")
    print(f"  -> Saved Excel to: {os.path.abspath(args.excel_out)}")

    # 7. Generate Interactive Folium Map
    map_generator = MapGenerator(output_filepath=args.map_out)
    map_generator.generate_map(all_jobs, include_filtered=args.include_filtered)
    print(f"  -> Saved Map to: {os.path.abspath(args.map_out)}")

    # 8. Sync to Google Sheets (if configured)
    if not args.skip_sheets:
        print("\n[GOOGLE-SHEETS] Checking Google Sheets synchronization...")
        sheets_sync = GoogleSheetsSync()
        if sheets_sync.client and sheets_sync.sheet_id:
            sheets_sync.sync(all_jobs, include_filtered=args.include_filtered)
            print("  -> Google Sheets updated successfully!")
        else:
            if not sheets_sync.sheet_id:
                print("  -> Google Sheets sync SKIPPED: GOOGLE_SHEET_ID is missing from environment/secrets.")
            elif not sheets_sync.client:
                print("  -> Google Sheets sync SKIPPED: Google Service Account credentials missing (GOOGLE_CREDENTIALS secret or credentials.json file).")
            else:
                print("  -> Google Sheets sync skipped.")

    print("\n" + "=" * 70)
    print("[SUCCESS] Pipeline completed successfully!")
    print(f"• Active relevant jobs: {len(all_jobs)}")
    print(f"• New additions:        {len(new_jobs)}")
    print("=" * 70)


if __name__ == "__main__":
    main()
