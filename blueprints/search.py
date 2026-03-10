import csv
import io
import json
import logging
import os
import re

from flask import Blueprint, render_template, request, redirect, url_for, flash, Response
from flask_login import login_required, current_user

from config import Config
from database import (
    get_resumes, get_resume, save_resume, update_resume, save_resume_version,
    get_user_settings, get_applied_job_keys, get_bookmarked_job_keys,
    get_dismissed_job_keys, get_search_history,
    add_search_history_with_salary,
    get_role_velocities_batch,
)

logger = logging.getLogger(__name__)

RESULTS_PER_PAGE = 20

search_bp = Blueprint("search", __name__)


def init_search_limiter(limiter):
    """Apply rate limits to search routes. Called during blueprint registration."""
    limiter.limit("5 per minute")(search)


def _safe_int(value, default=0):
    """Safely convert a value to int, returning default on failure."""
    try:
        return int(value)
    except (ValueError, TypeError):
        return default


@search_bp.route("/search", methods=["GET", "POST"])
def search():
    from services.resume_parser import parse_resume
    from services.skills_extractor import extract_keywords, extract_keywords_smart
    from services.job_search import search_all
    from services.job_analyzer import analyze_jobs
    from services.job_matcher import score_jobs, generate_match_summary
    from services.deduplicator import (
        deduplicate_cross_source, flag_staleness, flag_staffing_agencies, sort_within_tiers,
    )
    from services.salary_normalizer import normalize_salary
    from services.company_enricher import enrich_jobs

    resume_text = ""
    resume_data = {}
    query = ""
    location = ""
    remote_only = False
    date_posted = "month"
    employment_type = ""
    use_ai = False
    resume_id = None

    if request.method == "POST":
        # Check for saved resume
        saved_resume_id = request.form.get("saved_resume_id", "")
        if saved_resume_id and current_user.is_authenticated:
            saved = get_resume(int(saved_resume_id), current_user.id)
            if saved:
                resume_text = saved["raw_text"]
                resume_id = saved["id"]
                # Use cached skills if available
                if saved.get("skills_json"):
                    resume_data = json.loads(saved["skills_json"])

        # File upload overrides saved resume
        file = request.files.get("resume_file")
        text = request.form.get("resume_text", "")

        if file and file.filename:
            ext = os.path.splitext(file.filename)[1].lower()
            if ext not in Config.ALLOWED_EXTENSIONS:
                flash("Invalid file type. Only PDF and DOCX are supported.", "error")
                return redirect(url_for("index"))
            try:
                resume_text = parse_resume(file=file)
                resume_data = {}  # Re-extract since this is new text
            except ValueError as e:
                flash(str(e), "error")
                return redirect(url_for("index"))
        elif text.strip() and not resume_text:
            resume_text = parse_resume(text=text)

        query = request.form.get("query", "").strip()
        location = request.form.get("location", "").strip()
        remote_only = bool(request.form.get("remote_only"))
        date_posted = request.form.get("date_posted", "month")
        employment_type = request.form.get("employment_type", "")
        use_ai = bool(request.form.get("use_ai"))

        # Save resume if user is logged in and uploaded new one
        if resume_text and current_user.is_authenticated and not saved_resume_id:
            if file and file.filename:
                save_resume(current_user.id, resume_text, name=file.filename, filename=file.filename)
            elif text.strip():
                save_resume(current_user.id, resume_text, name="Pasted Resume")
    else:
        query = request.args.get("query", "").strip()
        location = request.args.get("location", "").strip()
        remote_only = request.args.get("remote_only") == "true"
        date_posted = request.args.get("date_posted", "month")
        employment_type = request.args.get("employment_type", "")

        # Use saved resume for GET re-searches
        if current_user.is_authenticated and not resume_data:
            from services.resume_loader import load_resume_or_empty
            loaded = load_resume_or_empty(current_user.id)
            if loaded["text"]:
                resume_text = loaded["text"]
                resume_id = loaded["id"]
                resume_data = loaded["data"]

    # Extract skills if not already loaded from cache
    if resume_text and not resume_data:
        if use_ai:
            resume_data = extract_keywords_smart(resume_text)
        else:
            resume_data = extract_keywords(resume_text)
        # Cache skills on resume
        if current_user.is_authenticated and resume_id:
            update_resume(resume_id, current_user.id, resume_text, json.dumps(resume_data))
            save_resume_version(resume_id, current_user.id, resume_text, json.dumps(resume_data), "Auto-saved from search")

    # Build search query from resume if none provided
    if not query:
        if resume_data.get("job_titles"):
            query = resume_data["job_titles"][0]
        elif resume_data.get("skills"):
            skills = resume_data["skills"]
            if skills and isinstance(skills[0], dict):
                query = " ".join(s["skill"] for s in skills[:3])
            else:
                query = " ".join(skills[:3])

    if not query:
        flash("Please provide a resume or enter search keywords.", "warning")
        return redirect(url_for("index"))

    # Search
    try:
        jobs = search_all(query, location, remote_only, date_posted, employment_type=employment_type)
    except Exception as e:
        logger.error("Search failed: %s", e)
        flash("Search encountered an error. Some results may be missing.", "warning")
        jobs = []

    # Analyze
    jobs = analyze_jobs(jobs)

    # Normalize salaries
    for job in jobs:
        salary_info = normalize_salary(
            job.get("salary_min"), job.get("salary_max"), job.get("description", "")
        )
        job["salary_annual_min"] = salary_info.get("salary_annual_min")
        job["salary_annual_max"] = salary_info.get("salary_annual_max")
        job["salary_period"] = salary_info.get("salary_period", "annual")
        # Backfill missing salary from description extraction
        if not job.get("salary_min") and salary_info.get("salary_min"):
            job["salary_min"] = salary_info["salary_min"]
            job["salary_max"] = salary_info.get("salary_max")

    jobs = deduplicate_cross_source(jobs)
    jobs = flag_staleness(jobs)
    jobs = flag_staffing_agencies(jobs)

    # Enrich company data (cached, 7-day TTL)
    try:
        jobs = enrich_jobs(jobs)
    except Exception as e:
        logger.warning("Company enrichment failed: %s", e)

    # Fetch user settings once for commute + scoring + filtering
    user_settings = None
    if current_user.is_authenticated:
        user_settings = get_user_settings(current_user.id)

    # Apply negative filters (blocked keywords, locations, companies)
    if user_settings:
        # Parse blocked companies
        blocked_companies_raw = user_settings.get("blocked_companies", "") or ""
        blocked_companies = [c.strip().lower() for c in blocked_companies_raw.split(",") if c.strip()]

        # Parse blocked keywords
        blocked_keywords_raw = user_settings.get("blocked_keywords", "") or "[]"
        if blocked_keywords_raw.startswith("["):
            try:
                blocked_keywords = [k.strip().lower() for k in json.loads(blocked_keywords_raw) if k.strip()]
            except (json.JSONDecodeError, TypeError):
                blocked_keywords = []
        else:
            blocked_keywords = [k.strip().lower() for k in blocked_keywords_raw.split(",") if k.strip()]

        # Parse blocked locations
        blocked_locations_raw = user_settings.get("blocked_locations", "") or "[]"
        if blocked_locations_raw.startswith("["):
            try:
                blocked_locations = [l.strip().lower() for l in json.loads(blocked_locations_raw) if l.strip()]
            except (json.JSONDecodeError, TypeError):
                blocked_locations = []
        else:
            blocked_locations = [l.strip().lower() for l in blocked_locations_raw.split(",") if l.strip()]

        if blocked_companies or blocked_keywords or blocked_locations:
            filtered = []
            for job in jobs:
                title_lower = (job.get("title") or "").lower()
                desc_lower = (job.get("description") or "").lower()
                company_lower = (job.get("company") or "").lower()
                location_lower = (job.get("location") or "").lower()

                # Check blocked companies
                if any(bc in company_lower for bc in blocked_companies):
                    continue
                # Check blocked keywords in title or description
                if any(bk in title_lower or bk in desc_lower for bk in blocked_keywords):
                    continue
                # Check blocked locations (partial match)
                if any(bl in location_lower for bl in blocked_locations):
                    continue
                filtered.append(job)
            jobs = filtered

    # Commute check for non-remote jobs
    if user_settings and location:
        try:
            from services.commute_checker import check_commute_for_jobs
            max_commute = user_settings.get("max_commute_minutes", 60)
            jobs = check_commute_for_jobs(jobs, location, max_commute)
        except Exception as e:
            logger.warning("Commute check failed: %s", e)

    # Score and tier
    user_prefs = {}
    preference_profile = None
    if resume_data:
        if current_user.is_authenticated:
            user_prefs = user_settings
            # Build preference profile from bookmarked/applied/dismissed jobs
            try:
                from services.preference_learner import build_preference_profile
                preference_profile = build_preference_profile(current_user.id)
            except Exception as e:
                logger.warning("Preference learning failed: %s", e)
        if remote_only:
            user_prefs["remote_only"] = True

        # Load custom scoring weights
        scoring_weights = None
        if user_settings and user_settings.get("scoring_weights"):
            try:
                scoring_weights = json.loads(user_settings["scoring_weights"])
            except (json.JSONDecodeError, TypeError):
                pass

        jobs = score_jobs(jobs, resume_data, user_prefs, preference_profile, scoring_weights)

        # Generate heuristic summaries only (AI summaries are on-demand via button)
        for job in jobs:
            if job.get("match_tier") == "strong" and job.get("match_reasons"):
                job["match_summary"] = "Matches your profile: " + "; ".join(job["match_reasons"][:3]) + "."

    # Record salary data for salary intelligence
    if current_user.is_authenticated and jobs:
        try:
            from services.salary_intelligence import record_salary_from_jobs
            record_salary_from_jobs(current_user.id, jobs, query, location)
        except Exception as e:
            logger.warning("Salary recording failed: %s", e)

    # Record jobs searched metric
    try:
        from services.metrics import inc_jobs_searched
        inc_jobs_searched(len(jobs))
    except Exception:
        pass

    # Role velocity signal (batch query — single DB connection)
    try:
        pairs = [(j.get("company", ""), j.get("title", "")) for j in jobs]
        velocities = get_role_velocities_batch(pairs)
        for job in jobs:
            v = velocities.get((job.get("company", ""), job.get("title", "")), 0)
            job["role_velocity"] = v if v > 1 else None
    except Exception:
        for job in jobs:
            job["role_velocity"] = None

    # Sort
    sort_by = request.args.get("sort", request.form.get("sort", "score"))
    if sort_by == "date":
        jobs.sort(key=lambda j: j.get("posted_date", ""), reverse=True)
    elif sort_by == "salary":
        jobs.sort(key=lambda j: j.get("salary_annual_max") or j.get("salary_annual_min") or j.get("salary_max") or j.get("salary_min") or 0, reverse=True)
    else:
        jobs = sort_within_tiers(jobs)

    # Record search history with avg salary
    if current_user.is_authenticated:
        avg_salary = None
        salary_vals = []
        for j in jobs:
            s_min = j.get("salary_annual_min") or j.get("salary_min")
            s_max = j.get("salary_annual_max") or j.get("salary_max")
            if s_min and s_max:
                salary_vals.append((s_min + s_max) / 2)
            elif s_min:
                salary_vals.append(s_min)
            elif s_max:
                salary_vals.append(s_max)
        if salary_vals:
            avg_salary = sum(salary_vals) / len(salary_vals)
        add_search_history_with_salary(current_user.id, query, location, remote_only, resume_id, len(jobs), avg_salary)

    # Pagination
    try:
        page = int(request.args.get("page", request.form.get("page", 1)))
    except (ValueError, TypeError):
        page = 1
    total_jobs = len(jobs)
    total_pages = max(1, (total_jobs + RESULTS_PER_PAGE - 1) // RESULTS_PER_PAGE)
    page = max(1, min(page, total_pages))
    start = (page - 1) * RESULTS_PER_PAGE
    paginated_jobs = jobs[start:start + RESULTS_PER_PAGE]

    # Get applied + bookmarked + dismissed keys
    applied_keys = set()
    bookmarked_keys = set()
    dismissed_keys = set()
    if current_user.is_authenticated:
        applied_keys = get_applied_job_keys(current_user.id)
        bookmarked_keys = get_bookmarked_job_keys(current_user.id)
        dismissed_keys = get_dismissed_job_keys(current_user.id)

    from services.job_search import get_unavailable_sources
    unavailable = get_unavailable_sources()
    sources = list({j["source"] for j in jobs})

    skills_display = resume_data.get("skills", [])
    job_titles = resume_data.get("job_titles", [])
    seniority = resume_data.get("seniority_tier", "")
    experience_years = resume_data.get("experience_years")

    return render_template(
        "results.html",
        jobs=paginated_jobs,
        all_jobs_count=len(jobs),
        query=query,
        location=location,
        total_jobs=total_jobs,
        page=page,
        total_pages=total_pages,
        sort=sort_by,
        skills=skills_display,
        job_titles=job_titles,
        seniority=seniority,
        experience_years=experience_years,
        sources=sources,
        unavailable_sources=unavailable,
        applied_keys=applied_keys,
        bookmarked_keys=bookmarked_keys,
        dismissed_keys=dismissed_keys,
    )


@search_bp.route("/export")
@login_required
def export_csv():
    """Export search results as CSV."""
    # Re-run the search to get data (or we could cache it, but this is simpler)
    from services.job_search import search_all
    from services.job_analyzer import analyze_jobs

    query = request.args.get("query", "")
    location = request.args.get("location", "")
    remote_only = request.args.get("remote_only") == "true"

    if not query:
        flash("No search to export.", "warning")
        return redirect(url_for("index"))

    jobs = search_all(query, location, remote_only)
    jobs = analyze_jobs(jobs)

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Title", "Company", "Location", "Remote Status", "Salary Min", "Salary Max",
                      "Posted Date", "Source", "Match Score", "Apply URL"])
    for job in jobs:
        writer.writerow([
            job.get("title", ""), job.get("company", ""), job.get("location", ""),
            job.get("remote_status", ""), job.get("salary_min", ""), job.get("salary_max", ""),
            job.get("posted_date", ""), job.get("source", ""), job.get("match_score", ""),
            job.get("apply_url", ""),
        ])

    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename=jobs_{re.sub(r'[^a-zA-Z0-9_-]', '_', query)}.csv"},
    )


@search_bp.route("/history")
@login_required
def history():
    from services.search_trends import get_search_trends, get_popular_searches
    searches = get_search_history(current_user.id)
    trends = get_search_trends(current_user.id, days=90)
    popular = get_popular_searches(current_user.id, limit=10)
    return render_template("history.html", searches=searches, trends=trends, popular=popular,
                           show_trends=False)


@search_bp.route("/history/trends")
@login_required
def history_trends():
    from services.search_trends import get_search_trends, get_popular_searches
    query_filter = request.args.get("query", "")
    days = _safe_int(request.args.get("days", "90"), 90)

    trends = get_search_trends(current_user.id, query=query_filter or None, days=days)
    popular = get_popular_searches(current_user.id, limit=10)
    searches = get_search_history(current_user.id)

    return render_template("history.html", searches=searches, trends=trends, popular=popular,
                           query_filter=query_filter, days=days, show_trends=True)
