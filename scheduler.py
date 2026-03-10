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


def init_scheduler(app):
    """Initialize the background scheduler for notification checks."""
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
    scheduler.start()
    logger.info("Scheduler started - checking alerts every hour")


def _cleanup(app):
    """Periodic cleanup of old data."""
    with app.app_context():
        try:
            purge_old_shared_jobs(days=30)
            purge_old_api_usage(days=90)
            logger.info("Cleanup completed")
        except Exception as e:
            logger.error("Cleanup failed: %s", e)


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
