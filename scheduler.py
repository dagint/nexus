import json
import logging
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from apscheduler.schedulers.background import BackgroundScheduler

from database import (
    get_all_saved_searches, get_seen_job_keys, add_seen_jobs, update_last_notified,
    purge_old_shared_jobs, purge_old_api_usage, get_user_email_count_today,
)

logger = logging.getLogger(__name__)

scheduler = BackgroundScheduler()

MAX_EMAILS_PER_USER_PER_DAY = 2


def shutdown_scheduler():
    """Gracefully shut down the scheduler if running."""
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("Scheduler shut down")


def init_scheduler(app):
    """Initialize the background scheduler for notification checks."""
    import atexit
    atexit.register(shutdown_scheduler)

    scheduler.add_job(
        func=lambda: _check_alerts(app),
        trigger="interval",
        hours=1,
        id="check_alerts",
        replace_existing=True,
    )
    scheduler.add_job(
        func=lambda: _cleanup(app),
        trigger="interval",
        hours=24,
        id="cleanup",
        replace_existing=True,
    )
    scheduler.add_job(
        func=lambda: _check_follow_ups(app),
        trigger="interval",
        hours=24,
        id="check_follow_ups",
        replace_existing=True,
    )
    scheduler.add_job(
        func=lambda: _send_weekly_reports(app),
        trigger="cron",
        day_of_week="mon",
        hour=9,
        minute=0,
        id="weekly_reports",
        replace_existing=True,
    )
    scheduler.start()
    logger.info("Scheduler started - checking alerts every hour, follow-ups daily, weekly reports Mondays 9 AM")


def _cleanup(app):
    """Periodic cleanup of old data."""
    with app.app_context():
        try:
            purge_old_shared_jobs(days=30)
            purge_old_api_usage(days=90)
            logger.info("Cleanup completed")
        except Exception as e:
            logger.error("Cleanup failed: %s", e)


def _check_follow_ups(app):
    """Check for due follow-ups and create in-app notifications."""
    with app.app_context():
        try:
            from database import get_due_follow_ups, create_notification

            due = get_due_follow_ups(days_ahead=0)  # Overdue and due today
            today = datetime.utcnow().strftime("%Y-%m-%d")

            # Group by user
            user_followups = defaultdict(list)
            for row in due:
                user_followups[row["user_id"]].append(row)

            for user_id, followups in user_followups.items():
                for fu in followups:
                    is_overdue = fu["follow_up_date"] < today
                    prefix = "OVERDUE" if is_overdue else "Due today"
                    message = f"{prefix}: Follow up on {fu['title']} at {fu['company']} (scheduled {fu['follow_up_date']})"
                    create_notification(
                        user_id,
                        message=message,
                        link="/pipeline",
                    )

                # Optionally send email if SMTP configured
                if followups:
                    _send_follow_up_email(followups[0]["email"], followups, app)

            if due:
                logger.info("Created follow-up notifications for %d users", len(user_followups))
        except Exception as e:
            logger.error("Follow-up check failed: %s", e)


def _send_follow_up_email(email, followups, app):
    """Send an email reminder for due follow-ups (best-effort)."""
    try:
        from services.notifier import _smtp_configured, _send_email
        from email.mime.multipart import MIMEMultipart
        from email.mime.text import MIMEText
        from html import escape
        from config import Config

        if not _smtp_configured():
            return

        today = datetime.utcnow().strftime("%Y-%m-%d")
        parts = []
        for fu in followups[:10]:
            is_overdue = fu["follow_up_date"] < today
            status = '<span style="color:red;font-weight:bold">OVERDUE</span>' if is_overdue else '<span style="color:orange">Due Today</span>'
            parts.append(f"""
            <tr>
                <td style="padding:8px;border-bottom:1px solid #eee">
                    {status}<br>
                    <strong>{escape(fu.get('title', ''))}</strong> at {escape(fu.get('company', ''))}<br>
                    <small>Follow-up scheduled: {escape(fu.get('follow_up_date', ''))}</small>
                </td>
            </tr>""")

        rows = "".join(parts)
        html = f"""
        <html><head><style>
        @media (prefers-color-scheme: dark) {{
            body {{ background-color: #1a1a2e !important; color: #e0e0e0 !important; }}
            h2 {{ color: #e0e0e0 !important; }}
            td {{ border-bottom-color: #2a2a4a !important; }}
        }}
        </style></head>
        <body style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto;background-color:#ffffff;color:#333333">
        <h2>Follow-up Reminder: {len(followups)} application(s)</h2>
        <p>The following applications need follow-up:</p>
        <table style="width:100%;border-collapse:collapse">{rows}</table>
        <p><a href="#" style="color:#007bff">Go to Pipeline</a></p>
        <hr><p style="color:#999;font-size:12px">Sent by Nexus</p>
        </body></html>"""

        msg = MIMEMultipart("alternative")
        msg["Subject"] = f"Follow-up Reminder: {len(followups)} application(s) need attention"
        msg["From"] = Config.SMTP_FROM
        msg["To"] = email
        msg.attach(MIMEText(html, "html"))
        _send_email(msg)
        logger.info("Sent follow-up reminder to %s for %d items", email, len(followups))

    except Exception as e:
        logger.warning("Failed to send follow-up email to %s: %s", email, e)


def _check_alerts(app):
    """Check all active saved searches and send consolidated digests per user.

    Email throttling: max MAX_EMAILS_PER_USER_PER_DAY emails per user per 24h.
    Multiple alerts for the same user are consolidated into a single digest.
    """
    from services.job_search import search_all
    from services.job_analyzer import analyze_jobs
    from services.job_matcher import score_jobs
    from services.deduplicator import flag_staleness, flag_staffing_agencies
    from services.company_enricher import enrich_jobs
    from services.notifier import send_consolidated_digest

    logger.info("Running alert check")

    with app.app_context():
        searches = get_all_saved_searches()
        now = datetime.now(timezone.utc).replace(tzinfo=None)

        # Group searches by user
        user_searches = defaultdict(list)
        for search in searches:
            user_searches[search["user_id"]].append(search)

        for user_id, user_alerts in user_searches.items():
            # Check per-user email throttle
            emails_sent_today = get_user_email_count_today(user_id)
            if emails_sent_today >= MAX_EMAILS_PER_USER_PER_DAY:
                logger.info("User %d already received %d emails today, skipping",
                            user_id, emails_sent_today)
                continue

            email = user_alerts[0]["email"]

            # Collect new jobs across all of this user's alerts
            all_new_jobs = []
            all_still_open = []
            triggered_search_ids = []
            search_queries = []

            for search in user_alerts:
                last = search["last_notified_at"]
                frequency = search["frequency"]

                if last:
                    last_dt = datetime.fromisoformat(last) if isinstance(last, str) else last
                    if frequency == "daily" and (now - last_dt) < timedelta(hours=24):
                        continue
                    if frequency == "weekly" and (now - last_dt) < timedelta(days=7):
                        continue

                try:
                    query = search["query"]
                    location = search["location"] or ""
                    remote_only = bool(search["remote_only"])

                    jobs = search_all(query, location, remote_only)
                    jobs = analyze_jobs(jobs)

                    skills_data = json.loads(search["skills_json"]) if search["skills_json"] else None
                    if skills_data:
                        jobs = score_jobs(jobs, skills_data)

                    jobs = flag_staleness(jobs)
                    jobs = flag_staffing_agencies(jobs)

                    try:
                        jobs = enrich_jobs(jobs)
                    except Exception as e:
                        logger.warning("Enrichment failed in alert: %s", e)

                    # Filter to non-stale, non-staffing jobs for higher quality
                    quality_jobs = [
                        j for j in jobs
                        if not j.get("is_stale") and not j.get("is_staffing_agency")
                    ]

                    seen_keys = get_seen_job_keys(search["id"])
                    new_jobs = [j for j in quality_jobs if j["job_key"] not in seen_keys]
                    still_open = [j for j in quality_jobs if j["job_key"] in seen_keys][:5]

                    if new_jobs:
                        # Tag each job with the alert query for grouping in email
                        for job in new_jobs:
                            job["_alert_query"] = query
                        all_new_jobs.extend(new_jobs)
                        all_still_open.extend(still_open)
                        search_queries.append(query)

                    # Always record seen jobs and update timestamp
                    all_job_keys = [j["job_key"] for j in jobs]
                    if all_job_keys:
                        add_seen_jobs(search["id"], all_job_keys)
                    triggered_search_ids.append(search["id"])

                except Exception as e:
                    logger.error("Alert check failed for search %s: %s", search["id"], e)

            # Trigger webhooks for new matches (fire-and-forget)
            if all_new_jobs:
                try:
                    from services.webhook_sender import trigger_webhooks
                    webhook_payload = {
                        "user_id": user_id,
                        "new_job_count": len(all_new_jobs),
                        "jobs": [
                            {
                                "title": j.get("title", ""),
                                "company": j.get("company", ""),
                                "location": j.get("location", ""),
                                "apply_url": j.get("apply_url", ""),
                                "match_score": j.get("match_score"),
                                "source": j.get("source", ""),
                            }
                            for j in all_new_jobs[:20]  # Limit payload size
                        ],
                    }
                    trigger_webhooks(user_id, "new_matches", webhook_payload)
                except Exception as e:
                    logger.warning("Failed to trigger webhooks for user %d: %s", user_id, e)

            # Send one consolidated digest for this user
            if all_new_jobs:
                # Deduplicate jobs across alerts (same job may match multiple alerts)
                seen_job_keys = set()
                unique_new_jobs = []
                for job in all_new_jobs:
                    if job["job_key"] not in seen_job_keys:
                        seen_job_keys.add(job["job_key"])
                        unique_new_jobs.append(job)

                # Sort by match score descending for actionability
                unique_new_jobs.sort(
                    key=lambda j: j.get("match_score", 0), reverse=True
                )

                combined_query = " | ".join(search_queries)
                send_consolidated_digest(
                    email, unique_new_jobs, search_queries, app,
                    still_open_jobs=all_still_open[:10],
                )

                # Mark all triggered searches as notified
                for sid in triggered_search_ids:
                    update_last_notified(sid)

                logger.info("Sent consolidated digest with %d jobs for %d alerts to %s",
                            len(unique_new_jobs), len(search_queries), email)
            else:
                logger.info("No new jobs for user %d across %d alerts",
                            user_id, len(user_alerts))


def _send_weekly_reports(app):
    """Send weekly progress reports to all opted-in users."""
    with app.app_context():
        try:
            from database import get_weekly_report_users, get_user_weekly_stats
            from services.notifier import send_weekly_report

            users = get_weekly_report_users()
            sent = 0
            for user in users:
                try:
                    stats = get_user_weekly_stats(user["id"])
                    send_weekly_report(user["email"], stats, app)
                    sent += 1
                except Exception as e:
                    logger.warning("Failed to send weekly report to user %d: %s",
                                   user["id"], e)

            logger.info("Sent weekly reports to %d/%d users", sent, len(users))
        except Exception as e:
            logger.error("Weekly report job failed: %s", e)
