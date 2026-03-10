import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from html import escape

from flask import render_template

from config import Config

logger = logging.getLogger(__name__)


def _smtp_configured():
    """Check if SMTP credentials are available."""
    return bool(Config.SMTP_USER and Config.SMTP_PASSWORD)


def _send_email(msg):
    """Send an email message via SMTP."""
    with smtplib.SMTP(Config.SMTP_HOST, Config.SMTP_PORT) as server:
        server.starttls()
        server.login(Config.SMTP_USER, Config.SMTP_PASSWORD)
        server.send_message(msg)


def _group_by_tier(jobs):
    """Group jobs into match-quality tiers."""
    tiers = {"strong": [], "possible": [], "stretch": []}
    for job in jobs:
        tier = job.get("match_tier", "possible")
        if tier in tiers:
            tiers[tier].append(job)
    return tiers


def send_digest(email, jobs, search_query, app=None, still_open_jobs=None):
    """Send an HTML email digest of new job listings."""
    if not _smtp_configured():
        logger.warning("SMTP not configured, skipping email to %s", email)
        return False

    tiers = _group_by_tier(jobs)
    still_open_jobs = still_open_jobs or []

    try:
        if app:
            with app.app_context():
                html = render_template(
                    "partials/email_digest.html",
                    jobs=jobs,
                    tiers=tiers,
                    search_query=search_query,
                    new_count=len(jobs),
                    still_open_jobs=still_open_jobs,
                    still_open_count=len(still_open_jobs),
                )
        else:
            html = _simple_html(jobs, search_query)

        msg = MIMEMultipart("alternative")
        msg["Subject"] = f"Job Alert: {len(jobs)} new matches for '{search_query}'"
        msg["From"] = Config.SMTP_FROM
        msg["To"] = email
        msg.attach(MIMEText(html, "html"))
        _send_email(msg)

        logger.info("Sent digest email to %s with %d jobs", email, len(jobs))
        return True

    except Exception as e:
        logger.error("Failed to send email to %s: %s", email, e)
        return False


def send_consolidated_digest(email, jobs, search_queries, app=None, still_open_jobs=None):
    """Send a single consolidated digest combining results from multiple alerts.

    search_queries: list of query strings that triggered this digest.
    """
    if not _smtp_configured():
        logger.warning("SMTP not configured, skipping email to %s", email)
        return False

    tiers = _group_by_tier(jobs)
    still_open_jobs = still_open_jobs or []
    combined_query = " | ".join(search_queries)

    try:
        if app:
            with app.app_context():
                html = render_template(
                    "partials/email_digest.html",
                    jobs=jobs,
                    tiers=tiers,
                    search_query=combined_query,
                    search_queries=search_queries,
                    new_count=len(jobs),
                    still_open_jobs=still_open_jobs,
                    still_open_count=len(still_open_jobs),
                    is_consolidated=len(search_queries) > 1,
                )
        else:
            html = _simple_html(jobs, combined_query)

        alert_count = len(search_queries)
        subject = (
            f"Job Alert: {len(jobs)} new matches across {alert_count} alerts"
            if alert_count > 1
            else f"Job Alert: {len(jobs)} new matches for '{search_queries[0]}'"
        )

        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = Config.SMTP_FROM
        msg["To"] = email
        msg.attach(MIMEText(html, "html"))
        _send_email(msg)

        logger.info("Sent consolidated digest to %s with %d jobs from %d alerts",
                     email, len(jobs), alert_count)
        return True

    except Exception as e:
        logger.error("Failed to send consolidated digest to %s: %s", email, e)
        return False


def send_password_reset_email(email, token, base_url):
    """Send a password reset email with the reset link."""
    if not _smtp_configured():
        logger.warning("SMTP not configured, skipping password reset email to %s", email)
        return False

    reset_url = f"{base_url}/reset-password/{token}"
    html = f"""
    <html><body style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto">
    <h2>Password Reset Request</h2>
    <p>You requested a password reset for your Nexus account.</p>
    <p>Click the link below to reset your password. This link will expire in 1 hour.</p>
    <p><a href="{reset_url}" style="display:inline-block;padding:10px 20px;background:#0d6efd;color:white;text-decoration:none;border-radius:5px">Reset Password</a></p>
    <p>Or copy and paste this URL into your browser:</p>
    <p style="word-break:break-all;color:#666">{reset_url}</p>
    <hr>
    <p style="color:#999;font-size:12px">If you did not request a password reset, you can safely ignore this email.</p>
    </body></html>"""

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = "Password Reset - Nexus"
        msg["From"] = Config.SMTP_FROM
        msg["To"] = email
        msg.attach(MIMEText(html, "html"))
        _send_email(msg)

        logger.info("Sent password reset email to %s", email)
        return True

    except Exception as e:
        logger.error("Failed to send password reset email to %s: %s", email, e)
        return False


def send_weekly_report(email, stats, app=None):
    """Send a weekly progress report email."""
    if not _smtp_configured():
        logger.warning("SMTP not configured, skipping weekly report to %s", email)
        return False

    try:
        if app:
            with app.app_context():
                html = render_template("partials/weekly_report.html", stats=stats)
        else:
            html = _simple_weekly_html(stats)

        msg = MIMEMultipart("alternative")
        msg["Subject"] = f"Nexus Weekly Report: {stats.get('apps_this_week', 0)} applications this week"
        msg["From"] = Config.SMTP_FROM
        msg["To"] = email
        msg.attach(MIMEText(html, "html"))
        _send_email(msg)

        logger.info("Sent weekly report to %s", email)
        return True

    except Exception as e:
        logger.error("Failed to send weekly report to %s: %s", email, e)
        return False


def _simple_weekly_html(stats):
    """Fallback HTML for weekly reports when templates are unavailable."""
    apps = stats.get("apps_this_week", 0)
    total = stats.get("total_apps", 0)
    rate = stats.get("response_rate", 0)
    interviews = stats.get("interviews", 0)

    return f"""
    <html><head><style>
    @media (prefers-color-scheme: dark) {{
        body {{ background-color: #1a1a2e !important; color: #e0e0e0 !important; }}
    }}
    </style></head>
    <body style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto">
    <h2>Weekly Job Search Report</h2>
    <p>Applications this week: <strong>{apps}</strong></p>
    <p>Total applications: <strong>{total}</strong></p>
    <p>Response rate: <strong>{rate}%</strong></p>
    <p>Active interviews: <strong>{interviews}</strong></p>
    <hr><p style="color:#999;font-size:12px">Sent by Nexus</p>
    </body></html>"""


def _simple_html(jobs, search_query):
    """Fallback HTML template for emails with dark mode support."""
    parts = []
    for job in jobs[:20]:
        score = job.get("match_score", "?")
        tier = job.get("match_tier", "")
        badge = ""
        if tier == "strong":
            badge = '<span style="color:green;font-weight:bold">[Strong Match]</span>'
        elif tier == "possible":
            badge = '<span style="color:orange">[Possible]</span>'
        elif tier == "stretch":
            badge = '<span style="color:gray">[Stretch]</span>'

        parts.append(f"""
        <tr>
            <td class="job-row" style="padding:8px;border-bottom:1px solid #eee">
                <strong>{escape(job['title'])}</strong> {badge}<br>
                <span class="text-secondary-email" style="color:#666">{escape(job['company'])}</span> — {escape(job.get('location', ''))}<br>
                <small>Score: {score}/100 | {escape(job.get('remote_status', ''))} | {escape(job.get('source', ''))}</small><br>
                <a href="{escape(job.get('apply_url', '#'))}" style="color:#007bff">Apply &rarr;</a>
            </td>
        </tr>""")

    rows = "".join(parts)
    return f"""
    <html><head><style>
    @media (prefers-color-scheme: dark) {{
        body {{ background-color: #1a1a2e !important; color: #e0e0e0 !important; }}
        h2 {{ color: #e0e0e0 !important; }}
        .job-row {{ border-bottom-color: #2a2a4a !important; }}
        .text-secondary-email {{ color: #a0a0a0 !important; }}
        a {{ color: #64b5f6 !important; }}
        table {{ background: #16213e !important; }}
    }}
    </style></head>
    <body style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto;background-color:#ffffff;color:#333333">
    <h2>Job Alert: {len(jobs)} new matches</h2>
    <p>Search: <strong>{escape(search_query)}</strong></p>
    <table style="width:100%;border-collapse:collapse">{rows}</table>
    <hr><p style="color:#999;font-size:12px">Sent by Nexus</p>
    </body></html>"""
