# Assistant Professor Job Board Aggregator & Summarizer

An automated, daily web aggregator designed to track, evaluate, and visualize Assistant Professor job openings in **Transportation Engineering, Urban Planning, and Mobility Systems** (or any academic discipline via custom CV) across the **United States, Canada, Europe, Hong Kong, Singapore, Japan, South Korea, and Taiwan**.

It collects postings from **5 major academic job platforms** ([AcademicKeys](https://engineering.academickeys.com/seeker_search.php), [HigherEdJobs](https://www.higheredjobs.com/faculty/), [The Chronicle of Higher Education](https://jobs.chronicle.com/), [Jobs.ac.uk](https://www.jobs.ac.uk/), and [LinkedIn Jobs](https://www.linkedin.com/jobs/)), uses **Google Gemini** to extract structured metadata, calculate a **1–10 Candidate Fit Score**, and generate concise summaries, exports to **Excel (`.xlsx`)**, **Google Sheets**, and **CSV**, and plots hiring institutions on an **interactive geographic map (`map.html` / `index.html`)**.

---

## Key Features

- **Multi-Site Scraping (5 Platforms)**:
  - [AcademicKeys Engineering](https://engineering.academickeys.com/seeker_search.php)
  - [HigherEdJobs Faculty](https://www.higheredjobs.com/faculty/)
  - [The Chronicle of Higher Education Jobs](https://jobs.chronicle.com/)
  - [Jobs.ac.uk](https://www.jobs.ac.uk/) (United Kingdom, Europe, and Global)
  - **LinkedIn Jobs** (via public guest search API — no account login or authentication needed)
- **Dynamic Candidate CV Fit Evaluation (1–10 Scoring)**:
  - Dynamically extracts your research profile, target departments, and subdiscipline boundaries directly from **`CV.pdf`**.
  - Assigns a calibrated **1 to 10 Fit Score** and a concise **Fit Reason** explaining why each job is a match or mismatch.
  - Highly portable: simply replace `CV.pdf` with your own CV to evaluate positions in any field (e.g. Computer Science, Economics, Mechanical Engineering).
- **Weak Relevance Screening Filter**:
  - Automatically screens out non-faculty positions (senior-only, adjuncts, postdocs) and irrelevant subfields (e.g. positions without transportation/mobility focus, water resources, structures, or non-engineering disciplines).
  - Screened-out postings are excluded from active outputs and cached in `.cache/filtered_jobs.json` to avoid redundant LLM calls.
  - Configurable sensitivity via `--min-fit-score` (default: `3`).
- **User-Editable Evaluation Prompt (`eval_prompt.txt`)**:
  - Fine-tune Gemini's evaluation criteria, target geographic scope, or degree requirements simply by editing [eval_prompt.txt](eval_prompt.txt).
- **Interactive Map & GitHub Pages Dashboard (`map.html` & `index.html`)**:
  - Built with Folium, Leaflet, and high-reliability Esri basemaps.
  - University markers clustered and color-coded by fit score (dark green for 9–10, green for 7–8, orange for 5–6, red for 3–4).
  - Interactive popup cards showing department, salary, application deadline, AI summary, and direct apply link.
  - Filter pins by deadline urgency (Upcoming <30 days, Next 30–60 days, Later, Open until filled).
  - **GitHub Pages Ready**: `index.html` mirrors the map for instant, free web hosting on GitHub Pages.
- **Dual Export & Real-Time Sync**:
  - **Excel (`jobs.xlsx`)**: Cleanly formatted spreadsheet with colored headers, fit score highlighting, and clickable application links.
  - **Google Sheets**: Live cloud synchronization to your personal Google Sheet via a Service Account.
  - **CSV (`jobs.csv`)**: Tabular format for local record-keeping and data science workflows.
- **Smart Deduplication & Daily Tracking**:
  - Deduplicates positions across multiple job boards by normalized URL and `(institution, department)`.
  - Tracks `Date Added`, `Last Verified`, and `Status` (`Active` / `Closed`).

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

### 1. Google Gemini API Key (**Highly Encouraged**)

A Google Gemini API key is **strongly recommended** to enable the core intelligence of this aggregator.

> [!IMPORTANT]
> **Free Tier Available**: Google AI Studio provides **free API keys** with generous limits (15 requests/minute and 1,000,000 tokens/minute for Flash models), requiring **no credit card**.

#### Limitations of Running Without a Gemini API Key:
The aggregator is designed to degrade gracefully if `GEMINI_API_KEY` is not provided, but running without it imposes significant limitations:
- **No 1–10 Fit Scores**: Fit scores will **not be computed** (`Fit Score` and `Fit Reason` remain empty / `None`).
- **No Relevance Screening**: The AI-powered screening filter is disabled; irrelevant positions, non-faculty roles, or out-of-scope fields will not be filtered out automatically.
- **Fallback Descriptions**: Positions will not receive synthesized 1-sentence summaries; the summary defaults to the first 200 characters of raw scraped HTML text.
- **Neutral Map Markers**: On `map.html`, all pins display a uniform grey marker (`Fit: N/A`) rather than color-coded candidate match tiers.
- **No CV Parsing**: `CV.pdf` cannot be analyzed dynamically.

#### How to Set Up Your Free Key:
1. Visit [Google AI Studio](https://aistudio.google.com/).
2. Sign in with your Google account and click **Get API key** &rarr; **Create API key**.
3. Copy [.env.example](.env.example) to `.env`:
   ```bash
   cp .env.example .env
   ```
4. Open `.env` and paste your key:
   ```env
   GEMINI_API_KEY=your_gemini_api_key_here
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
4. The workflow will automatically run every day at `06:00 UTC`, or you can trigger it manually anytime via the **Actions** tab by clicking **Run workflow**.

---

## Running the Scraper

### Basic Run
Run with default settings (scrapes Transportation and Mobility queries across all 5 platforms):
```bash
python job_scraper.py
```

### Advanced Options

```bash
# Custom search query (comma-separated)
python job_scraper.py --query "Assistant Professor Transportation Engineering, Assistant Professor Mobility"

# Adjust max listings fetched per source (default: 20)
python job_scraper.py --max-per-source 30

# Scrape specific sources only (academickeys, higheredjobs, chronicle, linkedin, jobsacuk)
python job_scraper.py --sources higheredjobs,linkedin,jobsacuk

# Specify a custom candidate CV (default: CV.pdf)
python job_scraper.py --cv-path path/to/my_cv.pdf

# Adjust minimum fit score threshold for active listings (1-10, default: 3)
python job_scraper.py --min-fit-score 4

# Specify a custom evaluation prompt template (default: eval_prompt.txt)
python job_scraper.py --eval-prompt eval_prompt.txt

# Re-evaluate all previously tracked jobs with an updated prompt or CV
python job_scraper.py --re-evaluate

# Include screened-out (filtered) positions in CSV/Excel/Map exports
python job_scraper.py --include-filtered

# Choose Gemini model (default: gemini-3.6-flash or gemini-3.7-flash)
python job_scraper.py --model gemini-3.7-flash

# Fast dry run without calling Gemini LLM
python job_scraper.py --skip-gemini

# Skip Google Sheets sync
python job_scraper.py --skip-sheets
```

---

## Output Files

Once the script completes, the following files are updated in the project directory:

| File | Description |
| :--- | :--- |
| `jobs.xlsx` | Beautifully styled Excel spreadsheet with auto-width columns, fit score badges, and clickable links. |
| `jobs.csv` | Standard comma-separated values file containing all tracked positions and historical metadata. |
| `map.html` | Standalone interactive map showing all hiring universities. Double-click or open in any web browser. |
| `index.html` | Mirror of `map.html` formatted for hosting the interactive map directly on **GitHub Pages**. |
| `.cache/geocache.json` | Local cache of university coordinates to avoid repeated geocoding requests. |
| `.cache/filtered_jobs.json` | Local cache of positions screened out by the relevance filter. |

---

## File Structure

```
AssistantProfessorJobScraper/
├── .github/
│   └── workflows/
│       └── daily_scrape.yml        # Daily automated GitHub Actions workflow
├── scrapers/
│   ├── __init__.py
│   ├── base.py                     # BaseScraper & JobPosting data models
│   ├── academickeys.py             # AcademicKeys Engineering scraper
│   ├── higheredjobs.py             # HigherEdJobs Faculty scraper
│   ├── chronicle.py                # The Chronicle of Higher Education scraper
│   ├── linkedin.py                 # LinkedIn Public Guest search scraper
│   └── jobsacuk.py                 # Jobs.ac.uk international faculty scraper
├── processor/
│   ├── __init__.py
│   ├── cv_matcher.py               # CV PDF parsing & candidate profile extraction
│   ├── deduplicator.py             # Historical tracking & duplicate prevention
│   ├── gemini_extractor.py         # Google Gemini structured parser & candidate fit scoring
│   ├── geocoder.py                 # University geocoding with local caching
│   ├── exporter.py                 # CSV and styled Excel (.xlsx) generator
│   ├── google_sheets.py            # Google Sheets cloud synchronizer
│   └── map_generator.py            # Folium interactive map & index.html generator
├── tests/
│   ├── __init__.py
│   ├── test_components.py          # Comprehensive component unit tests
│   └── test_deadline_and_status.py # Deadline parsing and status unit tests
├── .env.example                    # Template for environment variables & API keys
├── .gitignore                      # Protects secrets (.env, credentials.json, .cache/)
├── requirements.txt                # Python package dependencies
├── eval_prompt.txt                 # User-editable Gemini evaluation prompt template
├── CV.pdf                          # Candidate CV for automated profile matching
├── job_scraper.py                  # Main CLI entrypoint
├── README.md                       # Project documentation
├── LICENSE                         # MIT License
├── jobs.csv                        # Tracked job postings (CSV)
├── jobs.xlsx                       # Formatted job listings (Excel)
├── map.html                        # Interactive Folium map
└── index.html                      # GitHub Pages interactive web dashboard mirror
```
