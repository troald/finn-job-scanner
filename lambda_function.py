"""
AWS Lambda handler for FINN.no Job Scanner.
Runs the job scanner entirely in AWS, storing results in S3.
"""

import os
import json
import boto3
import requests
from datetime import datetime, timedelta
from bs4 import BeautifulSoup
import anthropic
import re
import time
import uuid

# AWS clients
s3 = boto3.client('s3')
secrets = boto3.client('secretsmanager')

# Configuration from environment variables
BUCKET_NAME = os.environ.get('BUCKET_NAME', '')
SECRET_NAME = os.environ.get('SECRET_NAME', 'job-scanner/anthropic-api-key')
REGION = os.environ.get('AWS_REGION', 'eu-north-1')

# Default settings
DEFAULT_MINIMUM_SCORE = 30
DEFAULT_MAX_JOBS = 25


def get_api_key():
    """Retrieve Anthropic API key from Secrets Manager."""
    try:
        response = secrets.get_secret_value(SecretId=SECRET_NAME)
        secret = json.loads(response['SecretString'])
        return secret.get('ANTHROPIC_API_KEY', '')
    except Exception as e:
        print(f"Error retrieving API key: {e}")
        # Fall back to environment variable
        return os.environ.get('ANTHROPIC_API_KEY', '')


def load_from_s3(key, default=None):
    """Load JSON data from S3."""
    try:
        response = s3.get_object(Bucket=BUCKET_NAME, Key=key)
        return json.loads(response['Body'].read().decode('utf-8'))
    except s3.exceptions.NoSuchKey:
        return default if default is not None else {}
    except Exception as e:
        print(f"Error loading {key} from S3: {e}")
        return default if default is not None else {}


def save_to_s3(key, data, content_type='application/json'):
    """Save data to S3."""
    try:
        if isinstance(data, dict) or isinstance(data, list):
            body = json.dumps(data, indent=2, ensure_ascii=False)
        else:
            body = data

        # Set no-cache for data files to prevent stale dashboard data
        cache_control = 'no-cache, no-store, must-revalidate' if key.startswith('data/') else None

        params = {
            'Bucket': BUCKET_NAME,
            'Key': key,
            'Body': body.encode('utf-8'),
            'ContentType': content_type
        }
        if cache_control:
            params['CacheControl'] = cache_control

        s3.put_object(**params)
        return True
    except Exception as e:
        print(f"Error saving {key} to S3: {e}")
        return False


def create_notification(job, profile_id, profile_name, threshold):
    """Create a notification for a high-scoring job."""
    notification = {
        'id': str(uuid.uuid4()),
        'job_id': job.get('finn_code'),
        'profile_id': profile_id,
        'title': job.get('title', 'Unknown'),
        'company': job.get('company', ''),
        'score': job.get('score', 0),
        'threshold': threshold,
        'url': job.get('url', ''),
        'reasoning': job.get('reasoning', ''),
        'created_at': datetime.now().isoformat(),
        'read': False
    }

    # Load existing notifications
    notifications_data = load_from_s3('data/notifications.json', {'notifications': []})
    if not isinstance(notifications_data, dict):
        notifications_data = {'notifications': []}
    if 'notifications' not in notifications_data:
        notifications_data['notifications'] = []

    # Add new notification at the beginning
    notifications_data['notifications'].insert(0, notification)

    # Keep only last 100 notifications
    notifications_data['notifications'] = notifications_data['notifications'][:100]

    # Save back to S3
    save_to_s3('data/notifications.json', notifications_data)
    print(f"    Created notification for high-scoring job (score: {job.get('score')})")

    return notification


def fetch_finn_search_results(search_url, max_jobs):
    """Fetch job listings from FINN.no search page with pagination support.

    Returns:
        dict with 'jobs' list and 'limited' boolean indicating if max_jobs was hit
    """
    print(f"  Fetching from: {search_url[:80]}...")

    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.5',
    }

    all_jobs = []
    seen_codes = set()
    page = 1
    max_pages = 10  # Safety limit
    hit_limit = False

    while len(all_jobs) < max_jobs and page <= max_pages:
        # Build URL with page parameter
        separator = '&' if '?' in search_url else '?'
        page_url = f"{search_url}{separator}page={page}" if page > 1 else search_url

        if page > 1:
            print(f"    Fetching page {page}...")
            time.sleep(5)  # Rate limiting between pages

        response = requests.get(page_url, headers=headers, timeout=30)
        response.raise_for_status()

        soup = BeautifulSoup(response.text, 'html.parser')
        job_links = soup.find_all('a', href=re.compile(r'/job/ad/\d+'))

        jobs_on_page = 0
        for link in job_links:
            href = link.get('href', '')
            match = re.search(r'/job/ad/(\d+)', href)
            if match:
                finn_code = match.group(1)
                if finn_code in seen_codes:
                    continue
                seen_codes.add(finn_code)

                title = link.get_text(strip=True) or "Unknown Title"
                full_url = f"https://www.finn.no/job/ad/{finn_code}"

                all_jobs.append({
                    'finn_code': finn_code,
                    'url': full_url,
                    'title': title[:100],
                })
                jobs_on_page += 1

                if len(all_jobs) >= max_jobs:
                    hit_limit = True
                    break

        # No more jobs on this page = end of results
        if jobs_on_page == 0:
            break

        page += 1

    status = f"(limit: {max_jobs})" if hit_limit else "(all available)"
    print(f"  Found {len(all_jobs)} job listings across {page} page(s) {status}")
    return {'jobs': all_jobs[:max_jobs], 'limited': hit_limit, 'pages': page}


def fetch_job_details(job_url):
    """Fetch full job description from a FINN.no job page."""
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        }

        response = requests.get(job_url, headers=headers, timeout=30)
        response.raise_for_status()

        soup = BeautifulSoup(response.text, 'html.parser')
        details = []

        title_elem = soup.find('h1')
        if title_elem:
            details.append(f"Title: {title_elem.get_text(strip=True)}")

        company_elem = soup.find('a', href=re.compile(r'/job/employer/company/'))
        if not company_elem:
            company_elem = soup.find('a', href=re.compile(r'/job/search\?orgId='))
        if company_elem:
            details.append(f"Company: {company_elem.get_text(strip=True)}")

        location_elem = soup.find('a', href=re.compile(r'/job/search\?location='))
        if location_elem:
            details.append(f"Location: {location_elem.get_text(strip=True)}")

        main_content = soup.find('main') or soup.find('article') or soup

        for script in main_content(["script", "style", "nav", "footer", "header"]):
            script.decompose()

        text = main_content.get_text(separator='\n', strip=True)
        lines = [line.strip() for line in text.split('\n') if line.strip()]
        text = '\n'.join(lines)

        if len(text) > 4000:
            text = text[:4000] + "..."

        details.append(f"\nJob Description:\n{text}")

        return '\n'.join(details)

    except Exception as e:
        print(f"    Error fetching job details: {e}")
        return None


def analyze_job_with_claude(job_details, profile, api_key):
    """Use Claude API to analyze job fit."""
    client = anthropic.Anthropic(api_key=api_key)

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
            model="claude-haiku-4-5-20241022",
            max_tokens=300,
            messages=[{"role": "user", "content": prompt}]
        )

        result_text = response.content[0].text.strip()

        # Try to extract JSON from various response formats
        # 1. Check for markdown code blocks
        if "```" in result_text:
            match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', result_text, re.DOTALL)
            if match:
                result_text = match.group(1)

        # 2. Extract JSON by finding balanced braces
        start_idx = result_text.find('{')
        if start_idx != -1:
            brace_count = 0
            end_idx = start_idx
            for i, char in enumerate(result_text[start_idx:], start_idx):
                if char == '{':
                    brace_count += 1
                elif char == '}':
                    brace_count -= 1
                    if brace_count == 0:
                        end_idx = i + 1
                        break
            result_text = result_text[start_idx:end_idx]

        result = json.loads(result_text)
        return result['score'], result['reasoning']

    except Exception as e:
        print(f"    Error analyzing job: {e}")
        return 0, f"Error during analysis: {str(e)}"


def generate_report(all_jobs, profiles):
    """Generate markdown report."""
    today = datetime.now().strftime("%A, %B %d, %Y")

    report = f"""# Daily Job Match Report
**Date:** {today}

---

"""

    jobs_by_profile = {}
    for job in all_jobs:
        pid = job.get('profile_id', 'unknown')
        if pid not in jobs_by_profile:
            jobs_by_profile[pid] = []
        jobs_by_profile[pid].append(job)

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

        sorted_jobs = sorted(jobs, key=lambda x: x.get('score', 0), reverse=True)
        matching_jobs = [j for j in sorted_jobs if j.get('score', 0) >= min_score]

        if matching_jobs:
            for job in matching_jobs:
                title = job.get('title', 'Unknown')[:40]
                if len(job.get('title', '')) > 40:
                    title += '...'
                report += f"| **{job.get('score', 0)}** | {title} | {job.get('company', 'N/A')} | {job.get('location', 'N/A')} | [View]({job.get('url', '')}) |\n"
        else:
            report += "| - | No matching jobs found | - | - | - |\n"

        report += "\n"

        if matching_jobs:
            report += "### Detailed Analysis\n\n"
            for job in matching_jobs:
                report += f"""**{job.get('title', 'Unknown')}**
Company: {job.get('company', 'N/A')} | Location: {job.get('location', 'N/A')} | Score: {job.get('score', 0)}/100
{job.get('reasoning', '')}
[View on FINN]({job.get('url', '')})

---

"""

        total = len(jobs)
        high = len([j for j in jobs if j.get('score', 0) >= 70])
        medium = len([j for j in jobs if 40 <= j.get('score', 0) < 70])

        report += f"""**Stats:** {total} analyzed | {high} high match | {medium} medium match

---

"""

    report += "*Report generated automatically by Job Scanner (AWS Lambda)*\n"

    return report


def process_profile(profile_id, profile_config, analyzed_history, api_key, run_log=None):
    """Process a single search profile."""
    profile_name = profile_config.get('name', profile_id)
    search_url = profile_config.get('search_url', '')
    profile_text = profile_config.get('profile', '')
    max_jobs = profile_config.get('max_jobs', DEFAULT_MAX_JOBS)
    notification_threshold = profile_config.get('notification_threshold', 50)

    print(f"\n{'='*60}")
    print(f"Profile: {profile_name}")
    print(f"{'='*60}")

    # Initialize profile log
    profile_log = {
        'profile_id': profile_id,
        'profile_name': profile_name,
        'status': 'running',
        'search_url': search_url,
        'jobs_found': 0,
        'jobs_skipped': 0,
        'jobs_analyzed': 0,
        'jobs': [],
        'error': None
    }

    if run_log:
        run_log['profiles'].append(profile_log)
        save_run_log(run_log)

    if not search_url:
        print("  No search URL configured, skipping.")
        profile_log['status'] = 'skipped'
        profile_log['error'] = 'No search URL configured'
        if run_log:
            save_run_log(run_log)
        return []

    if profile_id not in analyzed_history:
        analyzed_history[profile_id] = {}

    profile_history = analyzed_history[profile_id]

    try:
        fetch_result = fetch_finn_search_results(search_url, max_jobs)
        job_listings = fetch_result['jobs']
        profile_log['jobs_found'] = len(job_listings)
        profile_log['limited'] = fetch_result['limited']
        profile_log['pages_fetched'] = fetch_result['pages']
    except Exception as e:
        error_msg = str(e)
        print(f"  Error fetching jobs: {error_msg}")
        profile_log['status'] = 'error'
        profile_log['error'] = error_msg
        if run_log:
            run_log['errors'].append(f"{profile_name}: {error_msg}")
            save_run_log(run_log)
        return []

    if not job_listings:
        print("  No job listings found.")
        profile_log['status'] = 'complete'
        if run_log:
            save_run_log(run_log)
        return []

    new_jobs = [j for j in job_listings if j['finn_code'] not in profile_history]
    skipped_count = len(job_listings) - len(new_jobs)
    profile_log['jobs_skipped'] = skipped_count

    if skipped_count > 0:
        print(f"  Skipping {skipped_count} previously analyzed jobs")

    if not new_jobs:
        print("  No new jobs to analyze.")
        profile_log['status'] = 'complete'
        if run_log:
            save_run_log(run_log)
        return []

    print(f"  Analyzing {len(new_jobs)} new jobs...")

    analyzed_jobs = []

    for i, job_data in enumerate(new_jobs):
        print(f"\n  [{i+1}/{len(new_jobs)}] {job_data.get('title', 'Unknown')[:50]}...")

        job = {
            'title': job_data.get('title', 'Unknown'),
            'company': '',
            'location': '',
            'url': job_data['url'],
            'finn_code': job_data['finn_code'],
            'profile_id': profile_id,
            'profile_name': profile_name,
        }

        # Log job being processed
        job_log = {
            'title': job['title'],
            'url': job['url'],
            'status': 'analyzing'
        }
        profile_log['jobs'].append(job_log)
        if run_log:
            save_run_log(run_log)

        description = fetch_job_details(job['url'])

        if description:
            company_match = re.search(r'Company:\s*(.+?)(?:\n|$)', description)
            if company_match:
                job['company'] = company_match.group(1).strip()

            location_match = re.search(r'Location:\s*(.+?)(?:\n|$)', description)
            if location_match:
                job['location'] = location_match.group(1).strip()

            job['score'], job['reasoning'] = analyze_job_with_claude(description, profile_text, api_key)
            print(f"    Score: {job['score']}/100 - {job['reasoning'][:50]}...")

            # Create notification if score exceeds threshold
            if job['score'] >= notification_threshold:
                create_notification(job, profile_id, profile_name, notification_threshold)

            # Update job log
            job_log['status'] = 'complete'
            job_log['score'] = job['score']
            job_log['company'] = job['company']
            job_log['location'] = job['location']
            job_log['reasoning'] = job['reasoning'][:100] + '...' if len(job.get('reasoning', '')) > 100 else job.get('reasoning', '')
        else:
            job['score'] = 0
            job['reasoning'] = "Could not fetch job details"
            job_log['status'] = 'error'
            job_log['error'] = 'Could not fetch job details'
            print(f"    Could not fetch job details")

        analyzed_jobs.append(job)
        profile_log['jobs_analyzed'] = len(analyzed_jobs)

        profile_history[job['finn_code']] = {
            'title': job['title'],
            'company': job['company'],
            'location': job['location'],
            'score': job['score'],
            'reasoning': job['reasoning'],
            'profile_id': profile_id,
            'profile_name': profile_name,
            'analyzed_date': datetime.now().strftime('%Y-%m-%d'),
        }

        # Save after each job
        save_to_s3('data/analyzed_jobs.json', analyzed_history)
        if run_log:
            save_run_log(run_log)

        # Rate limiting
        time.sleep(2)

    profile_log['status'] = 'complete'
    if run_log:
        save_run_log(run_log)

    return analyzed_jobs


def save_run_log(run_log):
    """Save current run log to S3."""
    # Save current run
    save_to_s3('data/run_log.json', run_log)

    # Also append to run history (keep last 50 runs)
    history = load_from_s3('data/run_history.json', [])
    if not isinstance(history, list):
        history = []

    # Update or append
    existing_idx = next((i for i, r in enumerate(history) if r.get('run_id') == run_log['run_id']), None)
    if existing_idx is not None:
        history[existing_idx] = run_log
    else:
        history.insert(0, run_log)

    # Keep only last 50 runs
    history = history[:50]
    save_to_s3('data/run_history.json', history)


def update_reports_index():
    """Update the reports index file."""
    try:
        # List all report files
        response = s3.list_objects_v2(
            Bucket=BUCKET_NAME,
            Prefix='data/reports/job_report_'
        )

        reports = []
        for obj in response.get('Contents', []):
            filename = obj['Key'].split('/')[-1]
            date_str = filename.replace('job_report_', '').replace('.md', '')
            try:
                date = datetime.strptime(date_str, '%Y%m%d')
                reports.append({
                    'filename': filename,
                    'date': date.strftime('%Y-%m-%d'),
                    'date_display': date.strftime('%B %d, %Y'),
                })
            except ValueError:
                continue

        reports.sort(key=lambda x: x['date'], reverse=True)
        save_to_s3('data/reports_index.json', reports)

    except Exception as e:
        print(f"Error updating reports index: {e}")


def cleanup_old_data(days_to_keep=10):
    """Remove reports and job data older than specified days."""
    print(f"\nCleaning up data older than {days_to_keep} days...")

    cutoff_date = datetime.now() - timedelta(days=days_to_keep)
    cutoff_str = cutoff_date.strftime('%Y-%m-%d')
    deleted_reports = 0
    deleted_jobs = 0

    try:
        # Clean up old reports
        response = s3.list_objects_v2(
            Bucket=BUCKET_NAME,
            Prefix='data/reports/job_report_'
        )

        for obj in response.get('Contents', []):
            filename = obj['Key'].split('/')[-1]
            date_str = filename.replace('job_report_', '').replace('.md', '')
            try:
                report_date = datetime.strptime(date_str, '%Y%m%d')
                if report_date < cutoff_date:
                    s3.delete_object(Bucket=BUCKET_NAME, Key=obj['Key'])
                    deleted_reports += 1
                    print(f"  Deleted old report: {filename}")
            except ValueError:
                continue

        # Clean up old job entries from analyzed_jobs.json
        analyzed_history = load_from_s3('data/analyzed_jobs.json', {})

        for profile_id, profile_jobs in analyzed_history.items():
            if isinstance(profile_jobs, dict):
                jobs_to_delete = []
                for finn_code, job in profile_jobs.items():
                    job_date = job.get('analyzed_date', '')
                    if job_date and job_date < cutoff_str:
                        jobs_to_delete.append(finn_code)

                for finn_code in jobs_to_delete:
                    del profile_jobs[finn_code]
                    deleted_jobs += 1

        if deleted_jobs > 0:
            save_to_s3('data/analyzed_jobs.json', analyzed_history)
            print(f"  Removed {deleted_jobs} old job entries")

        if deleted_reports > 0 or deleted_jobs > 0:
            print(f"  Cleanup complete: {deleted_reports} reports, {deleted_jobs} jobs removed")
        else:
            print("  No old data to clean up")

    except Exception as e:
        print(f"Error during cleanup: {e}")


def lambda_handler(event, context):
    """AWS Lambda entry point."""
    start_time = datetime.now()

    print("=" * 60)
    print("FINN.no Job Scanner - AWS Lambda Execution")
    print(f"Time: {start_time.strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    # Initialize run log
    run_log = {
        'run_id': start_time.strftime('%Y%m%d_%H%M%S'),
        'start_time': start_time.isoformat(),
        'status': 'running',
        'source': event.get('source', 'scheduled'),
        'profiles': [],
        'summary': {},
        'errors': []
    }

    # Save initial log
    save_run_log(run_log)

    # Get API key
    api_key = get_api_key()
    if not api_key:
        run_log['status'] = 'error'
        run_log['errors'].append('Could not retrieve API key from Secrets Manager')
        run_log['end_time'] = datetime.now().isoformat()
        save_run_log(run_log)
        return {
            'statusCode': 500,
            'body': json.dumps({'error': 'Could not retrieve API key'})
        }

    # Load configuration from S3
    config = load_from_s3('config/search_profiles.json', {})

    if not config:
        return {
            'statusCode': 400,
            'body': json.dumps({'error': 'No search profiles configured. Upload config/search_profiles.json to S3.'})
        }

    # Get enabled profiles
    profiles = {
        pid: cfg for pid, cfg in config.items()
        if cfg.get('enabled', True)
    }

    if not profiles:
        return {
            'statusCode': 400,
            'body': json.dumps({'error': 'No enabled search profiles found'})
        }

    print(f"\nEnabled profiles: {', '.join(p.get('name', pid) for pid, p in profiles.items())}")

    # Load analyzed jobs history
    analyzed_history = load_from_s3('data/analyzed_jobs.json', {})
    total_history = sum(len(jobs) for jobs in analyzed_history.values() if isinstance(jobs, dict))
    print(f"Loaded {total_history} previously analyzed jobs from history")

    # Process each profile
    all_analyzed_jobs = []

    for profile_id, profile_config in profiles.items():
        jobs = process_profile(profile_id, profile_config, analyzed_history, api_key, run_log)
        all_analyzed_jobs.extend(jobs)

    # Generate and save report
    if all_analyzed_jobs:
        report = generate_report(all_analyzed_jobs, profiles)
        report_filename = f"job_report_{datetime.now().strftime('%Y%m%d')}.md"
        save_to_s3(f'data/reports/{report_filename}', report, 'text/markdown')
        print(f"\nReport saved: {report_filename}")
    else:
        print("\nNo new jobs analyzed across all profiles.")

    # Update profiles metadata for dashboard
    profiles_meta = {
        pid: {"name": p.get("name", pid), "enabled": p.get("enabled", True)}
        for pid, p in config.items()
    }
    save_to_s3('data/profiles.json', profiles_meta)

    # Update reports index
    update_reports_index()

    # Clean up old data (older than 10 days)
    cleanup_old_data(days_to_keep=10)

    # Summary
    total_history = sum(len(jobs) for jobs in analyzed_history.values() if isinstance(jobs, dict))
    end_time = datetime.now()
    duration_seconds = (end_time - start_time).total_seconds()

    # Finalize run log
    run_log['status'] = 'complete'
    run_log['end_time'] = end_time.isoformat()
    run_log['duration_seconds'] = round(duration_seconds, 1)
    run_log['summary'] = {
        'jobs_analyzed': len(all_analyzed_jobs),
        'profiles_processed': len(profiles),
        'total_in_history': total_history,
        'high_matches': len([j for j in all_analyzed_jobs if j.get('score', 0) >= 70]),
        'medium_matches': len([j for j in all_analyzed_jobs if 40 <= j.get('score', 0) < 70]),
    }
    save_run_log(run_log)

    result = {
        'statusCode': 200,
        'body': json.dumps({
            'message': 'Scan complete',
            'new_jobs_analyzed': len(all_analyzed_jobs),
            'total_jobs_in_history': total_history,
            'profiles_processed': list(profiles.keys())
        })
    }

    print("\n" + "=" * 60)
    print("Scan complete!")
    print(f"Total new jobs analyzed: {len(all_analyzed_jobs)}")
    print(f"Total jobs in history: {total_history}")
    print(f"Duration: {duration_seconds:.1f} seconds")
    print("=" * 60)

    return result
