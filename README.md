# FINN.no Job Scanner with AI Assessment

Automatically scan FINN.no job listings daily and get AI-powered match scores based on your professional profile.

## Features

- 🔍 Scrapes FINN.no job listings based on your search criteria
- 🤖 Uses Claude AI to analyze each job against your profile
- 📊 Generates a scored summary table (0-100 match score)
- 📧 Optional email notifications
- ⏰ Easy to schedule for daily automated runs

## Quick Start

### 1. Install Dependencies

```bash
# Create a virtual environment (recommended)
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install required packages
pip install -r requirements.txt
```

### 2. Get Your Anthropic API Key

1. Go to [console.anthropic.com](https://console.anthropic.com/)
2. Create an account or sign in
3. Go to API Keys and create a new key
4. Copy the key (starts with `sk-ant-...`)

### 3. Configure Your Settings

Edit `config.py`:

```python
# Add your API key
ANTHROPIC_API_KEY = "sk-ant-your-key-here"

# Customize your profile
USER_PROFILE = """
## Education
- Your degree and field

## Work Experience  
- Your years of experience
- Your industry background

## Skills & Interests
- Key skills
- What you're looking for
"""

# Set your FINN.no search URL
# Go to finn.no/job, apply your filters, copy the URL
FINN_SEARCH_URL = "https://www.finn.no/job/search?location=0.20001&published=1"
```

### 4. Run the Scanner

```bash
python job_scanner.py
```

The report will be saved as `job_report_YYYYMMDD.md` in the same directory.

---

## Scheduling Daily Runs

### Option A: Linux/Mac (cron)

```bash
# Open crontab editor
crontab -e

# Add this line to run at 8:00 AM every day
0 8 * * * cd /path/to/job_scanner && /path/to/venv/bin/python job_scanner.py >> /path/to/job_scanner/cron.log 2>&1
```

**Find your paths:**
```bash
# Get the full path to your script
pwd

# Get the full path to Python in your venv
which python
```

### Option B: Windows (Task Scheduler)

1. Open **Task Scheduler** (search in Start menu)
2. Click **Create Basic Task**
3. Name it "Daily Job Scanner"
4. Set trigger: **Daily** at your preferred time
5. Action: **Start a program**
   - Program: `C:\path\to\venv\Scripts\python.exe`
   - Arguments: `C:\path\to\job_scanner\job_scanner.py`
   - Start in: `C:\path\to\job_scanner`
6. Finish

### Option C: Cloud Hosting (Free/Cheap)

**Railway.app (Recommended - Simple)**
1. Create account at [railway.app](https://railway.app)
2. Create new project from GitHub repo
3. Add environment variable: `ANTHROPIC_API_KEY`
4. Add a cron job using Railway's scheduling

**GitHub Actions (Free)**
Create `.github/workflows/scan.yml`:

```yaml
name: Daily Job Scan

on:
  schedule:
    - cron: '0 7 * * *'  # 7 AM UTC daily
  workflow_dispatch:  # Allow manual runs

jobs:
  scan:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      
      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'
          
      - name: Install dependencies
        run: pip install -r requirements.txt
        
      - name: Run scanner
        env:
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
        run: python job_scanner.py
        
      - name: Upload report
        uses: actions/upload-artifact@v4
        with:
          name: job-report
          path: job_report_*.md
```

Add your API key as a GitHub secret: Settings → Secrets → Actions → New secret

---

## Email Notifications

To receive reports by email, edit `config.py`:

```python
EMAIL_CONFIG = {
    'enabled': True,
    'smtp_server': 'smtp.gmail.com',
    'smtp_port': 587,
    'username': 'your-email@gmail.com',
    'password': 'your-app-password',  # NOT your regular password!
    'from_email': 'your-email@gmail.com',
    'to_email': 'your-email@gmail.com',
}
```

### Gmail Setup
1. Enable 2-factor authentication on your Google account
2. Go to [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords)
3. Create an App Password for "Mail"
4. Use that 16-character password in the config

---

## Customizing Your Search

### Search URL Examples

```python
# All of Norway, posted today
FINN_SEARCH_URL = "https://www.finn.no/job/search?location=0.20001&published=1"

# Møre og Romsdal region only
FINN_SEARCH_URL = "https://www.finn.no/job/search?location=1.20001.20015&published=1"

# Maritime industry
FINN_SEARCH_URL = "https://www.finn.no/job/search?industry=69&published=1"

# IT industry
FINN_SEARCH_URL = "https://www.finn.no/job/search?industry=65&published=1"

# Multiple filters (Maritime + Møre og Romsdal)
FINN_SEARCH_URL = "https://www.finn.no/job/search?industry=69&location=1.20001.20015&published=1"

# Saved search (your personalized filters)
FINN_SEARCH_URL = "https://www.finn.no/job/search?stored-id=YOUR_SAVED_SEARCH_ID&published=1"
```

**Pro tip:** Go to finn.no/job, set all your filters, then copy the URL from your browser.

---

## Cost Estimation

**Anthropic API costs:**
- Claude Sonnet: ~$0.003 per 1K input tokens, ~$0.015 per 1K output tokens
- Each job analysis: ~2K input + 0.3K output ≈ $0.01
- 50 jobs/day × 30 days = $15/month

**Tips to reduce costs:**
- Set `MAX_JOBS_TO_ANALYZE` lower
- Use more specific search filters
- Increase `MINIMUM_SCORE_TO_INCLUDE` to skip low matches

---

## Troubleshooting

### "No job listings found"
- Check if your FINN_SEARCH_URL is valid
- FINN.no may have updated their HTML structure
- Try running with a simpler search URL first

### API Errors
- Verify your ANTHROPIC_API_KEY is correct
- Check your API credit balance at console.anthropic.com
- Ensure you have billing set up

### Email not sending
- Use App Password, not regular password for Gmail
- Check spam folder
- Verify SMTP settings for your email provider

### Cron not running
- Check cron logs: `grep CRON /var/log/syslog`
- Ensure paths are absolute, not relative
- Test the command manually first

---

## File Structure

```
job_scanner/
├── job_scanner.py      # Main script
├── config.py           # Your configuration
├── requirements.txt    # Python dependencies
├── README.md           # This file
└── job_report_*.md     # Generated reports
```

---

## License

MIT License - Feel free to modify and use as you wish.

---

## Support

If you have issues or questions:
1. Check the Troubleshooting section above
2. Verify your config.py settings
3. Run the script manually to see error messages
