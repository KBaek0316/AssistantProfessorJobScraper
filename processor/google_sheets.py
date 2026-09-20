import base64
import json
import logging
import os
import re
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
        "Deadline Date",
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

        # Normalize and extract Sheet ID (in case a full URL was provided)
        raw_sheet_id = sheet_id or os.environ.get("GOOGLE_SHEET_ID")
        if raw_sheet_id:
            raw_sheet_id = str(raw_sheet_id).strip().strip("'\"")
            m = re.search(r"/spreadsheets/d/([a-zA-Z0-9-_]+)", raw_sheet_id)
            self.sheet_id = m.group(1) if m else raw_sheet_id
        else:
            self.sheet_id = None

        # Robust tab name fallback: if env var is empty string or whitespace, default to 'Jobs'
        raw_tab = tab_name or os.environ.get("GOOGLE_SHEET_TAB_NAME")
        self.tab_name = raw_tab.strip() if (raw_tab and raw_tab.strip()) else "Jobs"

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

            # Fallback checks for alternative credential env var names
            if not self.credentials_json:
                for alt_var in (
                    "GOOGLE_SERVICE_ACCOUNT",
                    "GOOGLE_SERVICE_ACCOUNT_JSON",
                    "GOOGLE_APPLICATION_CREDENTIALS_JSON",
                    "SERVICE_ACCOUNT_KEY",
                    "SERVICE_ACCOUNT_JSON",
                    "GSPREAD_CREDENTIALS",
                ):
                    val = os.environ.get(alt_var)
                    if val and val.strip():
                        self.credentials_json = val.strip()
                        break

            if self.credentials_json and self.credentials_json.strip():
                raw_cred = self.credentials_json.strip().strip("'\"")
                creds_dict = None
                try:
                    creds_dict = json.loads(raw_cred)
                except Exception:
                    # Attempt base64 decode if raw_cred was base64 encoded
                    try:
                        decoded = base64.b64decode(raw_cred).decode("utf-8")
                        creds_dict = json.loads(decoded)
                    except Exception:
                        pass

                if creds_dict:
                    creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
                    self.client = gspread.authorize(creds)
                    self.logger.info("Authorized Google Sheets client via JSON credentials string.")
                elif os.path.exists(raw_cred):
                    creds = Credentials.from_service_account_file(raw_cred, scopes=scopes)
                    self.client = gspread.authorize(creds)
                    self.logger.info(f"Authorized Google Sheets client via file: {raw_cred}")
                else:
                    self.logger.warning("Could not parse GOOGLE_CREDENTIALS as valid JSON or existing file path.")
            elif os.path.exists(self.credentials_file):
                creds = Credentials.from_service_account_file(self.credentials_file, scopes=scopes)
                self.client = gspread.authorize(creds)
                self.logger.info(f"Authorized Google Sheets client via file: {self.credentials_file}")
            else:
                self.logger.info("No service account credentials found. Google Sheets sync disabled.")
        except Exception as e:
            self.logger.warning(f"Failed to initialize Google Sheets client: {e}")

    def sync(self, postings: List[JobPosting], include_filtered: bool = False) -> bool:
        """Upload/sync current postings to Google Sheets. Returns True on success, False otherwise."""
        if not self.client or not self.sheet_id:
            return False

        if not self.tab_name or not self.tab_name.strip():
            self.tab_name = "Jobs"

        if not include_filtered:
            postings = [p for p in postings if not p.status.startswith("Filtered")]

        from scrapers.base import sort_postings_by_deadline
        postings = sort_postings_by_deadline(postings)

        try:
            spreadsheet = self.client.open_by_key(self.sheet_id)

            # Get or create worksheet
            try:
                worksheet = spreadsheet.worksheet(self.tab_name)
            except Exception:
                # If only 1 worksheet exists, rename it to avoid creating redundant tabs
                all_sheets = spreadsheet.worksheets()
                if len(all_sheets) == 1:
                    worksheet = all_sheets[0]
                    worksheet.update_title(self.tab_name)
                else:
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
                    p.deadline_date,
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
            worksheet.format("A1:R1", {"textFormat": {"bold": True}})

            self.logger.info(f"Successfully synced {len(postings)} active jobs to Google Sheet '{spreadsheet.title}'")
            return True

        except Exception as e:
            self.logger.error(f"Error syncing to Google Sheet: {e}", exc_info=True)
            return False
