# FINN.no Job Scanner

## Project Overview
This is an automated job scanning tool that scrapes FINN.no (Norwegian job board) daily and uses Claude AI to score job listings against the user's professional profile.

## User Profile
- Masters degree in Finance
- 20 years as Business Manager in Maritime industry
- Passion for digitalization, web development, IT security
- Location: Ålesund / Møre og Romsdal, Norway

## Architecture
```
job_scanner/
├── job_scanner.py      # Main script - scrapes FINN.no, calls Claude API, generates report
├── config.py           # User configuration - API key, profile, search URL, email settings
├── requirements.txt    # Python dependencies: anthropic, requests, beautifulsoup4
└── README.md           # Setup and scheduling instructions
```

## Key Components

### job_scanner.py
- `fetch_finn_search_results()` - Scrapes FINN.no search page for job listings
- `fetch_job_details()` - Fetches full description from individual job pages
- `analyze_job_with_claude()` - Calls Claude API to score job (0-100) with reasoning
- `generate_summary_report()` - Creates markdown report with scored table
- `send_email_report()` - Optional email delivery
- `main()` - Orchestrates the full pipeline

### config.py
- `ANTHROPIC_API_KEY` - User must add their key
- `USER_PROFILE` - Pre-filled based on conversation, user can customize
- `FINN_SEARCH_URL` - FINN.no search URL with filters
- `EMAIL_CONFIG` - Optional SMTP settings for email notifications
- `MINIMUM_SCORE_TO_INCLUDE` - Threshold for report inclusion (default: 30)
- `MAX_JOBS_TO_ANALYZE` - Limit per run (default: 50)

## Running the Project
```bash
# Install dependencies
pip install -r requirements.txt

# Edit config.py with API key
# Then run:
python job_scanner.py
```

## Scheduling
- **Linux/Mac**: cron job at 8 AM daily
- **Windows**: Task Scheduler
- **Cloud**: GitHub Actions (workflow in README)

## Output
Generates `job_report_YYYYMMDD.md` with:
- Scored table of matching jobs
- Detailed analysis for each job above threshold
- Summary statistics

## Common Tasks
- **Change search criteria**: Edit `FINN_SEARCH_URL` in config.py
- **Adjust scoring threshold**: Change `MINIMUM_SCORE_TO_INCLUDE` in config.py
- **Enable email**: Set `EMAIL_CONFIG['enabled'] = True` and add SMTP details
- **Modify profile**: Edit `USER_PROFILE` in config.py

## API Usage
- Uses Claude Sonnet for analysis (~$0.01 per job)
- Rate limited with 2-second delay between jobs
- Estimated cost: ~$15/month for 50 jobs/day
