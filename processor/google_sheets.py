import json
import logging
import os
from typing import List, Optional
from scrapers.base import JobPosting


class GoogleSheetsSync:
    """Syncs job postings to a remote Google Sheet using a Service Account."""

    COLUMNS = [
        "Title",
        "Institution",
        "Field/Division",
        "Fit Score (1-10)",
        "Fit Reason",
        "Research Topics",
        "Tenure Track",
        "Location",
        "Deadline",
        "Salary",
        "Summary (Gemini)",
        "Link",
        "Source",
        "Date Added",
        "Last Verified",
        "Status",
        "ID",
    ]

    def __init__(
        self,
        sheet_id: Optional[str] = None,
        credentials_file: Optional[str] = None,
        credentials_json: Optional[str] = None,
        tab_name: Optional[str] = None,
    ):
        self.logger = logging.getLogger("processor.google_sheets")
        self.sheet_id = sheet_id or os.environ.get("GOOGLE_SHEET_ID")
        self.tab_name = tab_name or os.environ.get("GOOGLE_SHEET_TAB_NAME", "Jobs")
        self.credentials_file = credentials_file or os.environ.get("GOOGLE_SERVICE_ACCOUNT_FILE", "credentials.json")
        self.credentials_json = credentials_json or os.environ.get("GOOGLE_CREDENTIALS")
        self.client = None

        self._initialize_client()

    def _initialize_client(self):
        if not self.sheet_id:
            self.logger.info("GOOGLE_SHEET_ID not provided. Google Sheets sync is disabled.")
            return

        try:
            import gspread
            from google.oauth2.service_account import Credentials

            scopes = [
                "https://www.googleapis.com/auth/spreadsheets",
                "https://www.googleapis.com/auth/drive",
            ]

            if self.credentials_json:
                creds_dict = json.loads(self.credentials_json)
                creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
                self.client = gspread.authorize(creds)
                self.logger.info("Authorized Google Sheets client via JSON credentials string.")
            elif os.path.exists(self.credentials_file):
                creds = Credentials.from_service_account_file(self.credentials_file, scopes=scopes)
                self.client = gspread.authorize(creds)
                self.logger.info(f"Authorized Google Sheets client via file: {self.credentials_file}")
            else:
                self.logger.info("No service account credentials found. Google Sheets sync disabled.")
        except Exception as e:
            self.logger.warning(f"Failed to initialize Google Sheets client: {e}")

    def sync(self, postings: List[JobPosting], include_filtered: bool = False):
        """Upload/sync current postings to Google Sheets."""
        if not self.client or not self.sheet_id:
            return

        if not include_filtered:
            postings = [p for p in postings if not p.status.startswith("Filtered")]

        try:
            spreadsheet = self.client.open_by_key(self.sheet_id)

            # Get or create worksheet
            try:
                worksheet = spreadsheet.worksheet(self.tab_name)
            except Exception:
                worksheet = spreadsheet.add_worksheet(title=self.tab_name, rows=100, cols=20)

            # Build rows data
            rows = [self.COLUMNS]
            for p in postings:
                rows.append([
                    p.title,
                    p.institution,
                    p.field,
                    p.fit_score if p.fit_score is not None else "",
                    p.fit_reason,
                    p.research_topics,
                    p.tenure_track,
                    p.location,
                    p.deadline,
                    p.salary,
                    p.summary,
                    p.link,
                    p.source,
                    p.date_first_seen,
                    p.date_last_verified,
                    p.status,
                    p.id,
                ])

            # Update worksheet in a single API call
            worksheet.clear()
            worksheet.update("A1", rows)
            # Format header row with bold text
            worksheet.format("A1:Q1", {"textFormat": {"bold": True}})

            self.logger.info(f"Successfully synced {len(postings)} active jobs to Google Sheet '{spreadsheet.title}'")

        except Exception as e:
            self.logger.error(f"Error syncing to Google Sheet: {e}", exc_info=True)
