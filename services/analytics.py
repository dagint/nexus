import logging
import re
from collections import Counter
from datetime import datetime, timedelta

from database import get_db
from services.constants import JOB_TITLE_STOP_WORDS as STOP_WORDS

logger = logging.getLogger(__name__)


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
        from database import _safe_close
        _safe_close(conn)


def get_response_rates(user_id):
    """Get response rate breakdown by source and by resume.

    Returns dict with:
    - total_applied: int
    - total_responded: int (moved past 'applied' stage)
    - overall_rate: float (percentage)
    - by_source: list of {source, applied, responded, rate}
    - by_resume: list of {resume_name, resume_id, applied, responded, rate}
    """
    conn = get_db()
    try:
        # Overall
        total_row = conn.execute(
            "SELECT COUNT(*) as cnt FROM applied_jobs WHERE user_id = ?",
            (user_id,),
        ).fetchone()
        total_applied = total_row["cnt"] if total_row else 0

        responded_row = conn.execute(
            "SELECT COUNT(*) as cnt FROM applied_jobs WHERE user_id = ? AND stage != 'applied'",
            (user_id,),
        ).fetchone()
        total_responded = responded_row["cnt"] if responded_row else 0

        overall_rate = (total_responded / total_applied * 100) if total_applied > 0 else 0.0

        # By source (via bookmarked_jobs join)
        source_rows = conn.execute(
            """SELECT COALESCE(b.source, 'Unknown') as source,
                      COUNT(*) as applied,
                      SUM(CASE WHEN a.stage != 'applied' THEN 1 ELSE 0 END) as responded
               FROM applied_jobs a
               LEFT JOIN bookmarked_jobs b ON a.user_id = b.user_id AND a.job_key = b.job_key
               WHERE a.user_id = ?
               GROUP BY source
               ORDER BY applied DESC""",
            (user_id,),
        ).fetchall()

        by_source = []
        for row in source_rows:
            applied = row["applied"]
            responded = row["responded"]
            by_source.append({
                "source": row["source"],
                "applied": applied,
                "responded": responded,
                "rate": round(responded / applied * 100, 1) if applied > 0 else 0.0,
            })

        # By resume (via resume_id on applied_jobs)
        resume_rows = conn.execute(
            """SELECT COALESCE(r.name, 'No Resume') as resume_name,
                      a.resume_id,
                      COUNT(*) as applied,
                      SUM(CASE WHEN a.stage != 'applied' THEN 1 ELSE 0 END) as responded
               FROM applied_jobs a
               LEFT JOIN resumes r ON a.resume_id = r.id
               WHERE a.user_id = ?
               GROUP BY a.resume_id
               ORDER BY applied DESC""",
            (user_id,),
        ).fetchall()

        by_resume = []
        for row in resume_rows:
            applied = row["applied"]
            responded = row["responded"]
            by_resume.append({
                "resume_name": row["resume_name"],
                "resume_id": row["resume_id"],
                "applied": applied,
                "responded": responded,
                "rate": round(responded / applied * 100, 1) if applied > 0 else 0.0,
            })

        return {
            "total_applied": total_applied,
            "total_responded": total_responded,
            "overall_rate": round(overall_rate, 1),
            "by_source": by_source,
            "by_resume": by_resume,
        }
    finally:
        from database import _safe_close
        _safe_close(conn)


def get_funnel_metrics(user_id):
    """Compute a hiring funnel from stage transitions.

    Returns dict with:
    - stages: list of {stage, count, median_days_to_next}
    - transitions: list of {from_stage, to_stage, count, median_days}
    """
    conn = get_db()
    try:
        # Count jobs currently at each stage
        stage_counts = conn.execute(
            "SELECT stage, COUNT(*) as cnt FROM applied_jobs WHERE user_id = ? GROUP BY stage",
            (user_id,),
        ).fetchall()
        stage_count_map = {r["stage"]: r["cnt"] for r in stage_counts}

        # Get all transitions to compute time between stages
        transitions = conn.execute(
            """SELECT from_stage, to_stage,
                      julianday(transitioned_at) as trans_day,
                      job_key
               FROM stage_transitions
               WHERE user_id = ?
               ORDER BY job_key, transitioned_at ASC""",
            (user_id,),
        ).fetchall()

        # Group transitions by (from_stage, to_stage) to compute median days
        from collections import defaultdict
        transition_days = defaultdict(list)
        prev_by_job = {}

        for t in transitions:
            job_key = t["job_key"]
            if job_key in prev_by_job:
                prev_day = prev_by_job[job_key]
                days = t["trans_day"] - prev_day
                if days >= 0:
                    fs = t["from_stage"] or "new"
                    ts = t["to_stage"]
                    transition_days[(fs, ts)].append(days)
            prev_by_job[job_key] = t["trans_day"]

        # Build transitions summary
        import statistics as _stats
        transition_summary = []
        for (fs, ts), days_list in transition_days.items():
            median_d = round(_stats.median(days_list), 1) if days_list else 0
            transition_summary.append({
                "from_stage": fs,
                "to_stage": ts,
                "count": len(days_list),
                "median_days": median_d,
            })

        # Ordered stage pipeline for the funnel
        from database import PIPELINE_STAGES
        ordered_stages = ["saved"] + PIPELINE_STAGES

        # Build funnel: count how many jobs reached each stage (cumulative)
        stage_reached = defaultdict(int)
        job_max_stage = {}

        # Get all stage transition records to find max stage per job
        all_jobs = conn.execute(
            "SELECT job_key, stage FROM applied_jobs WHERE user_id = ?",
            (user_id,),
        ).fetchall()

        for job in all_jobs:
            stage = job["stage"]
            if stage in ordered_stages:
                idx = ordered_stages.index(stage)
                # This job reached at least this stage and all prior
                for s in ordered_stages[:idx + 1]:
                    stage_reached[s] += 1

        # Build funnel data
        stages_data = []
        for i, stage in enumerate(ordered_stages):
            count = stage_reached.get(stage, stage_count_map.get(stage, 0))
            # Find median days to next stage
            median_to_next = None
            if i < len(ordered_stages) - 1:
                next_stage = ordered_stages[i + 1]
                for ts in transition_summary:
                    if ts["from_stage"] == stage and ts["to_stage"] == next_stage:
                        median_to_next = ts["median_days"]
                        break

            stages_data.append({
                "stage": stage,
                "count": count,
                "median_days_to_next": median_to_next,
            })

        return {
            "stages": stages_data,
            "transitions": transition_summary,
        }
    finally:
        from database import _safe_close
        _safe_close(conn)
