#!/usr/bin/env python3
"""
Assistant Professor Job Board Aggregator & Summarizer
Aggregates job postings from AcademicKeys, HigherEdJobs, Chronicle of Higher Education, and LinkedIn.
Uses Google Gemini Flash for structured parsing and summarization.
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
        default="Assistant Professor Transportation",
        help="Search query for job boards (default: 'Assistant Professor Transportation')",
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
    print(f"  Search Query: '{args.query}'")
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
    scraped_postings = []
    for scraper in scrapers:
        print(f"\n[SCRAPING] Fetching listings from {scraper.name}...")
        try:
            results = scraper.scrape(query=args.query, max_results=args.max_per_source)
            scraped_postings.extend(results)
            print(f"  -> Retrieved {len(results)} postings from {scraper.name}")
        except Exception as e:
            logger.error(f"Failed scraping {scraper.name}: {e}", exc_info=True)

    print(f"\n[SUMMARY] Total raw listings fetched across all sources: {len(scraped_postings)}")

    # 3. Deduplicate and Track Historical Records
    deduplicator = JobDeduplicator(csv_filepath=args.csv_out)
    new_jobs, all_jobs = deduplicator.process_incoming(scraped_postings)
    print(f"[DEDUPLICATION] Brand new postings discovered today: {len(new_jobs)}")
    print(f"[DEDUPLICATION] Total active and tracked postings: {len(all_jobs)}")

    # 4. Gemini Structured Extraction & 2-Sentence Summary
    if not args.skip_gemini and new_jobs:
        print(f"\n[GEMINI] Running Google Gemini Flash on {len(new_jobs)} new postings...")
        extractor = GeminiExtractor()
        extractor.enrich_postings(new_jobs)
    elif not new_jobs:
        print("\n[GEMINI] No new postings to process with Gemini.")
    else:
        print("\n[GEMINI] Gemini summarization skipped via --skip-gemini flag.")

    # 5. Geocode Institutions / Locations
    print("\n[GEOCODING] Geocoding university locations for interactive map...")
    geocoder = UniversityGeocoder()
    geocoder.enrich_coordinates(all_jobs)

    # 6. Export to CSV and Excel (.xlsx)
    print("\n[EXPORT] Exporting results to disk...")
    exporter = JobExporter(csv_filepath=args.csv_out, excel_filepath=args.excel_out)
    exporter.export_csv(all_jobs)
    exporter.export_excel(all_jobs)
    print(f"  -> Saved CSV to: {os.path.abspath(args.csv_out)}")
    print(f"  -> Saved Excel to: {os.path.abspath(args.excel_out)}")

    # 7. Generate Interactive Folium Map
    map_generator = MapGenerator(output_filepath=args.map_out)
    map_generator.generate_map(all_jobs)
    print(f"  -> Saved Map to: {os.path.abspath(args.map_out)}")

    # 8. Sync to Google Sheets (if configured)
    if not args.skip_sheets:
        print("\n[GOOGLE-SHEETS] Checking Google Sheets synchronization...")
        sheets_sync = GoogleSheetsSync()
        if sheets_sync.client and sheets_sync.sheet_id:
            sheets_sync.sync(all_jobs)
            print("  -> Google Sheets updated successfully!")
        else:
            print("  -> Google Sheets sync skipped (not configured or missing credentials).")

    print("\n" + "=" * 70)
    print("[SUCCESS] Pipeline completed successfully!")
    print(f"• Total tracked jobs: {len(all_jobs)}")
    print(f"• New additions:      {len(new_jobs)}")
    print("=" * 70)


if __name__ == "__main__":
    main()
