#!/usr/bin/env python3
"""
Job Scanner Web Dashboard
A clean, editorial-style interface for reviewing job scan results.
"""

import json
import glob
import os
from datetime import datetime
from pathlib import Path
from flask import Flask, render_template_string, jsonify
import markdown

app = Flask(__name__)

# Paths
BASE_DIR = Path(__file__).parent
ANALYZED_JOBS_FILE = BASE_DIR / "analyzed_jobs.json"
REPORTS_PATTERN = str(BASE_DIR / "job_report_*.md")


def load_analyzed_jobs():
    """Load the analyzed jobs history."""
    if ANALYZED_JOBS_FILE.exists():
        try:
            with open(ANALYZED_JOBS_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return {}
    return {}


def get_reports():
    """Get list of available report files."""
    reports = []
    for filepath in glob.glob(REPORTS_PATTERN):
        filename = os.path.basename(filepath)
        # Extract date from filename (job_report_20260124.md)
        date_str = filename.replace('job_report_', '').replace('.md', '')
        try:
            date = datetime.strptime(date_str, '%Y%m%d')
            reports.append({
                'filename': filename,
                'date': date.strftime('%Y-%m-%d'),
                'date_display': date.strftime('%B %d, %Y'),
                'path': filepath
            })
        except ValueError:
            continue
    return sorted(reports, key=lambda x: x['date'], reverse=True)


def load_report(filename):
    """Load and convert a markdown report to HTML."""
    filepath = BASE_DIR / filename
    if filepath.exists():
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
        return markdown.markdown(content, extensions=['tables', 'fenced_code'])
    return None


# HTML Template with embedded CSS
TEMPLATE = '''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Job Scanner Dashboard</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Instrument+Serif:ital@0;1&family=DM+Sans:opsz,wght@9..40,300;9..40,400;9..40,500&display=swap" rel="stylesheet">
    <style>
        :root {
            --bg-primary: #0a0a0a;
            --bg-secondary: #141414;
            --bg-card: #1a1a1a;
            --bg-hover: #222222;
            --text-primary: #f5f5f4;
            --text-secondary: #a8a8a8;
            --text-muted: #6b6b6b;
            --accent: #e8e4dd;
            --border: #2a2a2a;
            --score-high: #4ade80;
            --score-mid: #fbbf24;
            --score-low: #f87171;
            --gradient-subtle: linear-gradient(135deg, #1a1a1a 0%, #0f0f0f 100%);
        }

        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }

        body {
            font-family: 'DM Sans', sans-serif;
            background: var(--bg-primary);
            color: var(--text-primary);
            line-height: 1.6;
            min-height: 100vh;
        }

        /* Subtle grain texture overlay */
        body::before {
            content: '';
            position: fixed;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            opacity: 0.03;
            pointer-events: none;
            background-image: url("data:image/svg+xml,%3Csvg viewBox='0 0 256 256' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='noise'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='4' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23noise)'/%3E%3C/svg%3E");
            z-index: 1000;
        }

        .container {
            max-width: 1400px;
            margin: 0 auto;
            padding: 0 2rem;
        }

        /* Header */
        header {
            padding: 3rem 0 2rem;
            border-bottom: 1px solid var(--border);
            margin-bottom: 3rem;
        }

        .logo {
            font-family: 'Instrument Serif', serif;
            font-size: 2.5rem;
            font-weight: 400;
            letter-spacing: -0.02em;
            color: var(--accent);
            margin-bottom: 0.5rem;
        }

        .logo span {
            font-style: italic;
            color: var(--text-secondary);
        }

        .tagline {
            font-size: 0.875rem;
            color: var(--text-muted);
            text-transform: uppercase;
            letter-spacing: 0.1em;
        }

        /* Navigation */
        nav {
            display: flex;
            gap: 0.5rem;
            margin-bottom: 3rem;
        }

        .nav-btn {
            padding: 0.75rem 1.5rem;
            background: transparent;
            border: 1px solid var(--border);
            color: var(--text-secondary);
            font-family: inherit;
            font-size: 0.875rem;
            cursor: pointer;
            transition: all 0.2s ease;
            border-radius: 2px;
        }

        .nav-btn:hover {
            background: var(--bg-card);
            color: var(--text-primary);
        }

        .nav-btn.active {
            background: var(--accent);
            color: var(--bg-primary);
            border-color: var(--accent);
        }

        /* Stats Grid */
        .stats-grid {
            display: grid;
            grid-template-columns: repeat(4, 1fr);
            gap: 1.5rem;
            margin-bottom: 3rem;
        }

        .stat-card {
            background: var(--gradient-subtle);
            border: 1px solid var(--border);
            padding: 1.5rem;
            border-radius: 3px;
            position: relative;
            overflow: hidden;
        }

        .stat-card::after {
            content: '';
            position: absolute;
            top: 0;
            left: 0;
            width: 100%;
            height: 2px;
            background: linear-gradient(90deg, transparent, var(--accent), transparent);
            opacity: 0.3;
        }

        .stat-value {
            font-family: 'Instrument Serif', serif;
            font-size: 3rem;
            line-height: 1;
            margin-bottom: 0.5rem;
        }

        .stat-label {
            font-size: 0.75rem;
            text-transform: uppercase;
            letter-spacing: 0.1em;
            color: var(--text-muted);
        }

        .stat-card.high .stat-value { color: var(--score-high); }
        .stat-card.mid .stat-value { color: var(--score-mid); }
        .stat-card.low .stat-value { color: var(--score-low); }

        /* Section Headers */
        .section-header {
            display: flex;
            justify-content: space-between;
            align-items: baseline;
            margin-bottom: 1.5rem;
            padding-bottom: 1rem;
            border-bottom: 1px solid var(--border);
        }

        .section-title {
            font-family: 'Instrument Serif', serif;
            font-size: 1.5rem;
            font-weight: 400;
        }

        .section-count {
            font-size: 0.875rem;
            color: var(--text-muted);
        }

        /* Jobs Table */
        .jobs-table {
            width: 100%;
            border-collapse: collapse;
            margin-bottom: 3rem;
        }

        .jobs-table th {
            text-align: left;
            padding: 1rem;
            font-size: 0.75rem;
            text-transform: uppercase;
            letter-spacing: 0.1em;
            color: var(--text-muted);
            border-bottom: 1px solid var(--border);
            font-weight: 500;
        }

        .jobs-table td {
            padding: 1rem;
            border-bottom: 1px solid var(--border);
            vertical-align: middle;
        }

        .jobs-table tr {
            transition: background 0.15s ease;
        }

        .jobs-table tbody tr:hover {
            background: var(--bg-hover);
        }

        .job-title {
            font-weight: 500;
            color: var(--text-primary);
            margin-bottom: 0.25rem;
        }

        .job-company {
            font-size: 0.875rem;
            color: var(--text-secondary);
        }

        .score-badge {
            display: inline-flex;
            align-items: center;
            justify-content: center;
            width: 3rem;
            height: 3rem;
            border-radius: 50%;
            font-family: 'Instrument Serif', serif;
            font-size: 1.125rem;
            font-weight: 400;
        }

        .score-badge.high {
            background: rgba(74, 222, 128, 0.1);
            color: var(--score-high);
            border: 1px solid rgba(74, 222, 128, 0.3);
        }

        .score-badge.mid {
            background: rgba(251, 191, 36, 0.1);
            color: var(--score-mid);
            border: 1px solid rgba(251, 191, 36, 0.3);
        }

        .score-badge.low {
            background: rgba(248, 113, 113, 0.1);
            color: var(--score-low);
            border: 1px solid rgba(248, 113, 113, 0.3);
        }

        .date-cell {
            font-size: 0.875rem;
            color: var(--text-secondary);
        }

        .link-btn {
            display: inline-flex;
            align-items: center;
            gap: 0.5rem;
            padding: 0.5rem 1rem;
            background: transparent;
            border: 1px solid var(--border);
            color: var(--text-secondary);
            text-decoration: none;
            font-size: 0.8125rem;
            transition: all 0.2s ease;
            border-radius: 2px;
        }

        .link-btn:hover {
            background: var(--accent);
            color: var(--bg-primary);
            border-color: var(--accent);
        }

        /* Reports Section */
        .reports-grid {
            display: grid;
            grid-template-columns: 280px 1fr;
            gap: 2rem;
            margin-bottom: 3rem;
        }

        .reports-list {
            border: 1px solid var(--border);
            border-radius: 3px;
            overflow: hidden;
        }

        .report-item {
            padding: 1rem 1.25rem;
            border-bottom: 1px solid var(--border);
            cursor: pointer;
            transition: all 0.15s ease;
        }

        .report-item:last-child {
            border-bottom: none;
        }

        .report-item:hover {
            background: var(--bg-hover);
        }

        .report-item.active {
            background: var(--bg-card);
            border-left: 2px solid var(--accent);
        }

        .report-date {
            font-family: 'Instrument Serif', serif;
            font-size: 1.125rem;
            margin-bottom: 0.25rem;
        }

        .report-meta {
            font-size: 0.75rem;
            color: var(--text-muted);
        }

        .report-content {
            background: var(--bg-card);
            border: 1px solid var(--border);
            border-radius: 3px;
            padding: 2rem;
            min-height: 500px;
        }

        .report-content h1 {
            font-family: 'Instrument Serif', serif;
            font-size: 2rem;
            font-weight: 400;
            margin-bottom: 1.5rem;
            color: var(--accent);
        }

        .report-content h2 {
            font-family: 'Instrument Serif', serif;
            font-size: 1.5rem;
            font-weight: 400;
            margin: 2rem 0 1rem;
            padding-bottom: 0.5rem;
            border-bottom: 1px solid var(--border);
        }

        .report-content h3 {
            font-size: 1.125rem;
            font-weight: 500;
            margin: 1.5rem 0 0.75rem;
        }

        .report-content p {
            margin-bottom: 1rem;
            color: var(--text-secondary);
        }

        .report-content strong {
            color: var(--text-primary);
        }

        .report-content table {
            width: 100%;
            border-collapse: collapse;
            margin: 1.5rem 0;
            font-size: 0.875rem;
        }

        .report-content th,
        .report-content td {
            padding: 0.75rem;
            text-align: left;
            border-bottom: 1px solid var(--border);
        }

        .report-content th {
            color: var(--text-muted);
            font-weight: 500;
            text-transform: uppercase;
            letter-spacing: 0.05em;
            font-size: 0.75rem;
        }

        .report-content a {
            color: var(--accent);
            text-decoration: none;
            border-bottom: 1px solid transparent;
            transition: border-color 0.15s ease;
        }

        .report-content a:hover {
            border-color: var(--accent);
        }

        .report-content hr {
            border: none;
            border-top: 1px solid var(--border);
            margin: 2rem 0;
        }

        .report-content ul, .report-content ol {
            margin: 1rem 0;
            padding-left: 1.5rem;
            color: var(--text-secondary);
        }

        .report-content li {
            margin-bottom: 0.5rem;
        }

        .empty-state {
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            height: 300px;
            color: var(--text-muted);
            text-align: center;
        }

        .empty-state-icon {
            font-size: 3rem;
            margin-bottom: 1rem;
            opacity: 0.5;
        }

        /* View transitions */
        .view {
            display: none;
            animation: fadeIn 0.3s ease;
        }

        .view.active {
            display: block;
        }

        @keyframes fadeIn {
            from { opacity: 0; transform: translateY(10px); }
            to { opacity: 1; transform: translateY(0); }
        }

        /* Responsive */
        @media (max-width: 1024px) {
            .stats-grid {
                grid-template-columns: repeat(2, 1fr);
            }

            .reports-grid {
                grid-template-columns: 1fr;
            }
        }

        @media (max-width: 640px) {
            .stats-grid {
                grid-template-columns: 1fr;
            }

            .container {
                padding: 0 1rem;
            }

            .logo {
                font-size: 2rem;
            }
        }
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1 class="logo">Job Scanner <span>Dashboard</span></h1>
            <p class="tagline">FINN.no &bull; AI-Powered Job Matching</p>
        </header>

        <nav>
            <button class="nav-btn active" data-view="dashboard">Dashboard</button>
            <button class="nav-btn" data-view="reports">Reports</button>
        </nav>

        <!-- Dashboard View -->
        <div id="dashboard" class="view active">
            <div class="stats-grid">
                <div class="stat-card">
                    <div class="stat-value" id="total-jobs">0</div>
                    <div class="stat-label">Total Analyzed</div>
                </div>
                <div class="stat-card high">
                    <div class="stat-value" id="high-match">0</div>
                    <div class="stat-label">High Match (70+)</div>
                </div>
                <div class="stat-card mid">
                    <div class="stat-value" id="mid-match">0</div>
                    <div class="stat-label">Medium Match</div>
                </div>
                <div class="stat-card low">
                    <div class="stat-value" id="low-match">0</div>
                    <div class="stat-label">Low Match</div>
                </div>
            </div>

            <div class="section-header">
                <h2 class="section-title">Analyzed Jobs</h2>
                <span class="section-count" id="jobs-count">0 jobs</span>
            </div>

            <table class="jobs-table">
                <thead>
                    <tr>
                        <th>Score</th>
                        <th>Position</th>
                        <th>Analyzed</th>
                        <th>Action</th>
                    </tr>
                </thead>
                <tbody id="jobs-tbody">
                </tbody>
            </table>
        </div>

        <!-- Reports View -->
        <div id="reports" class="view">
            <div class="section-header">
                <h2 class="section-title">Daily Reports</h2>
                <span class="section-count" id="reports-count">0 reports</span>
            </div>

            <div class="reports-grid">
                <div class="reports-list" id="reports-list">
                </div>
                <div class="report-content" id="report-content">
                    <div class="empty-state">
                        <div class="empty-state-icon">📄</div>
                        <p>Select a report to view</p>
                    </div>
                </div>
            </div>
        </div>
    </div>

    <script>
        // Navigation
        document.querySelectorAll('.nav-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                document.querySelectorAll('.nav-btn').forEach(b => b.classList.remove('active'));
                document.querySelectorAll('.view').forEach(v => v.classList.remove('active'));
                btn.classList.add('active');
                document.getElementById(btn.dataset.view).classList.add('active');
            });
        });

        // Load dashboard data
        async function loadDashboard() {
            try {
                const response = await fetch('/api/jobs');
                const jobs = await response.json();

                // Calculate stats
                const total = Object.keys(jobs).length;
                const high = Object.values(jobs).filter(j => j.score >= 70).length;
                const mid = Object.values(jobs).filter(j => j.score >= 40 && j.score < 70).length;
                const low = Object.values(jobs).filter(j => j.score < 40).length;

                document.getElementById('total-jobs').textContent = total;
                document.getElementById('high-match').textContent = high;
                document.getElementById('mid-match').textContent = mid;
                document.getElementById('low-match').textContent = low;
                document.getElementById('jobs-count').textContent = `${total} jobs`;

                // Populate table
                const tbody = document.getElementById('jobs-tbody');
                tbody.innerHTML = '';

                // Sort by score descending
                const sortedJobs = Object.entries(jobs)
                    .sort((a, b) => (b[1].score || 0) - (a[1].score || 0));

                if (sortedJobs.length === 0) {
                    tbody.innerHTML = `
                        <tr>
                            <td colspan="4">
                                <div class="empty-state">
                                    <div class="empty-state-icon">🔍</div>
                                    <p>No jobs analyzed yet. Run the scanner first.</p>
                                </div>
                            </td>
                        </tr>
                    `;
                    return;
                }

                sortedJobs.forEach(([finnCode, job]) => {
                    const scoreClass = job.score >= 70 ? 'high' : job.score >= 40 ? 'mid' : 'low';
                    const row = document.createElement('tr');
                    row.innerHTML = `
                        <td><span class="score-badge ${scoreClass}">${job.score || 0}</span></td>
                        <td>
                            <div class="job-title">${escapeHtml(job.title || 'Unknown')}</div>
                            <div class="job-company">${escapeHtml(job.company || 'Unknown company')}</div>
                        </td>
                        <td class="date-cell">${job.analyzed_date || 'N/A'}</td>
                        <td>
                            <a href="https://www.finn.no/job/ad/${finnCode}" target="_blank" class="link-btn">
                                View on FINN →
                            </a>
                        </td>
                    `;
                    tbody.appendChild(row);
                });
            } catch (error) {
                console.error('Failed to load jobs:', error);
            }
        }

        // Load reports list
        async function loadReports() {
            try {
                const response = await fetch('/api/reports');
                const reports = await response.json();

                document.getElementById('reports-count').textContent = `${reports.length} reports`;

                const list = document.getElementById('reports-list');
                list.innerHTML = '';

                if (reports.length === 0) {
                    list.innerHTML = `
                        <div class="empty-state" style="height: 200px;">
                            <p>No reports generated yet</p>
                        </div>
                    `;
                    return;
                }

                reports.forEach((report, index) => {
                    const item = document.createElement('div');
                    item.className = 'report-item' + (index === 0 ? ' active' : '');
                    item.dataset.filename = report.filename;
                    item.innerHTML = `
                        <div class="report-date">${report.date_display}</div>
                        <div class="report-meta">${report.filename}</div>
                    `;
                    item.addEventListener('click', () => loadReport(report.filename, item));
                    list.appendChild(item);
                });

                // Load first report
                if (reports.length > 0) {
                    loadReport(reports[0].filename);
                }
            } catch (error) {
                console.error('Failed to load reports:', error);
            }
        }

        // Load single report
        async function loadReport(filename, clickedItem = null) {
            try {
                // Update active state
                if (clickedItem) {
                    document.querySelectorAll('.report-item').forEach(i => i.classList.remove('active'));
                    clickedItem.classList.add('active');
                }

                const response = await fetch(`/api/report/${filename}`);
                const data = await response.json();

                if (data.html) {
                    document.getElementById('report-content').innerHTML = data.html;
                }
            } catch (error) {
                console.error('Failed to load report:', error);
            }
        }

        // Escape HTML
        function escapeHtml(text) {
            const div = document.createElement('div');
            div.textContent = text;
            return div.innerHTML;
        }

        // Initialize
        loadDashboard();
        loadReports();
    </script>
</body>
</html>
'''


@app.route('/')
def index():
    """Serve the main dashboard."""
    return render_template_string(TEMPLATE)


@app.route('/api/jobs')
def api_jobs():
    """API endpoint for analyzed jobs."""
    return jsonify(load_analyzed_jobs())


@app.route('/api/reports')
def api_reports():
    """API endpoint for report list."""
    return jsonify(get_reports())


@app.route('/api/report/<filename>')
def api_report(filename):
    """API endpoint for single report content."""
    # Security: ensure filename matches expected pattern
    if not filename.startswith('job_report_') or not filename.endswith('.md'):
        return jsonify({'error': 'Invalid filename'}), 400

    html = load_report(filename)
    if html:
        return jsonify({'html': html})
    return jsonify({'error': 'Report not found'}), 404


if __name__ == '__main__':
    print("=" * 50)
    print("Job Scanner Dashboard")
    print("=" * 50)
    print(f"Open http://localhost:5000 in your browser")
    print("Press Ctrl+C to stop")
    print("=" * 50)
    app.run(debug=True, port=5000)
