"""
Configuration file for FINN.no Job Scanner
Edit this file to customize your profile and search settings.
"""

import os

# =============================================================================
# ANTHROPIC API KEY
# Set via environment variable: export ANTHROPIC_API_KEY="sk-ant-..."
# Get your API key from: https://console.anthropic.com/
# =============================================================================
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")


# =============================================================================
# YOUR PROFESSIONAL PROFILE
# Edit this to match your background, skills, and interests
# =============================================================================
USER_PROFILE = """
## Education
- Masters degree in Finance

## Work Experience
- 20 years as a Business Manager in the Maritime industry
- Experience with operations, strategy, and business development

## Skills & Interests
- Strong financial analysis and budgeting skills
- Business process optimization
- Passion for digitalization and digital transformation
- Interest in web development
- Interest in IT security and cybersecurity

## What I'm Looking For
- Senior management or leadership roles
- Roles that combine maritime/business expertise with digital transformation
- Operations, finance, or business development positions
- Opportunities to drive digitalization initiatives

## Location Preferences
- Based in Møre og Romsdal region (Ålesund area)
- Open to remote/hybrid work arrangements
- May consider relocation for exceptional opportunities
"""


# =============================================================================
# FINN.NO SEARCH URL
# Go to finn.no/job, set your filters, and copy the URL
# Example filters: location, industry, job type, etc.
# =============================================================================
FINN_SEARCH_URL = "https://www.finn.no/job/search?location=0.20001&published=1"

# Alternative URLs you might want to use:
# Møre og Romsdal only:
# FINN_SEARCH_URL = "https://www.finn.no/job/search?location=1.20001.20015&published=1"
#
# Maritime industry:
# FINN_SEARCH_URL = "https://www.finn.no/job/search?industry=69&published=1"
#
# IT jobs:
# FINN_SEARCH_URL = "https://www.finn.no/job/search?industry=65&published=1"
#
# Leadership positions:
# FINN_SEARCH_URL = "https://www.finn.no/job/search?occupation=OCCUPATION_MANAGEMENT&published=1"


# =============================================================================
# SCORING SETTINGS
# =============================================================================
# Only include jobs with score >= this value in the report
MINIMUM_SCORE_TO_INCLUDE = 30

# Maximum number of jobs to analyze per run (to manage API costs)
# Each job uses approximately 1,000-2,000 tokens
MAX_JOBS_TO_ANALYZE = 50


# =============================================================================
# EMAIL CONFIGURATION (Optional)
# Set enabled=True and fill in details to receive email reports
# =============================================================================
EMAIL_CONFIG = {
    'enabled': False,  # Set to True to enable email notifications
    
    # Gmail example (you'll need an App Password, not your regular password)
    # See: https://support.google.com/accounts/answer/185833
    'smtp_server': 'smtp.gmail.com',
    'smtp_port': 587,
    'username': 'your-email@gmail.com',
    'password': 'your-app-password',  # Use App Password, not regular password
    'from_email': 'your-email@gmail.com',
    'to_email': 'your-email@gmail.com',
    
    # For other email providers:
    # Outlook: smtp_server='smtp-mail.outlook.com', smtp_port=587
    # Yahoo: smtp_server='smtp.mail.yahoo.com', smtp_port=587
}
