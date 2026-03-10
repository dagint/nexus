"""Salary intelligence: aggregation and market comparison from user's job data."""
import logging
import statistics

logger = logging.getLogger(__name__)


def get_salary_insights(user_id, role_query=None, location=None):
    """Aggregate salary data from the user's salary_data table.

    Returns a dict with:
    - median, p25, p75, min, max, sample_size
    - by_source: {source: {median, count}}
    - by_company: [{company, salary_min, salary_max}] (top entries)
    """
    from database import get_db, _safe_close

    conn = get_db()
    params = [user_id]
    where = ["user_id = ?"]

    if role_query:
        where.append("role_query LIKE ?")
        params.append(f"%{role_query}%")
    if location:
        where.append("(location LIKE ? OR location IS NULL)")
        params.append(f"%{location}%")

    where_clause = " AND ".join(where)

    rows = conn.execute(
        f"SELECT * FROM salary_data WHERE {where_clause} ORDER BY recorded_at DESC LIMIT 500",
        params,
    ).fetchall()
    _safe_close(conn)

    if not rows:
        return {
            "median": None, "p25": None, "p75": None,
            "min": None, "max": None, "sample_size": 0,
            "by_source": {}, "by_company": [],
        }

    # Collect salary midpoints
    midpoints = []
    by_source = {}
    by_company = {}

    for row in rows:
        row_dict = dict(row)
        sal_min = row_dict.get("salary_min") or 0
        sal_max = row_dict.get("salary_max") or 0

        if sal_min <= 0 and sal_max <= 0:
            continue

        mid = (sal_min + sal_max) / 2 if sal_min > 0 and sal_max > 0 else max(sal_min, sal_max)
        midpoints.append(mid)

        source = row_dict.get("source", "Unknown")
        if source not in by_source:
            by_source[source] = []
        by_source[source].append(mid)

        company = row_dict.get("company", "Unknown")
        if company not in by_company:
            by_company[company] = {"salary_min": sal_min, "salary_max": sal_max}
        else:
            if sal_min > 0:
                by_company[company]["salary_min"] = max(by_company[company]["salary_min"], sal_min)
            if sal_max > 0:
                by_company[company]["salary_max"] = max(by_company[company]["salary_max"], sal_max)

    if not midpoints:
        return {
            "median": None, "p25": None, "p75": None,
            "min": None, "max": None, "sample_size": 0,
            "by_source": {}, "by_company": [],
        }

    midpoints.sort()
    n = len(midpoints)

    result = {
        "median": round(statistics.median(midpoints)),
        "p25": round(midpoints[n // 4]) if n >= 4 else round(midpoints[0]),
        "p75": round(midpoints[3 * n // 4]) if n >= 4 else round(midpoints[-1]),
        "min": round(min(midpoints)),
        "max": round(max(midpoints)),
        "sample_size": n,
        "by_source": {},
        "by_company": [],
    }

    # Aggregate by source
    for source, vals in by_source.items():
        result["by_source"][source] = {
            "median": round(statistics.median(vals)),
            "count": len(vals),
        }

    # Top companies by salary
    company_list = [
        {"company": c, "salary_min": round(v["salary_min"]), "salary_max": round(v["salary_max"])}
        for c, v in by_company.items()
        if v["salary_max"] > 0
    ]
    company_list.sort(key=lambda x: x["salary_max"], reverse=True)
    result["by_company"] = company_list[:20]

    return result


def record_salary_from_jobs(user_id, jobs, role_query, location=None):
    """Record salary data from search results into the salary_data table."""
    from database import get_db, _safe_close

    records = []
    for job in jobs:
        sal_min = job.get("salary_min") or job.get("salary_annual_min")
        sal_max = job.get("salary_max") or job.get("salary_annual_max")
        if not sal_min and not sal_max:
            continue
        records.append((
            user_id,
            role_query,
            location or job.get("location", ""),
            sal_min,
            sal_max,
            job.get("source", ""),
            job.get("company", ""),
        ))

    if not records:
        return 0

    conn = get_db()
    conn.executemany(
        """INSERT INTO salary_data (user_id, role_query, location, salary_min, salary_max, source, company)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        records,
    )
    conn.commit()
    _safe_close(conn)
    return len(records)


def get_salary_badge(job, user_id, role_query=None):
    """Return a salary comparison badge for a job: 'Above Market', 'Below Market', 'At Market', or None."""
    sal_min = job.get("salary_min") or job.get("salary_annual_min")
    sal_max = job.get("salary_max") or job.get("salary_annual_max")
    if not sal_min and not sal_max:
        return None

    mid = (sal_min + sal_max) / 2 if sal_min and sal_max else (sal_min or sal_max)

    insights = get_salary_insights(user_id, role_query=role_query)
    if not insights.get("median") or insights["sample_size"] < 3:
        return None

    median = insights["median"]
    if mid > median * 1.1:
        return "Above Market"
    elif mid < median * 0.9:
        return "Below Market"
    else:
        return "At Market"
