import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from flask import render_template

from config import Config

logger = logging.getLogger(__name__)


def send_digest(email, jobs, search_query, app=None, still_open_jobs=None):
    """Send an HTML email digest of new job listings."""
    if not Config.SMTP_USER or not Config.SMTP_PASSWORD:
        logger.warning("SMTP not configured, skipping email to %s", email)
        return False

    # Group jobs by tier
    tiers = {"strong": [], "possible": [], "stretch": []}
    for job in jobs:
        tier = job.get("match_tier", "possible")
        if tier in tiers:
            tiers[tier].append(job)

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
            # Fallback plain HTML
            html = _simple_html(jobs, search_query)

        msg = MIMEMultipart("alternative")
        msg["Subject"] = f"Job Alert: {len(jobs)} new matches for '{search_query}'"
        msg["From"] = Config.SMTP_FROM
        msg["To"] = email
        msg.attach(MIMEText(html, "html"))

        with smtplib.SMTP(Config.SMTP_HOST, Config.SMTP_PORT) as server:
            server.starttls()
            server.login(Config.SMTP_USER, Config.SMTP_PASSWORD)
            server.send_message(msg)

        logger.info("Sent digest email to %s with %d jobs", email, len(jobs))
        return True

    except Exception as e:
        logger.error("Failed to send email to %s: %s", email, e)
        return False


def send_password_reset_email(email, token, base_url):
    """Send a password reset email with the reset link."""
    if not Config.SMTP_USER or not Config.SMTP_PASSWORD:
        logger.warning("SMTP not configured, skipping password reset email to %s", email)
        return False

    reset_url = f"{base_url}/reset-password/{token}"
    html = f"""
    <html><body style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto">
    <h2>Password Reset Request</h2>
    <p>You requested a password reset for your Job Search Tool account.</p>
    <p>Click the link below to reset your password. This link will expire in 1 hour.</p>
    <p><a href="{reset_url}" style="display:inline-block;padding:10px 20px;background:#0d6efd;color:white;text-decoration:none;border-radius:5px">Reset Password</a></p>
    <p>Or copy and paste this URL into your browser:</p>
    <p style="word-break:break-all;color:#666">{reset_url}</p>
    <hr>
    <p style="color:#999;font-size:12px">If you did not request a password reset, you can safely ignore this email.</p>
    </body></html>"""

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = "Password Reset - Job Search Tool"
        msg["From"] = Config.SMTP_FROM
        msg["To"] = email
        msg.attach(MIMEText(html, "html"))

        with smtplib.SMTP(Config.SMTP_HOST, Config.SMTP_PORT) as server:
            server.starttls()
            server.login(Config.SMTP_USER, Config.SMTP_PASSWORD)
            server.send_message(msg)

        logger.info("Sent password reset email to %s", email)
        return True

    except Exception as e:
        logger.error("Failed to send password reset email to %s: %s", email, e)
        return False


def _simple_html(jobs, search_query):
    """Fallback HTML template for emails."""
    rows = ""
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

        rows += f"""
        <tr>
            <td style="padding:8px;border-bottom:1px solid #eee">
                <strong>{job['title']}</strong> {badge}<br>
                <span style="color:#666">{job['company']}</span> — {job.get('location', '')}<br>
                <small>Score: {score}/100 | {job.get('remote_status', '')} | {job.get('source', '')}</small><br>
                <a href="{job.get('apply_url', '#')}">Apply →</a>
            </td>
        </tr>"""

    return f"""
    <html><body style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto">
    <h2>Job Alert: {len(jobs)} new matches</h2>
    <p>Search: <strong>{search_query}</strong></p>
    <table style="width:100%;border-collapse:collapse">{rows}</table>
    <hr><p style="color:#999;font-size:12px">Sent by Job Search Tool</p>
    </body></html>"""
