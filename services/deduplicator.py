import logging
import re
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher

logger = logging.getLogger(__name__)

STAFFING_PATTERNS = [
    r"\bstaffing\b", r"\brecruiting\b", r"\btalent\s+solutions?\b",
    r"\bconsultants?\b", r"\bcontract(?:ing|ors?)?\s+(?:services?|agency)\b",
    r"\bplacement\b", r"\btemporary\b", r"\bmanpower\b",
    r"\bheadhunt(?:er|ing)\b", r"\bpersonnel\b",
]


def deduplicate_cross_source(jobs, threshold=0.85):
    """Remove duplicates across sources, keeping the listing with the most complete description."""
    seen = []
    result = []

    for job in jobs:
        title = job["title"].lower().strip()
        company = job["company"].lower().strip()
        is_dup = False

        for i, (s_title, s_company) in enumerate(seen):
            title_sim = SequenceMatcher(None, title, s_title).ratio()
            company_sim = SequenceMatcher(None, company, s_company).ratio()

            if title_sim >= threshold and company_sim >= threshold:
                # Keep the one with more information
                if len(job.get("description", "")) > len(result[i].get("description", "")):
                    result[i] = job
                    seen[i] = (title, company)
                is_dup = True
                break

        if not is_dup:
            seen.append((title, company))
            result.append(job)

    removed = len(jobs) - len(result)
    if removed:
        logger.info("Deduplication removed %d duplicate listings", removed)
    return result


def flag_staleness(jobs, stale_days=30):
    """Flag jobs posted more than stale_days ago."""
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    for job in jobs:
        posted = job.get("posted_date", "")
        if posted:
            try:
                if "T" in posted:
                    posted_dt = datetime.fromisoformat(posted.replace("Z", "+00:00")).replace(tzinfo=None)
                else:
                    posted_dt = datetime.strptime(posted[:10], "%Y-%m-%d")
                age_days = (now - posted_dt).days
                job["age_days"] = age_days
                job["is_stale"] = age_days > stale_days
            except (ValueError, TypeError):
                job["age_days"] = None
                job["is_stale"] = False
        else:
            job["age_days"] = None
            job["is_stale"] = False
    return jobs


def flag_staffing_agencies(jobs):
    """Flag jobs from staffing agencies/recruiters."""
    for job in jobs:
        company = job.get("company", "").lower()
        desc = job.get("description", "").lower()[:200]
        text = f"{company} {desc}"

        job["is_staffing_agency"] = any(
            re.search(pattern, text) for pattern in STAFFING_PATTERNS
        )
    return jobs


def sort_within_tiers(jobs):
    """Sort jobs by posted date within each match tier, stale jobs at bottom."""
    def sort_key(job):
        tier_order = {"strong": 0, "possible": 1, "stretch": 2, "low": 3}
        tier = tier_order.get(job.get("match_tier", "low"), 3)
        stale = 1 if job.get("is_stale") else 0
        # Newer first (use negative score as tiebreaker)
        score = -(job.get("match_score", 0))
        return (tier, stale, score)

    jobs.sort(key=sort_key)
    return jobs
