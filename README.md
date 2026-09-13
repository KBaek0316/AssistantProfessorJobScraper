# Assistant Professor Job Board Aggregator & Summarizer

An automated, daily web aggregator designed to track and summarize Assistant Professor job listings in **Transportation Engineering** (and related Civil / Systems Engineering disciplines) across the United States.

It collects postings from **AcademicKeys**, **HigherEdJobs**, **The Chronicle of Higher Education**, and **LinkedIn**, uses **Google Gemini Flash** to extract structured metadata and a 2-sentence summary, exports to **Excel (`.xlsx`)**, **Google Sheets**, and **CSV**, and plots hiring universities on an **interactive geographic map (`map.html`)**.

---

## Key Features

- **Multi-Site Scraping**:
  - [AcademicKeys Engineering](https://engineering.academickeys.com/seeker_search.php)
  - [HigherEdJobs Faculty](https://www.higheredjobs.com/faculty/)
  - [The Chronicle of Higher Education Jobs](https://jobs.chronicle.com/)
  - **LinkedIn Jobs** (via public guest search API — no login required, zero account ban risk)
- **Candidate CV Fit Evaluation & 1–10 Relevance Scoring**:
  - Automatically matches job postings against your research profile extracted from **`CV.pdf`**.
  - Assigns a **1 to 10 Fit Score** and a concise **Fit Reason** explaining why each job is a match or mismatch.
  - Highlights core Transportation Engineering & Planning roles (scores 8–10) in vibrant green in Excel and Folium map.
  - Welcomes interdisciplinary positions (e.g. Urban Planning, Industrial/Systems Engineering, Data Science) *if* they genuinely seek mobility/transportation expertise.
- **Weak Relevance Screening Filter**:
  - Automatically screens out irrelevant subfields (e.g. Water Resources/Hydrology jobs that only mention DOTs incidentally, Structural, Geotechnical, or non-engineering disciplines like Film, Nursing, Pharmacy).
  - Screened-out postings are excluded from active outputs and saved to `.cache/filtered_jobs.json` so they are never re-scraped or re-evaluated.
  - Configurable sensitivity via `--min-fit-score` (default: `3`).
- **User-Editable Evaluation Prompt (`eval_prompt.txt`)**:
  - Customize how Gemini evaluates job postings simply by opening and editing [eval_prompt.txt](file:///c:/Users/baek0040/Documents/GitHub/AssistantProfessorJobScraper/eval_prompt.txt) in your favorite text editor.
- **Complete CV Privacy**:
  - **`CV.pdf`** is strictly listed in `.gitignore` and is never committed to GitHub.
  - A built-in fallback profile ensures GitHub Actions workflows run seamlessly without needing your CV on GitHub.
- **Dual Export & Real-Time Sync**:
  - **Excel (`jobs.xlsx`)**: Cleanly formatted spreadsheet with colored headers, fit score highlighting, and clickable application links.
  - **Google Sheets**: Live synchronization with dedicated `Fit Score` and `Fit Reason` columns.
  - **CSV (`jobs.csv`)**: Tabular format for easy data analysis.
- **Interactive Map (`map.html`)**:
  - Built with Folium & Leaflet using high-reliability Esri basemaps.
  - Interactive pins displaying fit score badges, research topics, summaries, and direct application links.

---

## Python Environment Setup

The recommended environment name is **`scraping`**. You can set it up using either **Conda** (recommended) or standard **Python `venv`**.

### Option A: Using Conda (Recommended)

1. Open your terminal (PowerShell, Command Prompt, or Bash) and create the `scraping` environment:
   ```bash
   conda create -n scraping python=3.12 -y
   ```
2. Activate the environment:
   ```bash
   conda activate scraping
   ```
3. Install the required dependencies:
   ```bash
   pip install -r requirements.txt
   ```

### Option B: Using Python `venv`

1. Create a virtual environment named `scraping`:
   ```bash
   python -m venv scraping
   ```
2. Activate the environment:
   - **Windows (PowerShell)**:
     ```powershell
     .\scraping\Scripts\Activate.ps1
     ```
   - **Windows (CMD)**:
     ```cmd
     .\scraping\Scripts\activate.bat
     ```
   - **macOS / Linux**:
     ```bash
     source scraping/bin/activate
     ```
3. Install the dependencies:
   ```bash
   pip install -r requirements.txt
   ```

---

## API Keys & Credentials Guide

### 1. Google Gemini API Key (Required for AI Summarization)

- **How to get it**:
  1. Visit [Google AI Studio](https://aistudio.google.com/).
  2. Sign in with your Google account and click **Get API key**.
  3. Create a new API key (free tier includes generous limits: 15 requests/min and up to 1M tokens/min).
- **How to store it locally**:
  1. Copy [.env.example](file:///c:/Users/baek0040/Documents/GitHub/AssistantProfessorJobScraper/.env.example) to `.env`:
     ```bash
     cp .env.example .env
     ```
  2. Open `.env` and paste your key:
     ```env
     GEMINI_API_KEY=AIzaSy...your_key_here
     ```
  > [!NOTE]
  > `.env` is listed in `.gitignore` so your API key will never be committed or pushed to GitHub.

---

### 2. Google Sheets Credentials (Optional)

If you wish to synchronize job listings directly to a live Google Sheet:

1. **Create a Google Cloud Service Account**:
   - Go to the [Google Cloud Console](https://console.cloud.google.com/).
   - Create a project (e.g. `JobScraper`) and enable both the **Google Sheets API** and **Google Drive API**.
   - Navigate to **IAM & Admin > Service Accounts** and click **Create Service Account**.
   - Create a JSON Key for this service account and download it.
2. **Configure Local Access**:
   - Rename the downloaded JSON file to `credentials.json` and place it in the root of this project repository (this file is also in `.gitignore`).
   - Create a Google Sheet in your personal Google Drive.
   - Click **Share** on the Google Sheet, and paste the service account email (e.g., `job-scraper@...iam.gserviceaccount.com`) with **Editor** permissions.
   - Copy the Sheet ID from your Google Sheet URL:
     `https://docs.google.com/spreadsheets/d/`**`<YOUR_SHEET_ID>`**`/edit`
   - In your local `.env`, add:
     ```env
     GOOGLE_SHEET_ID=your_sheet_id_here
     GOOGLE_SERVICE_ACCOUNT_FILE=credentials.json
     GOOGLE_SHEET_TAB_NAME=Jobs
     ```
  > [!TIP]
  > If Google Sheet credentials are not provided, the scraper gracefully skips Google Sheets sync and still outputs `jobs.xlsx`, `jobs.csv`, and `map.html` locally.

---

### 3. Setting Up GitHub Actions Secrets (For Daily Cloud Automation)

To allow the daily GitHub Action to run automatically in the cloud:

1. Go to your repository on GitHub.
2. Navigate to **Settings > Secrets and variables > Actions**.
3. Click **New repository secret** and add:
   - `GEMINI_API_KEY`: Your Gemini API key.
   - `GOOGLE_SHEET_ID` *(optional)*: Your Google Sheet ID.
   - `GOOGLE_CREDENTIALS` *(optional)*: The entire contents of your `credentials.json` file pasted as raw text.
4. The workflow will automatically run every day at 06:00 UTC, or you can trigger it manually anytime via the **Actions** tab by clicking **Run workflow**.

---

## Running the Scraper

### Basic Run
Run with default settings (queries *"Assistant Professor Transportation"* across all 4 platforms):
```bash
python job_scraper.py
```

### Advanced Options

```bash
# Custom search query
python job_scraper.py --query "Assistant Professor Transportation Engineering"

# Adjust max results per source
python job_scraper.py --max-per-source 30

# Scrape specific sources only (e.g., HigherEdJobs and LinkedIn)
python job_scraper.py --sources higheredjobs,linkedin

# Skip Gemini processing (for fast dry runs without AI)
python job_scraper.py --skip-gemini

# Skip Google Sheets sync
python job_scraper.py --skip-sheets
```

---

## Output Files

Once the script completes, the following files are updated in the project directory:

| File | Description |
| :--- | :--- |
| `jobs.xlsx` | Beautifully styled Excel spreadsheet with auto-width columns and clickable links. |
| `jobs.csv` | Standard comma-separated values file containing all tracked positions and historical metadata. |
| `map.html` | Standalone interactive map showing all hiring universities. Double-click or open in any web browser. |
| `.cache/geocache.json` | Local cache of university coordinates to avoid repeated geocoding requests. |

---

## File Structure

```
AssistantProfessorJobScraper/
├── .github/
│   └── workflows/
│       └── daily_scrape.yml      # Daily automated GitHub Actions workflow
├── scrapers/
│   ├── __init__.py
│   ├── base.py                   # BaseScraper & JobPosting data model
│   ├── academickeys.py           # AcademicKeys Engineering scraper
│   ├── higheredjobs.py           # HigherEdJobs Faculty scraper
│   ├── chronicle.py              # The Chronicle of Higher Education scraper
│   └── linkedin.py               # LinkedIn Public Guest search scraper
├── processor/
│   ├── __init__.py
│   ├── deduplicator.py           # Historical tracking & duplicate prevention
│   ├── gemini_extractor.py       # Google Gemini Flash structured parser & summarizer
│   ├── geocoder.py               # University geocoding with local caching
│   ├── exporter.py               # CSV and styled Excel (.xlsx) generator
│   ├── google_sheets.py          # Google Sheets cloud synchronizer
│   └── map_generator.py          # Folium interactive map generator
├── .env.example                  # Template for API keys
├── .gitignore                    # Prevents leaking keys or temporary cache files
├── requirements.txt              # Pinned Python package dependencies
├── job_scraper.py                # Main CLI entrypoint
├── README.md                     # Documentation
├── jobs.csv                      # Tracked job postings (CSV)
├── jobs.xlsx                     # Formatted job listings (Excel)
└── map.html                      # Interactive Folium map
```
