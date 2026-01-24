#!/usr/bin/env python3
"""
FINN.no Job Scanner with AI Assessment
Automatically scans job listings and scores them against multiple search profiles using Claude API.
"""

import os
import json
import subprocess
import glob
import requests
from datetime import datetime, timedelta
from bs4 import BeautifulSoup
import anthropic
from dataclasses import dataclass, field
from typing import Optional
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import time
import re
from pathlib import Path

# File paths
BASE_DIR = Path(__file__).parent
ANALYZED_JOBS_FILE = BASE_DIR / "analyzed_jobs.json"
AWS_CONFIG_FILE = BASE_DIR / "aws_dashboard_config.json"

# Load configuration
from config import (
    ANTHROPIC_API_KEY,
    SEARCH_PROFILES,
    EMAIL_CONFIG,
    DEFAULT_MINIMUM_SCORE,
    DEFAULT_MAX_JOBS,
)


def load_analyzed_jobs() -> dict:
    """Load previously analyzed jobs from JSON file.

    Structure: {
        "profile_id": {
            "finn_code": { job_data }
        }
    }
    """
    if ANALYZED_JOBS_FILE.exists():
        try:
            with open(ANALYZED_JOBS_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                # Handle legacy format (flat structure without profiles)
                if data and not any(isinstance(v, dict) and 'title' not in v for v in data.values()):
                    # Old format - migrate to new structure under "default" profile
                    return {"_legacy": data}
                return data
        except (json.JSONDecodeError, IOError) as e:
            print(f"Warning: Could not load analyzed jobs history: {e}")
    return {}


def save_analyzed_jobs(analyzed: dict):
    """Save analyzed jobs to JSON file"""
    with open(ANALYZED_JOBS_FILE, 'w', encoding='utf-8') as f:
        json.dump(analyzed, f, indent=2, ensure_ascii=False)


def load_aws_config() -> dict:
    """Load AWS dashboard configuration if it exists."""
    if AWS_CONFIG_FILE.exists():
        try:
            with open(AWS_CONFIG_FILE, 'r') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    return {}


def upload_to_s3(local_path: str, s3_key: str, bucket: str, content_type: str = None):
    """Upload a file to S3."""
    cmd = ["aws", "s3", "cp", local_path, f"s3://{bucket}/{s3_key}"]
    if content_type:
        cmd.extend(["--content-type", content_type])
    result = subprocess.run(cmd, capture_output=True, text=True)
    return result.returncode == 0


def sync_to_cloud(profiles: dict):
    """Sync data to AWS S3 for the cloud dashboard."""
    aws_config = load_aws_config()
    if not aws_config:
        return  # Cloud dashboard not configured

    bucket = aws_config.get('bucket_name')
    if not bucket:
        return

    print("\nSyncing to cloud dashboard...")

    # Upload analyzed_jobs.json
    if ANALYZED_JOBS_FILE.exists():
        if upload_to_s3(str(ANALYZED_JOBS_FILE), "data/analyzed_jobs.json", bucket, "application/json"):
            print("  Uploaded analyzed_jobs.json")

    # Upload profiles configuration (without the full profile text, just metadata)
    profiles_meta = {
        pid: {"name": p.get("name", pid), "enabled": p.get("enabled", True)}
        for pid, p in profiles.items()
    }
    profiles_path = BASE_DIR / "profiles_meta.json"
    with open(profiles_path, 'w') as f:
        json.dump(profiles_meta, f, indent=2)
    if upload_to_s3(str(profiles_path), "data/profiles.json", bucket, "application/json"):
        print("  Uploaded profiles.json")
    profiles_path.unlink(missing_ok=True)

    # Find and upload all reports
    reports = []
    for report_path in glob.glob(str(BASE_DIR / "job_report_*.md")):
        filename = os.path.basename(report_path)
        date_str = filename.replace('job_report_', '').replace('.md', '')
        try:
            date = datetime.strptime(date_str, '%Y%m%d')
            reports.append({
                'filename': filename,
                'date': date.strftime('%Y-%m-%d'),
                'date_display': date.strftime('%B %d, %Y'),
            })
            # Upload report
            if upload_to_s3(report_path, f"data/reports/{filename}", bucket, "text/markdown"):
                print(f"  Uploaded {filename}")
        except ValueError:
            continue

    # Sort reports by date descending and upload index
    reports.sort(key=lambda x: x['date'], reverse=True)
    reports_index_path = BASE_DIR / "reports_index.json"
    with open(reports_index_path, 'w') as f:
        json.dump(reports, f, indent=2)

    if upload_to_s3(str(reports_index_path), "data/reports_index.json", bucket, "application/json"):
        print("  Uploaded reports_index.json")

    # Clean up temp file
    reports_index_path.unlink(missing_ok=True)

    print(f"  Dashboard: {aws_config.get('cloudfront_url', 'N/A')}")


@dataclass
class JobListing:
    """Represents a single job listing from FINN.no"""
    title: str
    company: str
    location: str
    url: str
    finn_code: str
    profile_id: str = ""
    profile_name: str = ""
    description: Optional[str] = None
    score: Optional[int] = None
    reasoning: Optional[str] = None


def fetch_finn_search_results(search_url: str, max_jobs: int) -> list[dict]:
    """Fetch job listings from FINN.no search page"""
    print(f"  Fetching from: {search_url[:80]}...")

    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.5',
    }

    response = requests.get(search_url, headers=headers, timeout=30)
    response.raise_for_status()

    soup = BeautifulSoup(response.text, 'html.parser')
    jobs = []

    # Find job listing links - FINN uses various formats
    job_links = soup.find_all('a', href=re.compile(r'/job/ad/\d+'))

    seen_codes = set()
    for link in job_links:
        href = link.get('href', '')
        match = re.search(r'/job/ad/(\d+)', href)
        if match:
            finn_code = match.group(1)
            if finn_code in seen_codes:
                continue
            seen_codes.add(finn_code)

            # Try to extract title from the link
            title = link.get_text(strip=True) or "Unknown Title"

            # Build full URL
            full_url = f"https://www.finn.no/job/ad/{finn_code}"

            jobs.append({
                'finn_code': finn_code,
                'url': full_url,
                'title': title[:100],
            })

    print(f"  Found {len(jobs)} job listings")
    return jobs[:max_jobs]


def fetch_job_details(job_url: str) -> Optional[str]:
    """Fetch full job description from a FINN.no job page"""
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        }

        response = requests.get(job_url, headers=headers, timeout=30)
        response.raise_for_status()

        soup = BeautifulSoup(response.text, 'html.parser')

        # Extract key information
        details = []

        # Get the page title
        title_elem = soup.find('h1')
        if title_elem:
            details.append(f"Title: {title_elem.get_text(strip=True)}")

        # Get company name
        company_elem = soup.find('a', href=re.compile(r'/job/employer/company/'))
        if not company_elem:
            company_elem = soup.find('a', href=re.compile(r'/job/search\?orgId='))
        if company_elem:
            details.append(f"Company: {company_elem.get_text(strip=True)}")

        # Get location
        location_elem = soup.find('a', href=re.compile(r'/job/search\?location='))
        if location_elem:
            details.append(f"Location: {location_elem.get_text(strip=True)}")

        # Get job description
        main_content = soup.find('main') or soup.find('article') or soup

        # Remove script and style elements
        for script in main_content(["script", "style", "nav", "footer", "header"]):
            script.decompose()

        # Get text content
        text = main_content.get_text(separator='\n', strip=True)

        # Clean up excessive whitespace
        lines = [line.strip() for line in text.split('\n') if line.strip()]
        text = '\n'.join(lines)

        # Truncate if too long
        if len(text) > 4000:
            text = text[:4000] + "..."

        details.append(f"\nJob Description:\n{text}")

        return '\n'.join(details)

    except Exception as e:
        print(f"    Error fetching job details: {e}")
        return None


def analyze_job_with_claude(job_details: str, profile: str) -> tuple[int, str]:
    """Use Claude API to analyze job fit and return score + reasoning"""

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    prompt = f"""Analyze this job listing against the candidate's profile and provide a match score from 0-100.

## Candidate Profile:
{profile}

## Job Listing:
{job_details}

## Instructions:
1. Score the job from 0-100 based on how well it matches the candidate's:
   - Target role and ideal background
   - Required skills and experience
   - Location preferences

2. A score of:
   - 80-100: Excellent match, should definitely apply
   - 60-79: Good match, worth considering
   - 40-59: Partial match, some relevant elements
   - 20-39: Poor match, significant gaps
   - 0-19: No match, wrong field/level entirely

3. Provide brief reasoning (2-3 sentences max)

## Response Format (JSON only, no other text):
{{"score": <number>, "reasoning": "<brief explanation>"}}
"""

    try:
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=300,
            messages=[{"role": "user", "content": prompt}]
        )

        result_text = response.content[0].text.strip()

        # Parse JSON response
        if "```" in result_text:
            result_text = re.search(r'```(?:json)?\s*({.*?})\s*```', result_text, re.DOTALL)
            if result_text:
                result_text = result_text.group(1)

        result = json.loads(result_text)
        return result['score'], result['reasoning']

    except Exception as e:
        print(f"    Error analyzing job: {e}")
        return 0, f"Error during analysis: {str(e)}"


def generate_summary_report(all_jobs: list[JobListing], profiles: dict) -> str:
    """Generate the final summary report with all profiles"""

    today = datetime.now().strftime("%A, %B %d, %Y")

    report = f"""# Daily Job Match Report
**Date:** {today}

---

"""

    # Group jobs by profile
    jobs_by_profile = {}
    for job in all_jobs:
        if job.profile_id not in jobs_by_profile:
            jobs_by_profile[job.profile_id] = []
        jobs_by_profile[job.profile_id].append(job)

    # Generate section for each profile
    for profile_id, profile_config in profiles.items():
        if not profile_config.get('enabled', True):
            continue

        profile_name = profile_config.get('name', profile_id)
        min_score = profile_config.get('minimum_score', DEFAULT_MINIMUM_SCORE)
        jobs = jobs_by_profile.get(profile_id, [])

        report += f"""## {profile_name}

| Score | Position | Company | Location | Link |
|-------|----------|---------|----------|------|
"""

        # Sort jobs by score descending
        sorted_jobs = sorted(jobs, key=lambda x: x.score or 0, reverse=True)

        matching_jobs = [j for j in sorted_jobs if j.score is not None and j.score >= min_score]

        if matching_jobs:
            for job in matching_jobs:
                report += f"| **{job.score}** | {job.title[:40]}{'...' if len(job.title) > 40 else ''} | {job.company or 'N/A'} | {job.location or 'N/A'} | [View]({job.url}) |\n"
        else:
            report += "| - | No matching jobs found | - | - | - |\n"

        report += "\n"

        # Detailed analysis for this profile
        if matching_jobs:
            report += "### Detailed Analysis\n\n"
            for job in matching_jobs:
                report += f"""**{job.title}**
Company: {job.company or 'N/A'} | Location: {job.location or 'N/A'} | Score: {job.score}/100
{job.reasoning}
[View on FINN]({job.url})

---

"""

        # Profile stats
        total = len(jobs)
        high = len([j for j in jobs if j.score and j.score >= 70])
        medium = len([j for j in jobs if j.score and 40 <= j.score < 70])

        report += f"""**Stats:** {total} analyzed | {high} high match | {medium} medium match

---

"""

    report += "*Report generated automatically by Job Scanner*\n"

    return report


def send_email_report(report: str, html_report: str = None):
    """Send the report via email"""
    if not EMAIL_CONFIG.get('enabled'):
        return

    msg = MIMEMultipart('alternative')
    msg['Subject'] = f"Daily Job Match Report - {datetime.now().strftime('%Y-%m-%d')}"
    msg['From'] = EMAIL_CONFIG['from_email']
    msg['To'] = EMAIL_CONFIG['to_email']

    msg.attach(MIMEText(report, 'plain'))

    if html_report:
        msg.attach(MIMEText(html_report, 'html'))

    try:
        with smtplib.SMTP(EMAIL_CONFIG['smtp_server'], EMAIL_CONFIG['smtp_port']) as server:
            server.starttls()
            server.login(EMAIL_CONFIG['username'], EMAIL_CONFIG['password'])
            server.send_message(msg)
        print("Email report sent successfully!")
    except Exception as e:
        print(f"Failed to send email: {e}")


def save_report_to_file(report: str, filename: str = None):
    """Save the report to a markdown file"""
    if filename is None:
        filename = f"job_report_{datetime.now().strftime('%Y%m%d')}.md"

    filepath = BASE_DIR / filename
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(report)

    print(f"Report saved to {filename}")
    return filename


def process_profile(profile_id: str, profile_config: dict, analyzed_history: dict) -> list[JobListing]:
    """Process a single search profile and return analyzed jobs."""

    profile_name = profile_config.get('name', profile_id)
    search_url = profile_config.get('search_url', '')
    profile_text = profile_config.get('profile', '')
    max_jobs = profile_config.get('max_jobs', DEFAULT_MAX_JOBS)
    min_score = profile_config.get('minimum_score', DEFAULT_MINIMUM_SCORE)

    print(f"\n{'='*60}")
    print(f"Profile: {profile_name}")
    print(f"{'='*60}")

    if not search_url:
        print("  No search URL configured, skipping.")
        return []

    # Initialize profile history if needed
    if profile_id not in analyzed_history:
        analyzed_history[profile_id] = {}

    profile_history = analyzed_history[profile_id]

    # Fetch job listings
    try:
        job_listings = fetch_finn_search_results(search_url, max_jobs)
    except Exception as e:
        print(f"  Error fetching jobs: {e}")
        return []

    if not job_listings:
        print("  No job listings found.")
        return []

    # Filter out already analyzed jobs
    new_jobs = [j for j in job_listings if j['finn_code'] not in profile_history]
    skipped_count = len(job_listings) - len(new_jobs)

    if skipped_count > 0:
        print(f"  Skipping {skipped_count} previously analyzed jobs")

    if not new_jobs:
        print("  No new jobs to analyze.")
        return []

    print(f"  Analyzing {len(new_jobs)} new jobs...")

    # Analyze each job
    analyzed_jobs = []

    for i, job_data in enumerate(new_jobs):
        print(f"\n  [{i+1}/{len(new_jobs)}] {job_data.get('title', 'Unknown')[:50]}...")

        job = JobListing(
            title=job_data.get('title', 'Unknown'),
            company=job_data.get('company', ''),
            location=job_data.get('location', ''),
            url=job_data['url'],
            finn_code=job_data['finn_code'],
            profile_id=profile_id,
            profile_name=profile_name,
        )

        # Fetch full job details
        job.description = fetch_job_details(job.url)

        if job.description:
            # Extract company and location from description
            if not job.company:
                company_match = re.search(r'Company:\s*(.+?)(?:\n|$)', job.description)
                if company_match:
                    job.company = company_match.group(1).strip()

            if not job.location:
                location_match = re.search(r'Location:\s*(.+?)(?:\n|$)', job.description)
                if location_match:
                    job.location = location_match.group(1).strip()

            # Analyze with Claude
            job.score, job.reasoning = analyze_job_with_claude(job.description, profile_text)
            print(f"    Score: {job.score}/100 - {job.reasoning[:50]}...")
        else:
            job.score = 0
            job.reasoning = "Could not fetch job details"
            print(f"    Could not fetch job details")

        analyzed_jobs.append(job)

        # Save to history
        profile_history[job.finn_code] = {
            'title': job.title,
            'company': job.company,
            'location': job.location,
            'score': job.score,
            'reasoning': job.reasoning,
            'profile_id': profile_id,
            'profile_name': profile_name,
            'analyzed_date': datetime.now().strftime('%Y-%m-%d'),
        }

        # Save history after each job
        save_analyzed_jobs(analyzed_history)

        # Rate limiting
        time.sleep(2)

    return analyzed_jobs


def main():
    """Main execution function"""
    print("=" * 60)
    print("FINN.no Job Scanner - Multi-Profile Daily Scan")
    print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    # Get enabled profiles
    enabled_profiles = {
        pid: config for pid, config in SEARCH_PROFILES.items()
        if config.get('enabled', True)
    }

    if not enabled_profiles:
        print("No enabled search profiles found. Please configure SEARCH_PROFILES in config.py")
        return

    print(f"\nEnabled profiles: {', '.join(p.get('name', pid) for pid, p in enabled_profiles.items())}")

    # Load previously analyzed jobs
    analyzed_history = load_analyzed_jobs()
    total_history = sum(len(jobs) for jobs in analyzed_history.values() if isinstance(jobs, dict))
    print(f"Loaded {total_history} previously analyzed jobs from history")

    # Process each profile
    all_analyzed_jobs = []

    for profile_id, profile_config in enabled_profiles.items():
        jobs = process_profile(profile_id, profile_config, analyzed_history)
        all_analyzed_jobs.extend(jobs)

    # Generate combined report
    if all_analyzed_jobs:
        report = generate_summary_report(all_analyzed_jobs, enabled_profiles)
        report_file = save_report_to_file(report)
        send_email_report(report)
    else:
        print("\nNo new jobs analyzed across all profiles.")

    # Sync to cloud dashboard
    sync_to_cloud(SEARCH_PROFILES)

    # Final summary
    print("\n" + "=" * 60)
    print("Scan complete!")
    if all_analyzed_jobs:
        print(f"Total new jobs analyzed: {len(all_analyzed_jobs)}")
        for profile_id, config in enabled_profiles.items():
            count = len([j for j in all_analyzed_jobs if j.profile_id == profile_id])
            if count > 0:
                print(f"  - {config.get('name', profile_id)}: {count} jobs")
    total_history = sum(len(jobs) for jobs in analyzed_history.values() if isinstance(jobs, dict))
    print(f"Total jobs in history: {total_history}")
    print("=" * 60)


if __name__ == "__main__":
    main()
