import json
import logging
from datetime import datetime, timedelta, timezone

from apscheduler.schedulers.background import BackgroundScheduler

from database import (
    get_all_saved_searches, get_seen_job_keys, add_seen_jobs, update_last_notified,
)

logger = logging.getLogger(__name__)

scheduler = BackgroundScheduler()


def init_scheduler(app):
    """Initialize the background scheduler for notification checks."""
    scheduler.add_job(
        func=lambda: _check_alerts(app),
        trigger="interval",
        hours=1,
        id="check_alerts",
        replace_existing=True,
    )
    scheduler.start()
    logger.info("Scheduler started - checking alerts every hour")


def _check_alerts(app):
    """Check all saved searches across all users and send notifications."""
    from services.job_search import search_all
    from services.job_analyzer import analyze_jobs
    from services.job_matcher import score_jobs
    from services.deduplicator import flag_staleness, flag_staffing_agencies
    from services.company_enricher import enrich_jobs
    from services.notifier import send_digest

    logger.info("Running alert check")
    searches = get_all_saved_searches()
    now = datetime.now(timezone.utc).replace(tzinfo=None)

    for search in searches:
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
            email = search["email"]

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

            seen_keys = get_seen_job_keys(search["id"])
            new_jobs = [j for j in jobs if j["job_key"] not in seen_keys]
            still_open = [j for j in jobs if j["job_key"] in seen_keys][:10]

            if new_jobs:
                send_digest(email, new_jobs, query, app, still_open_jobs=still_open)
                add_seen_jobs(search["id"], [j["job_key"] for j in new_jobs])
                update_last_notified(search["id"])
                logger.info("Sent %d new jobs for search '%s' to %s",
                            len(new_jobs), query, email)
            else:
                logger.info("No new jobs for search '%s'", query)

        except Exception as e:
            logger.error("Alert check failed for search %s: %s", search["id"], e)
