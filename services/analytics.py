import logging
import re
from collections import Counter
from datetime import datetime, timedelta

from database import get_db

logger = logging.getLogger(__name__)

# Common filler words to exclude from skill extraction
STOP_WORDS = {
    "the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "by", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "shall", "can", "need", "must", "not", "no",
    "we", "you", "he", "she", "it", "they", "i", "me", "my", "our",
    "your", "his", "her", "its", "their", "this", "that", "these", "those",
    "from", "up", "about", "into", "through", "during", "before", "after",
    "above", "below", "between", "out", "off", "over", "under", "again",
    "further", "then", "once", "here", "there", "when", "where", "why",
    "how", "all", "each", "every", "both", "few", "more", "most", "other",
    "some", "such", "only", "own", "same", "so", "than", "too", "very",
    "just", "because", "as", "if", "while", "also", "new", "one", "two",
    "three", "first", "last", "long", "great", "little", "right", "big",
    "high", "old", "small", "large", "next", "early", "young", "important",
    "public", "bad", "good", "best", "well", "way", "who", "what",
    "which", "much", "many", "any",
    # Job-specific filler words
    "senior", "junior", "lead", "principal", "staff", "engineer", "developer",
    "manager", "director", "analyst", "specialist", "coordinator", "associate",
    "intern", "consultant", "architect", "administrator", "officer",
    "remote", "hybrid", "onsite", "full-time", "part-time", "contract",
}


def _extract_title_words(title):
    """Extract meaningful words from a job title for skill counting."""
    if not title:
        return []
    words = re.findall(r"[a-zA-Z+#]+", title.lower())
    return [w for w in words if w not in STOP_WORDS and len(w) > 1]


def get_search_analytics(user_id):
    """Get comprehensive analytics for a user's job search.

    Returns dict with:
        - total_applications: int
        - applications_by_stage: dict (stage -> count)
        - applications_by_week: list of {"week": str, "count": int} (last 12 weeks)
        - response_rate: float (% that moved past 'applied' stage)
        - avg_time_to_response: float (days, for jobs that got responses)
        - top_skills_in_applied: list of {"skill": str, "count": int} (most common skills in applied jobs)
        - sources_breakdown: dict (source -> count of applications)
        - bookmarks_count: int
        - searches_count: int
        - active_alerts: int
    """
    conn = get_db()
    try:
        # Total applications
        row = conn.execute(
            "SELECT COUNT(*) as cnt FROM applied_jobs WHERE user_id = ?",
            (user_id,),
        ).fetchone()
        total_applications = row["cnt"] if row else 0

        # Applications by stage
        stage_rows = conn.execute(
            "SELECT stage, COUNT(*) as cnt FROM applied_jobs WHERE user_id = ? GROUP BY stage",
            (user_id,),
        ).fetchall()
        applications_by_stage = {r["stage"]: r["cnt"] for r in stage_rows}

        # Applications by week (last 12 weeks)
        week_rows = conn.execute(
            """SELECT strftime('%%Y-W%%W', applied_at) as week, COUNT(*) as cnt
               FROM applied_jobs
               WHERE user_id = ?
                 AND applied_at >= date('now', '-84 days')
               GROUP BY week
               ORDER BY week ASC""",
            (user_id,),
        ).fetchall()
        applications_by_week = [{"week": r["week"], "count": r["cnt"]} for r in week_rows]

        # Response rate: jobs that moved past 'applied'
        if total_applications > 0:
            responded_row = conn.execute(
                "SELECT COUNT(*) as cnt FROM applied_jobs WHERE user_id = ? AND stage != 'applied'",
                (user_id,),
            ).fetchone()
            responded = responded_row["cnt"] if responded_row else 0
            response_rate = (responded / total_applications) * 100
        else:
            response_rate = 0.0

        # Average time to response (days between applied_at and updated_at for non-applied stages)
        avg_row = conn.execute(
            """SELECT AVG(julianday(updated_at) - julianday(applied_at)) as avg_days
               FROM applied_jobs
               WHERE user_id = ? AND stage != 'applied'
                 AND updated_at IS NOT NULL AND applied_at IS NOT NULL""",
            (user_id,),
        ).fetchone()
        avg_time_to_response = round(avg_row["avg_days"], 1) if avg_row and avg_row["avg_days"] else 0.0

        # Top skills in applied jobs (word frequency from titles)
        title_rows = conn.execute(
            "SELECT title FROM applied_jobs WHERE user_id = ?",
            (user_id,),
        ).fetchall()
        word_counter = Counter()
        for r in title_rows:
            words = _extract_title_words(r["title"])
            word_counter.update(words)
        top_skills_in_applied = [
            {"skill": skill, "count": count}
            for skill, count in word_counter.most_common(10)
        ]

        # Sources breakdown - applied_jobs doesn't have a source column,
        # so try to join with bookmarked_jobs for source info, otherwise report "unknown"
        source_rows = conn.execute(
            """SELECT COALESCE(b.source, 'unknown') as source, COUNT(*) as cnt
               FROM applied_jobs a
               LEFT JOIN bookmarked_jobs b ON a.user_id = b.user_id AND a.job_key = b.job_key
               WHERE a.user_id = ?
               GROUP BY source""",
            (user_id,),
        ).fetchall()
        sources_breakdown = {r["source"]: r["cnt"] for r in source_rows}

        # Bookmarks count
        bm_row = conn.execute(
            "SELECT COUNT(*) as cnt FROM bookmarked_jobs WHERE user_id = ?",
            (user_id,),
        ).fetchone()
        bookmarks_count = bm_row["cnt"] if bm_row else 0

        # Searches count
        sh_row = conn.execute(
            "SELECT COUNT(*) as cnt FROM search_history WHERE user_id = ?",
            (user_id,),
        ).fetchone()
        searches_count = sh_row["cnt"] if sh_row else 0

        # Active alerts (saved searches)
        alerts_row = conn.execute(
            "SELECT COUNT(*) as cnt FROM saved_searches WHERE user_id = ?",
            (user_id,),
        ).fetchone()
        active_alerts = alerts_row["cnt"] if alerts_row else 0

        return {
            "total_applications": total_applications,
            "applications_by_stage": applications_by_stage,
            "applications_by_week": applications_by_week,
            "response_rate": round(response_rate, 1),
            "avg_time_to_response": avg_time_to_response,
            "top_skills_in_applied": top_skills_in_applied,
            "sources_breakdown": sources_breakdown,
            "bookmarks_count": bookmarks_count,
            "searches_count": searches_count,
            "active_alerts": active_alerts,
        }
    finally:
        conn.close()
