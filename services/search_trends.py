"""Search history trends and analytics."""
import logging
from collections import Counter
from datetime import datetime, timedelta

from database import get_db, _safe_close

logger = logging.getLogger(__name__)


def get_search_trends(user_id, query=None, days=90):
    """Get search trend data: result counts over time, salary movement.

    Returns dict with:
    - volume_by_date: list of {date, count, avg_results}
    - salary_trend: list of {date, avg_salary} (if salary data is available)
    - total_searches: int
    """
    conn = get_db()
    try:
        params = [user_id, f"-{days} days"]
        query_filter = ""
        if query:
            query_filter = " AND sh.query LIKE ?"
            params.append(f"%{query}%")

        # Volume by date
        volume_rows = conn.execute(
            f"""SELECT DATE(sh.searched_at) as date,
                       COUNT(*) as search_count,
                       AVG(sh.result_count) as avg_results,
                       AVG(sh.avg_salary) as avg_salary
                FROM search_history sh
                WHERE sh.user_id = ?
                  AND sh.searched_at >= datetime('now', ?)
                  {query_filter}
                GROUP BY DATE(sh.searched_at)
                ORDER BY date ASC""",
            params,
        ).fetchall()

        volume_by_date = []
        salary_trend = []
        total_searches = 0
        for row in volume_rows:
            d = dict(row)
            total_searches += d["search_count"]
            volume_by_date.append({
                "date": d["date"],
                "count": d["search_count"],
                "avg_results": round(d["avg_results"] or 0, 1),
            })
            if d.get("avg_salary") and d["avg_salary"] > 0:
                salary_trend.append({
                    "date": d["date"],
                    "avg_salary": round(d["avg_salary"]),
                })

        return {
            "volume_by_date": volume_by_date,
            "salary_trend": salary_trend,
            "total_searches": total_searches,
        }
    finally:
        _safe_close(conn)


def get_popular_searches(user_id, limit=10):
    """Get the most frequent search queries with stats.

    Returns list of {query, count, avg_results, last_searched, avg_salary}.
    """
    conn = get_db()
    try:
        rows = conn.execute(
            """SELECT query,
                      COUNT(*) as count,
                      AVG(result_count) as avg_results,
                      MAX(searched_at) as last_searched,
                      AVG(avg_salary) as avg_salary
               FROM search_history
               WHERE user_id = ?
               GROUP BY LOWER(query)
               ORDER BY count DESC
               LIMIT ?""",
            (user_id, limit),
        ).fetchall()

        return [
            {
                "query": row["query"],
                "count": row["count"],
                "avg_results": round(row["avg_results"] or 0, 1),
                "last_searched": row["last_searched"],
                "avg_salary": round(row["avg_salary"]) if row["avg_salary"] and row["avg_salary"] > 0 else None,
            }
            for row in rows
        ]
    finally:
        _safe_close(conn)
