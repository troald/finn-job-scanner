"""
Configuration file for FINN.no Job Scanner
Edit this file to customize your search profiles and settings.
"""

import os

# =============================================================================
# ANTHROPIC API KEY
# Set via environment variable: export ANTHROPIC_API_KEY="sk-ant-..."
# Get your API key from: https://console.anthropic.com/
# =============================================================================
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")


# =============================================================================
# SEARCH PROFILES
# Define multiple search profiles, each with its own URL and criteria.
# Each profile will be scanned separately and results tagged accordingly.
# =============================================================================
SEARCH_PROFILES = {
    # Example 1: Maritime Management roles
    "maritime-management": {
        "name": "Maritime Management",
        "enabled": True,
        "search_url": "https://www.finn.no/job/search?location=0.20001&occupation=OCCUPATION_MANAGEMENT&published=1",
        "minimum_score": 30,
        "max_jobs": 25,
        "profile": """
## Target Role
Senior management or leadership positions in the maritime industry.

## Ideal Candidate Background
- Masters degree in Finance or Business
- 15+ years experience in maritime industry
- Business management, operations, or strategy roles
- Experience with P&L responsibility

## Key Skills to Match
- Maritime industry knowledge (shipping, offshore, maritime services)
- Financial management and budgeting
- Business development and strategy
- Team leadership and organizational development
- International business experience

## Location
- Preference for Møre og Romsdal / Ålesund area
- Open to other Norwegian coastal cities
- Remote/hybrid arrangements acceptable
"""
    },

    # Example 2: Digital Transformation / IT roles
    "digital-transformation": {
        "name": "Digital & IT",
        "enabled": True,
        "search_url": "https://www.finn.no/job/search?location=0.20001&industry=65&published=1",
        "minimum_score": 30,
        "max_jobs": 25,
        "profile": """
## Target Role
Roles combining business expertise with digital transformation, IT management, or technology leadership.

## Ideal Candidate Background
- Business background with strong interest in technology
- Experience driving digitalization initiatives
- Understanding of both business and technical perspectives

## Key Skills to Match
- Digital transformation and process optimization
- IT strategy and implementation
- Web development or software projects
- IT security and cybersecurity awareness
- Change management for digital initiatives
- Data analysis and business intelligence

## Location
- Preference for Møre og Romsdal / Ålesund area
- Strong interest in remote/hybrid positions
- Open to relocation for right opportunity
"""
    },

    # Example 3: Finance roles
    "finance": {
        "name": "Finance",
        "enabled": False,  # Disabled by default - enable if needed
        "search_url": "https://www.finn.no/job/search?location=0.20001&occupation=OCCUPATION_FINANCE&published=1",
        "minimum_score": 40,
        "max_jobs": 20,
        "profile": """
## Target Role
Senior finance positions - CFO, Finance Director, Finance Manager.

## Ideal Candidate Background
- Masters degree in Finance
- 10+ years in financial management
- Experience with corporate finance, reporting, budgeting

## Key Skills to Match
- Financial planning and analysis
- Budgeting and forecasting
- Financial reporting and compliance
- ERP systems and financial software
- Team management

## Location
- Møre og Romsdal preferred
- Open to remote work
"""
    },
}


# =============================================================================
# GLOBAL SETTINGS
# =============================================================================
# Default minimum score if not specified per profile
DEFAULT_MINIMUM_SCORE = 30

# Default max jobs per profile if not specified
DEFAULT_MAX_JOBS = 50


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


# =============================================================================
# LEGACY SUPPORT (deprecated - use SEARCH_PROFILES instead)
# These are kept for backward compatibility but will be ignored if
# SEARCH_PROFILES is defined and non-empty.
# =============================================================================
USER_PROFILE = ""
FINN_SEARCH_URL = ""
MINIMUM_SCORE_TO_INCLUDE = DEFAULT_MINIMUM_SCORE
MAX_JOBS_TO_ANALYZE = DEFAULT_MAX_JOBS
