#!/usr/bin/env python3
"""
FINN.no Job Scanner with AI Assessment
Automatically scans job listings and scores them against your profile using Claude API.
"""

import os
import json
import subprocess
import glob
import requests
from datetime import datetime, timedelta
from bs4 import BeautifulSoup
import anthropic
from dataclasses import dataclass
from typing import Optional
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import time
import re
from pathlib import Path

# File to track previously analyzed jobs
BASE_DIR = Path(__file__).parent
ANALYZED_JOBS_FILE = BASE_DIR / "analyzed_jobs.json"
AWS_CONFIG_FILE = BASE_DIR / "aws_dashboard_config.json"

# Load configuration
from config import (
    ANTHROPIC_API_KEY,
    USER_PROFILE,
    FINN_SEARCH_URL,
    EMAIL_CONFIG,
    MINIMUM_SCORE_TO_INCLUDE,
    MAX_JOBS_TO_ANALYZE,
)


def load_analyzed_jobs() -> dict:
    """Load previously analyzed jobs from JSON file"""
    if ANALYZED_JOBS_FILE.exists():
        try:
            with open(ANALYZED_JOBS_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
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


def sync_to_cloud():
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
    description: Optional[str] = None
    score: Optional[int] = None
    reasoning: Optional[str] = None


def fetch_finn_search_results(search_url: str) -> list[dict]:
    """Fetch job listings from FINN.no search page"""
    print(f"Fetching job listings from FINN.no...")
    
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
    # Look for article elements or links with job ad patterns
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
            
            # Try to extract title and company from the link structure
            title = link.get_text(strip=True) or "Unknown Title"
            
            # Build full URL
            full_url = f"https://www.finn.no/job/ad/{finn_code}"
            
            jobs.append({
                'finn_code': finn_code,
                'url': full_url,
                'title': title[:100],  # Truncate long titles
            })
    
    print(f"Found {len(jobs)} job listings")
    return jobs[:MAX_JOBS_TO_ANALYZE]


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
        
        # Get job description - look for main content area
        # FINN.no typically has the description in the main article/content area
        main_content = soup.find('main') or soup.find('article') or soup
        
        # Remove script and style elements
        for script in main_content(["script", "style", "nav", "footer", "header"]):
            script.decompose()
        
        # Get text content
        text = main_content.get_text(separator='\n', strip=True)
        
        # Clean up excessive whitespace
        lines = [line.strip() for line in text.split('\n') if line.strip()]
        text = '\n'.join(lines)
        
        # Truncate if too long (keep first 4000 chars for API efficiency)
        if len(text) > 4000:
            text = text[:4000] + "..."
        
        details.append(f"\nJob Description:\n{text}")
        
        return '\n'.join(details)
        
    except Exception as e:
        print(f"Error fetching job details: {e}")
        return None


def analyze_job_with_claude(job_details: str, user_profile: str) -> tuple[int, str]:
    """Use Claude API to analyze job fit and return score + reasoning"""
    
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    
    prompt = f"""Analyze this job listing against the candidate's profile and provide a match score from 0-100.

## Candidate Profile:
{user_profile}

## Job Listing:
{job_details}

## Instructions:
1. Score the job from 0-100 based on how well it matches the candidate's:
   - Education and qualifications
   - Work experience and industry background
   - Skills and interests (including digitalization passion)
   - Seniority level appropriateness
   
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
        # Handle potential markdown code blocks
        if "```" in result_text:
            result_text = re.search(r'```(?:json)?\s*({.*?})\s*```', result_text, re.DOTALL)
            if result_text:
                result_text = result_text.group(1)
        
        result = json.loads(result_text)
        return result['score'], result['reasoning']
        
    except Exception as e:
        print(f"Error analyzing job: {e}")
        return 0, f"Error during analysis: {str(e)}"


def generate_summary_report(jobs: list[JobListing], user_profile: str) -> str:
    """Generate the final summary report with table"""
    
    today = datetime.now().strftime("%A, %B %d, %Y")
    
    report = f"""# Daily Job Match Report
**Date:** {today}

## Your Profile Summary
{user_profile}

---

## Job Matches (Sorted by Score)

| Score | Position | Company | Location | Link |
|-------|----------|---------|----------|------|
"""
    
    # Sort jobs by score descending
    sorted_jobs = sorted(jobs, key=lambda x: x.score or 0, reverse=True)
    
    for job in sorted_jobs:
        if job.score is not None and job.score >= MINIMUM_SCORE_TO_INCLUDE:
            report += f"| **{job.score}** | {job.title[:40]}{'...' if len(job.title) > 40 else ''} | {job.company or 'N/A'} | {job.location or 'N/A'} | [View]({job.url}) |\n"
    
    report += "\n---\n\n## Detailed Analysis\n\n"
    
    for job in sorted_jobs:
        if job.score is not None and job.score >= MINIMUM_SCORE_TO_INCLUDE:
            report += f"""### {job.title}
**Company:** {job.company or 'N/A'}  
**Location:** {job.location or 'N/A'}  
**Score:** {job.score}/100  
**Link:** {job.url}

**Assessment:** {job.reasoning}

---

"""
    
    # Summary statistics
    total_analyzed = len([j for j in jobs if j.score is not None])
    high_matches = len([j for j in jobs if j.score and j.score >= 70])
    medium_matches = len([j for j in jobs if j.score and 40 <= j.score < 70])
    
    report += f"""## Summary Statistics
- **Total jobs analyzed:** {total_analyzed}
- **High matches (70+):** {high_matches}
- **Medium matches (40-69):** {medium_matches}
- **Below threshold (<{MINIMUM_SCORE_TO_INCLUDE}):** {total_analyzed - high_matches - medium_matches}

---
*Report generated automatically by Job Scanner*
"""
    
    return report


def send_email_report(report: str, html_report: str = None):
    """Send the report via email"""
    if not EMAIL_CONFIG.get('enabled'):
        print("Email notifications disabled")
        return
    
    msg = MIMEMultipart('alternative')
    msg['Subject'] = f"Daily Job Match Report - {datetime.now().strftime('%Y-%m-%d')}"
    msg['From'] = EMAIL_CONFIG['from_email']
    msg['To'] = EMAIL_CONFIG['to_email']
    
    # Plain text version
    msg.attach(MIMEText(report, 'plain'))
    
    # HTML version (if provided)
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
    
    with open(filename, 'w', encoding='utf-8') as f:
        f.write(report)
    
    print(f"Report saved to {filename}")
    return filename


def main():
    """Main execution function"""
    print("=" * 60)
    print("FINN.no Job Scanner - Starting daily scan")
    print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    # Load previously analyzed jobs
    analyzed_history = load_analyzed_jobs()
    print(f"Loaded {len(analyzed_history)} previously analyzed jobs from history")

    # Step 1: Fetch job listings from FINN.no
    job_listings = fetch_finn_search_results(FINN_SEARCH_URL)

    if not job_listings:
        print("No job listings found. Exiting.")
        return

    # Filter out already analyzed jobs
    new_jobs = [j for j in job_listings if j['finn_code'] not in analyzed_history]
    skipped_count = len(job_listings) - len(new_jobs)

    if skipped_count > 0:
        print(f"Skipping {skipped_count} previously analyzed jobs")

    if not new_jobs:
        print("No new jobs to analyze. Exiting.")
        return

    print(f"Found {len(new_jobs)} new jobs to analyze")

    # Step 2: Fetch details and analyze each job
    analyzed_jobs = []

    for i, job_data in enumerate(new_jobs):
        print(f"\nAnalyzing job {i+1}/{len(new_jobs)}: {job_data.get('title', 'Unknown')[:50]}...")

        # Create JobListing object
        job = JobListing(
            title=job_data.get('title', 'Unknown'),
            company=job_data.get('company', ''),
            location=job_data.get('location', ''),
            url=job_data['url'],
            finn_code=job_data['finn_code'],
        )

        # Fetch full job details
        job.description = fetch_job_details(job.url)

        if job.description:
            # Extract company and location from description if not already set
            if not job.company:
                company_match = re.search(r'Company:\s*(.+?)(?:\n|$)', job.description)
                if company_match:
                    job.company = company_match.group(1).strip()

            if not job.location:
                location_match = re.search(r'Location:\s*(.+?)(?:\n|$)', job.description)
                if location_match:
                    job.location = location_match.group(1).strip()

            # Analyze with Claude
            job.score, job.reasoning = analyze_job_with_claude(job.description, USER_PROFILE)
            print(f"  Score: {job.score}/100 - {job.reasoning[:60]}...")
        else:
            job.score = 0
            job.reasoning = "Could not fetch job details"
            print(f"  Could not fetch job details")

        analyzed_jobs.append(job)

        # Save to history
        analyzed_history[job.finn_code] = {
            'title': job.title,
            'company': job.company,
            'score': job.score,
            'analyzed_date': datetime.now().strftime('%Y-%m-%d'),
        }

        # Save history after each job (in case of interruption)
        save_analyzed_jobs(analyzed_history)

        # Rate limiting - be nice to FINN.no and Anthropic API
        time.sleep(2)

    # Step 3: Generate report
    report = generate_summary_report(analyzed_jobs, USER_PROFILE)

    # Step 4: Save and send report
    report_file = save_report_to_file(report)

    # Send email if configured
    send_email_report(report)

    # Sync to cloud dashboard if configured
    sync_to_cloud()

    print("\n" + "=" * 60)
    print("Scan complete!")
    print(f"Report saved to: {report_file}")
    print(f"Total jobs in history: {len(analyzed_history)}")
    print("=" * 60)


if __name__ == "__main__":
    main()
