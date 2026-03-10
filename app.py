import csv
import io
import json
import logging
import os
import re
import zipfile
from datetime import datetime, timedelta

from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, Response, send_file, session
from flask_wtf.csrf import CSRFProtect
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user

from config import Config
from logging_config import setup_logging
from database import (
    init_db, get_user_by_id, create_user, authenticate_user,
    create_saved_search, get_saved_searches, delete_saved_search,
    toggle_saved_search, toggle_all_saved_searches,
    mark_applied, unmark_applied, get_applied_job_keys, get_applied_jobs,
    get_applied_stats, update_applied_stage, update_applied_notes, PIPELINE_STAGES,
    get_user_settings, update_user_settings,
    save_resume, get_resumes, get_resume,
    set_default_resume, delete_resume, update_resume,
    add_search_history, get_search_history,
    bookmark_job, unbookmark_job, get_bookmarked_jobs, get_bookmarked_job_keys,
    create_password_reset_token, validate_reset_token, consume_reset_token,
    update_user_password, get_user_by_email,
    save_resume_version, get_resume_versions, get_resume_version,
    create_shared_job, get_shared_job,
    create_notification, get_unread_notifications, get_unread_count, mark_notifications_read,
    get_role_velocity,
    dismiss_job, undismiss_job, get_dismissed_job_keys,
    get_api_usage_summary, get_api_usage_daily, get_api_usage_recent,
    get_search_templates, create_search_template, delete_search_template,
    add_job_contact, get_job_contacts, update_job_contact, delete_job_contact,
    update_follow_up_date,
    get_cached_interview_prep, save_interview_prep, get_all_interview_preps,
    get_interview_prep_by_id, delete_interview_prep,
    snapshot_job_description, get_job_description_snapshots,
    get_user_due_follow_ups,
    create_webhook, get_webhooks, delete_webhook,
    create_team, get_user_teams, get_team, get_team_members,
    is_team_member, get_team_member_role, add_team_member, remove_team_member,
    delete_team, share_job_with_team, get_team_shared_jobs, get_team_shared_job,
    add_team_job_comment, get_team_job_comments, get_team_activity,
    get_admin_stats, get_admin_users, is_user_admin,
    get_cached_company, cache_company,
    record_merge, get_merge_sources, get_merge_sources_batch,
    get_stage_transitions, get_salary_benchmarks,
    add_search_history_with_salary,
    create_api_token, validate_api_token, get_api_tokens, delete_api_token,
    get_user_applied_and_bookmarked_keys,
    create_oauth_account, get_oauth_account, link_oauth_account, get_user_oauth_accounts,
    create_user_oauth,
)

setup_logging()
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.config.from_object(Config)

from database import close_db
app.teardown_appcontext(close_db)

RESULTS_PER_PAGE = 20


def _safe_int(value, default=0):
    """Safely convert a value to int, returning default on failure."""
    try:
        return int(value)
    except (ValueError, TypeError):
        return default

# Security
csrf = CSRFProtect(app)


def _rate_limit_key():
    """Use user ID when authenticated, falling back to IP address."""
    try:
        if current_user.is_authenticated:
            return f"user:{current_user.id}"
    except Exception:
        pass
    return get_remote_address()


limiter = Limiter(
    app=app,
    key_func=_rate_limit_key,
    default_limits=["60 per minute"],
    storage_uri="memory://",
    headers_enabled=True,
)

# Auth
login_manager = LoginManager(app)
login_manager.login_view = "login"
login_manager.login_message_category = "warning"


class User(UserMixin):
    def __init__(self, user_data):
        self.id = user_data["id"]
        self.email = user_data["email"]
        self.name = user_data.get("name", "")
        self.is_admin = bool(user_data.get("is_admin", 0))


@login_manager.user_loader
def load_user(user_id):
    data = get_user_by_id(int(user_id))
    if data:
        return User(data)
    return None


@app.before_request
def _metrics_before():
    """Record request start time for latency tracking."""
    import time as _time
    request._metrics_start = _time.time()


@app.after_request
def set_security_headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "style-src 'self' 'unsafe-inline'; "
        "script-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; "
        "font-src 'self'; "
        "object-src 'none'; "
        "base-uri 'self'; "
        "form-action 'self';"
    )

    # Record metrics (skip /static and /metrics)
    try:
        import time as _time
        from services.metrics import inc_request, inc_error, observe_latency
        path = request.path
        if not path.startswith("/static") and path != "/metrics":
            inc_request(path, request.method)
            if response.status_code >= 400:
                inc_error(path, request.method)
            start = getattr(request, "_metrics_start", None)
            if start:
                observe_latency(path, request.method, _time.time() - start)
    except Exception:
        pass

    return response


@app.context_processor
def inject_notification_count():
    ctx = {"config": Config}
    if current_user.is_authenticated:
        ctx["notification_count"] = get_unread_count(current_user.id)
    else:
        ctx["notification_count"] = 0
    return ctx


# --- Error Handlers ---

@app.errorhandler(404)
def page_not_found(e):
    return render_template("404.html"), 404


@app.errorhandler(500)
def internal_server_error(e):
    return render_template("500.html"), 500


# --- Auth Routes ---

@app.route("/register", methods=["GET", "POST"])
@limiter.limit("5 per minute")
def register():
    if current_user.is_authenticated:
        return redirect(url_for("index"))

    if request.method == "POST":
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "")
        name = request.form.get("name", "").strip()

        if not email or not password:
            flash("Email and password are required.", "error")
            return redirect(url_for("register"))

        if len(password) < 8:
            flash("Password must be at least 8 characters.", "error")
            return redirect(url_for("register"))

        user_id = create_user(email, password, name)
        if user_id is None:
            flash("An account with that email already exists.", "error")
            return redirect(url_for("register"))

        user_data = get_user_by_id(user_id)
        login_user(User(user_data))
        flash("Account created! Welcome.", "success")
        return redirect(url_for("index"))

    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
@limiter.limit("10 per minute")
def login():
    if current_user.is_authenticated:
        return redirect(url_for("index"))

    if request.method == "POST":
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "")

        user_data = authenticate_user(email, password)
        if user_data:
            login_user(User(user_data), remember=bool(request.form.get("remember")))
            next_page = request.args.get("next")
            if next_page and not next_page.startswith("/"):
                next_page = None
            if next_page and next_page.startswith("//"):
                next_page = None
            return redirect(next_page or url_for("index"))

        flash("Invalid email or password.", "error")
        return redirect(url_for("login"))

    return render_template("login.html")


@app.route("/logout")
def logout():
    logout_user()
    flash("Logged out.", "success")
    return redirect(url_for("index"))


# --- Password Management ---

@app.route("/change-password", methods=["GET", "POST"])
@login_required
def change_password():
    if request.method == "POST":
        current_password = request.form.get("current_password", "")
        new_password = request.form.get("new_password", "")
        confirm_password = request.form.get("confirm_password", "")

        if not current_password or not new_password:
            flash("All fields are required.", "error")
            return redirect(url_for("change_password"))

        if new_password != confirm_password:
            flash("New passwords do not match.", "error")
            return redirect(url_for("change_password"))

        if len(new_password) < 8:
            flash("New password must be at least 8 characters.", "error")
            return redirect(url_for("change_password"))

        user_data = authenticate_user(current_user.email, current_password)
        if not user_data:
            flash("Current password is incorrect.", "error")
            return redirect(url_for("change_password"))

        update_user_password(current_user.id, new_password)
        flash("Password changed successfully.", "success")
        return redirect(url_for("settings"))

    return render_template("change_password.html")


@app.route("/forgot-password", methods=["GET", "POST"])
@limiter.limit("5 per minute")
def forgot_password():
    if current_user.is_authenticated:
        return redirect(url_for("change_password"))

    if request.method == "POST":
        email = request.form.get("email", "").strip()
        if not email:
            flash("Please enter your email address.", "error")
            return redirect(url_for("forgot_password"))

        smtp_configured = bool(Config.SMTP_USER and Config.SMTP_PASSWORD)
        if smtp_configured:
            token = create_password_reset_token(email)
            if token:
                from services.notifier import send_password_reset_email
                base_url = request.url_root.rstrip("/")
                send_password_reset_email(email, token, base_url)
            # Always show the same message to prevent email enumeration
            flash("If an account with that email exists, a password reset link has been sent.", "success")
        else:
            flash(
                "Email is not configured on this server. "
                "Please log in and use the Change Password option, or contact an administrator.",
                "warning",
            )

        return redirect(url_for("forgot_password"))

    return render_template("forgot_password.html")


@app.route("/reset-password/<token>", methods=["GET", "POST"])
@limiter.limit("10 per minute")
def reset_password(token):
    user_id = validate_reset_token(token)
    if not user_id:
        flash("This password reset link is invalid or has expired.", "error")
        return redirect(url_for("forgot_password"))

    if request.method == "POST":
        new_password = request.form.get("new_password", "")
        confirm_password = request.form.get("confirm_password", "")

        if not new_password:
            flash("Password is required.", "error")
            return redirect(url_for("reset_password", token=token))

        if new_password != confirm_password:
            flash("Passwords do not match.", "error")
            return redirect(url_for("reset_password", token=token))

        if len(new_password) < 8:
            flash("Password must be at least 8 characters.", "error")
            return redirect(url_for("reset_password", token=token))

        # Atomically consume token to prevent race condition
        consumed_user_id = consume_reset_token(token)
        if not consumed_user_id:
            flash("This password reset link is invalid or has expired.", "error")
            return redirect(url_for("forgot_password"))

        update_user_password(consumed_user_id, new_password)
        flash("Your password has been reset. You can now log in.", "success")
        return redirect(url_for("login"))

    return render_template("reset_password.html", token=token)


# --- Core Routes ---

@app.route("/health")
@limiter.exempt
def health():
    return jsonify({"status": "ok"})


@app.route("/")
def index():
    saved_resumes = []
    user_id = None
    if current_user.is_authenticated:
        saved_resumes = get_resumes(current_user.id)
        user_id = current_user.id
    templates = get_search_templates(user_id)
    # Group templates by category
    templates_by_category = {}
    for t in templates:
        cat = t.get("category") or "Other"
        templates_by_category.setdefault(cat, []).append(t)
    return render_template("index.html", saved_resumes=saved_resumes,
                           templates=templates, templates_by_category=templates_by_category)


@app.route("/search", methods=["GET", "POST"])
@limiter.limit("5 per minute")
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
    from database import get_role_velocities_batch
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


@app.route("/export")
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


# --- Alerts ---

@app.route("/alerts", methods=["GET"])
@login_required
def alerts():
    searches = get_saved_searches(current_user.id)
    smtp_configured = bool(Config.SMTP_USER and Config.SMTP_PASSWORD)
    return render_template("alerts.html", searches=searches, smtp_configured=smtp_configured)


@app.route("/alerts", methods=["POST"])
@login_required
def create_alert():
    query = request.form.get("query", "").strip()
    location = request.form.get("location", "").strip()
    frequency = request.form.get("frequency", "daily")
    remote_only = bool(request.form.get("remote_only"))

    if not query:
        flash("Search query is required.", "error")
        return redirect(url_for("alerts"))

    create_saved_search(current_user.id, query, location, remote_only, None, frequency)
    flash(f"Alert created for '{query}'.", "success")
    return redirect(url_for("alerts"))


@app.route("/alerts/<int:alert_id>/delete", methods=["POST"])
@login_required
def delete_alert(alert_id):
    delete_saved_search(alert_id, current_user.id)
    flash("Alert deleted.", "success")
    return redirect(url_for("alerts"))


@app.route("/alerts/<int:alert_id>/toggle", methods=["POST"])
@login_required
def toggle_alert(alert_id):
    is_active = request.form.get("is_active") == "1"
    toggle_saved_search(alert_id, current_user.id, is_active)
    status = "enabled" if is_active else "paused"
    flash(f"Alert {status}.", "success")
    return redirect(url_for("alerts"))


@app.route("/alerts/toggle-all", methods=["POST"])
@login_required
def toggle_all_alerts():
    is_active = request.form.get("is_active") == "1"
    toggle_all_saved_searches(current_user.id, is_active)
    status = "enabled" if is_active else "paused"
    flash(f"All alerts {status}.", "success")
    return redirect(url_for("alerts"))


# --- Applied Jobs / Pipeline ---

@app.route("/jobs/<job_key>/applied", methods=["POST"])
@login_required
def mark_job_applied(job_key):
    data = request.get_json() or {}
    mark_applied(
        current_user.id, job_key,
        data.get("title", ""), data.get("company", ""),
        data.get("notes", ""), data.get("location", ""),
        data.get("apply_url", ""), data.get("stage", "applied"),
    )
    # Store resume_id if provided
    resume_id = data.get("resume_id")
    if resume_id:
        from database import get_db, _safe_close
        conn = get_db()
        conn.execute(
            "UPDATE applied_jobs SET resume_id = ? WHERE user_id = ? AND job_key = ?",
            (resume_id, current_user.id, job_key),
        )
        conn.commit()
        _safe_close(conn)
    return jsonify({"status": "ok"})


@app.route("/jobs/<job_key>/applied", methods=["DELETE"])
@login_required
def unmark_job_applied(job_key):
    unmark_applied(current_user.id, job_key)
    return jsonify({"status": "ok"})


@app.route("/jobs/<job_key>/stage", methods=["POST"])
@login_required
def update_job_stage(job_key):
    data = request.get_json() or {}
    stage = data.get("stage", "applied")
    notes = data.get("notes")
    if stage not in PIPELINE_STAGES:
        return jsonify({"error": "Invalid stage"}), 400
    update_applied_stage(current_user.id, job_key, stage, notes)
    return jsonify({"status": "ok", "stage": stage})


@app.route("/jobs/<job_key>/notes", methods=["POST"])
@login_required
def update_job_notes(job_key):
    data = request.get_json() or {}
    update_applied_notes(current_user.id, job_key, data.get("notes", ""))
    return jsonify({"status": "ok"})


@app.route("/pipeline")
@login_required
def pipeline():
    stage_filter = request.args.get("stage")
    applied = get_applied_jobs(current_user.id, stage_filter)
    stats = get_applied_stats(current_user.id)
    today = datetime.now().strftime("%Y-%m-%d")
    return render_template("pipeline.html", jobs=applied, stats=stats,
                           stages=PIPELINE_STAGES, current_stage=stage_filter, today=today)


# --- Bookmarks ---

@app.route("/jobs/<job_key>/bookmark", methods=["POST"])
@login_required
def bookmark_job_route(job_key):
    data = request.get_json() or {}
    data["job_key"] = job_key
    bookmark_job(current_user.id, data)
    return jsonify({"status": "ok"})


@app.route("/jobs/<job_key>/bookmark", methods=["DELETE"])
@login_required
def unbookmark_job_route(job_key):
    unbookmark_job(current_user.id, job_key)
    return jsonify({"status": "ok"})


# --- Dismissed Jobs ---

@app.route("/jobs/<job_key>/dismiss", methods=["POST"])
@login_required
def dismiss_job_route(job_key):
    data = request.get_json() or {}
    dismiss_job(
        current_user.id, job_key,
        data.get("title", ""), data.get("company", ""),
    )
    return jsonify({"status": "ok"})


@app.route("/jobs/<job_key>/dismiss", methods=["DELETE"])
@login_required
def undismiss_job_route(job_key):
    undismiss_job(current_user.id, job_key)
    return jsonify({"status": "ok"})


@app.route("/bookmarks")
@login_required
def bookmarks():
    jobs = get_bookmarked_jobs(current_user.id)
    applied_keys = get_applied_job_keys(current_user.id)
    return render_template("bookmarks.html", jobs=jobs, applied_keys=applied_keys)


# --- Compare ---

@app.route("/compare")
def compare_jobs_view():
    keys_str = request.args.get("keys", "")
    if not keys_str:
        flash("No jobs selected for comparison.", "warning")
        return redirect(url_for("index"))
    keys = [k.strip() for k in keys_str.split(",") if k.strip()][:4]
    jobs = []
    if current_user.is_authenticated:
        all_bookmarks = get_bookmarked_jobs(current_user.id)
        bm_map = {dict(b)["job_key"]: dict(b) for b in all_bookmarks}
        for key in keys:
            if key in bm_map:
                jobs.append(bm_map[key])
    return render_template("compare.html", jobs=jobs, keys=keys)


# --- Cover Letter ---

@app.route("/jobs/cover-letter", methods=["POST"])
@login_required
@limiter.limit("10 per minute")
def generate_cover_letter_route():
    from services.cover_letter import generate_cover_letter
    data = request.get_json() or {}

    job_title = data.get("title", "")
    company = data.get("company", "")
    job_description = data.get("description", "")

    from services.resume_loader import require_resume
    resume, err = require_resume(current_user.id)
    if err:
        return err

    letter = generate_cover_letter(
        resume["text"], job_title, company, job_description,
        user_name=current_user.name
    )

    return jsonify({"cover_letter": letter})


# --- Screening Answers ---

@app.route("/jobs/screening-answers", methods=["POST"])
@login_required
@limiter.limit("10 per minute")
def screening_answers():
    """Generate answers to screening questions."""
    from services.screening_answerer import generate_screening_answers
    data = request.get_json() or {}

    job_title = data.get("title", "")
    company = data.get("company", "")
    job_description = data.get("description", "")
    questions = data.get("questions", [])

    if not questions:
        return jsonify({"error": "No questions provided."}), 400

    from services.resume_loader import load_resume_or_empty
    resume = load_resume_or_empty(current_user.id)

    answers = generate_screening_answers(
        resume["text"], job_title, company, job_description, questions,
        user_name=current_user.name
    )

    return jsonify({"answers": answers})


# --- Application Draft ---

@app.route("/jobs/application-draft", methods=["POST"])
@login_required
@limiter.limit("10 per minute")
def application_draft():
    """Generate an application draft."""
    from services.application_drafter import generate_application_draft
    data = request.get_json() or {}

    job_title = data.get("title", "")
    company = data.get("company", "")
    job_description = data.get("description", "")

    from services.resume_loader import require_resume
    resume, err = require_resume(current_user.id)
    if err:
        return err

    draft = generate_application_draft(
        resume["text"], resume["data"], job_title, company, job_description,
        user_name=current_user.name
    )

    return jsonify({"draft": draft})


# --- Resumes ---

@app.route("/resumes")
@login_required
def resumes():
    user_resumes = get_resumes(current_user.id)
    return render_template("resumes.html", resumes=user_resumes)


@app.route("/resumes/<int:rid>/default", methods=["POST"])
@login_required
def set_resume_default(rid):
    set_default_resume(rid, current_user.id)
    flash("Default resume updated.", "success")
    return redirect(url_for("resumes"))


@app.route("/resumes/<int:rid>")
@login_required
def view_resume(rid):
    resume = get_resume(rid, current_user.id)
    if not resume:
        flash("Resume not found.", "error")
        return redirect(url_for("resumes"))
    skills = []
    if resume.get("skills_json"):
        try:
            skills_data = json.loads(resume["skills_json"])
            skills = skills_data.get("skills", skills_data) if isinstance(skills_data, dict) else skills_data
        except (json.JSONDecodeError, TypeError):
            pass
    return render_template("resume_view.html", resume=resume, skills=skills)


@app.route("/resumes/<int:rid>/delete", methods=["POST"])
@login_required
def delete_resume_route(rid):
    delete_resume(rid, current_user.id)
    flash("Resume deleted.", "success")
    return redirect(url_for("resumes"))


# --- Share Job ---

@app.route("/jobs/share", methods=["POST"])
@login_required
def share_job():
    data = request.get_json() or {}
    if not data.get("title"):
        return jsonify({"error": "Job data required"}), 400
    token = create_shared_job(current_user.id, data)
    share_url = request.url_root.rstrip("/") + url_for("view_shared_job", token=token)
    return jsonify({"share_url": share_url, "token": token})


@app.route("/shared/<token>")
def view_shared_job(token):
    job = get_shared_job(token)
    if not job:
        flash("Shared job not found or has expired.", "error")
        return redirect(url_for("index"))
    return render_template("shared_job.html", job=job)


# --- Resume Versioning ---

@app.route("/resumes/<int:rid>/versions")
@login_required
def resume_versions(rid):
    resume = get_resume(rid, current_user.id)
    if not resume:
        flash("Resume not found.", "error")
        return redirect(url_for("resumes"))
    versions = get_resume_versions(rid, current_user.id)
    return render_template("resume_versions.html", resume=resume, versions=versions)


@app.route("/resumes/<int:rid>/versions/<int:vid>")
@login_required
def view_resume_version(rid, vid):
    version = get_resume_version(vid, current_user.id)
    if not version or version["resume_id"] != rid:
        flash("Version not found.", "error")
        return redirect(url_for("resume_versions", rid=rid))
    resume = get_resume(rid, current_user.id)
    return render_template("resume_version_detail.html", resume=resume, version=version)


@app.route("/resumes/<int:rid>/versions/<int:vid>/restore", methods=["POST"])
@login_required
def restore_resume_version(rid, vid):
    version = get_resume_version(vid, current_user.id)
    if not version or version["resume_id"] != rid:
        flash("Version not found.", "error")
        return redirect(url_for("resume_versions", rid=rid))
    current_resume = get_resume(rid, current_user.id)
    if current_resume:
        save_resume_version(rid, current_user.id, current_resume["raw_text"], current_resume.get("skills_json"), "Before restore")
    update_resume(rid, current_user.id, version["raw_text"], version.get("skills_json"))
    flash(f"Restored to version {version['version_number']}.", "success")
    return redirect(url_for("resumes"))


# --- LinkedIn Import ---

@app.route("/resumes/import-linkedin", methods=["POST"])
@login_required
def import_linkedin():
    file = request.files.get("linkedin_file")
    if not file or not file.filename:
        flash("Please select a LinkedIn PDF file.", "error")
        return redirect(url_for("resumes"))
    ext = os.path.splitext(file.filename)[1].lower()
    if ext != ".pdf":
        flash("Only PDF files are supported for LinkedIn import.", "error")
        return redirect(url_for("resumes"))
    from services.linkedin_parser import parse_linkedin_pdf, linkedin_to_resume_text
    parsed = parse_linkedin_pdf(file)
    if not parsed:
        flash("Could not parse the LinkedIn PDF. Make sure it's a valid LinkedIn profile export.", "error")
        return redirect(url_for("resumes"))
    resume_text = linkedin_to_resume_text(parsed)
    name = f"LinkedIn - {parsed.get('name', 'Import')}"
    save_resume(current_user.id, resume_text, name=name, filename=file.filename)
    flash(f"LinkedIn profile imported as '{name}'.", "success")
    return redirect(url_for("resumes"))


# --- Search History ---

@app.route("/history")
@login_required
def history():
    from services.search_trends import get_search_trends, get_popular_searches
    searches = get_search_history(current_user.id)
    trends = get_search_trends(current_user.id, days=90)
    popular = get_popular_searches(current_user.id, limit=10)
    return render_template("history.html", searches=searches, trends=trends, popular=popular,
                           show_trends=False)


# --- Dashboard ---

@app.route("/dashboard")
@login_required
def dashboard():
    stats = get_applied_stats(current_user.id)
    recent_applied = get_applied_jobs(current_user.id)[:5]
    recent_history = get_search_history(current_user.id, limit=5)
    bookmarks_count = len(get_bookmarked_job_keys(current_user.id))
    resumes_count = len(get_resumes(current_user.id))
    alerts_count = len(get_saved_searches(current_user.id))
    total_applied = sum(stats.values())

    # Follow-up reminders (next 7 days)
    due_follow_ups = get_user_due_follow_ups(current_user.id, days_ahead=7)
    today = datetime.now().strftime("%Y-%m-%d")

    return render_template(
        "dashboard.html",
        stats=stats,
        stages=PIPELINE_STAGES,
        recent_applied=recent_applied,
        recent_history=recent_history,
        bookmarks_count=bookmarks_count,
        resumes_count=resumes_count,
        alerts_count=alerts_count,
        total_applied=total_applied,
        due_follow_ups=due_follow_ups,
        today=today,
    )


# --- Settings ---

@app.route("/settings", methods=["GET"])
@login_required
def settings():
    user_settings = get_user_settings(current_user.id)
    from services.apis.registry import get_all_providers
    api_status = {p.name: p.is_available() for p in get_all_providers()}
    api_status["Claude AI (matching)"] = bool(Config.ANTHROPIC_API_KEY)
    api_status["SMTP (email)"] = bool(Config.SMTP_USER and Config.SMTP_PASSWORD)

    # Parse scoring weights for template
    scoring_weights = {"skills": 50, "location": 50, "salary": 50, "experience": 50, "remote": 50}
    if user_settings.get("scoring_weights"):
        try:
            scoring_weights.update(json.loads(user_settings["scoring_weights"]))
        except (json.JSONDecodeError, TypeError):
            pass

    # API tokens
    api_tokens_list = get_api_tokens(current_user.id)
    new_token = session.pop("new_api_token", None)

    # OAuth accounts
    oauth_accounts = get_user_oauth_accounts(current_user.id)
    google_oauth_available = bool(Config.GOOGLE_CLIENT_ID)

    return render_template("settings.html", settings=user_settings, api_status=api_status,
                           scoring_weights=scoring_weights, api_tokens=api_tokens_list,
                           new_token=new_token, oauth_accounts=oauth_accounts,
                           google_oauth_available=google_oauth_available)


@app.route("/settings", methods=["POST"])
@login_required
def save_settings():
    # Build scoring weights JSON
    scoring_weights = json.dumps({
        "skills": min(_safe_int(request.form.get("weight_skills"), 50), 100),
        "location": min(_safe_int(request.form.get("weight_location"), 50), 100),
        "salary": min(_safe_int(request.form.get("weight_salary"), 50), 100),
        "experience": min(_safe_int(request.form.get("weight_experience"), 50), 100),
        "remote": min(_safe_int(request.form.get("weight_remote"), 50), 100),
    })
    weekly_report = 1 if request.form.get("weekly_report_enabled") else 0
    update_user_settings(
        current_user.id,
        name=request.form.get("name", ""),
        timezone=request.form.get("timezone", "UTC"),
        max_commute_minutes=min(_safe_int(request.form.get("max_commute_minutes"), 60), 999),
        seniority_tier=request.form.get("seniority_tier", ""),
        blocked_companies=request.form.get("blocked_companies", ""),
        blocked_keywords=request.form.get("blocked_keywords", ""),
        blocked_locations=request.form.get("blocked_locations", ""),
        scoring_weights=scoring_weights,
        weekly_report_enabled=weekly_report,
    )
    flash("Settings saved.", "success")
    return redirect(url_for("settings"))


# --- Notifications ---

@app.route("/notifications")
@login_required
def get_notifications():
    notifs = get_unread_notifications(current_user.id)
    return jsonify({
        "notifications": [
            {"id": n["id"], "message": n["message"], "link": n["link"], "created_at": n["created_at"]}
            for n in notifs
        ],
        "count": get_unread_count(current_user.id),
    })


@app.route("/notifications/read", methods=["POST"])
@login_required
def read_notifications():
    data = request.get_json() or {}
    ids = data.get("ids")
    mark_notifications_read(current_user.id, ids)
    return jsonify({"status": "ok"})


# --- Job Detail ---

@app.route("/jobs/<job_key>")
def job_detail(job_key):
    """Full-page view of a single job."""
    applied_keys = set()
    bookmarked_keys = set()
    dismissed_keys = set()
    if current_user.is_authenticated:
        applied_keys = get_applied_job_keys(current_user.id)
        bookmarked_keys = get_bookmarked_job_keys(current_user.id)
        dismissed_keys = get_dismissed_job_keys(current_user.id)

    # Try to find job in bookmarks or shared jobs
    job = None
    if current_user.is_authenticated:
        bookmarks = get_bookmarked_jobs(current_user.id)
        for b in bookmarks:
            if dict(b)["job_key"] == job_key:
                job = dict(b)
                break
    if not job:
        shared = get_shared_job(job_key)
        if shared:
            job = shared
    if not job:
        flash("Job not found. Try searching again.", "warning")
        return redirect(url_for("index"))

    # Snapshot description for diff tracking
    has_changes = False
    if current_user.is_authenticated and job.get("description"):
        try:
            snapshot_job_description(current_user.id, job_key, job["description"])
            snapshots = get_job_description_snapshots(current_user.id, job_key)
            has_changes = len(snapshots) > 1
        except Exception as e:
            logger.warning("Description snapshot failed: %s", e)

    # Load company research summary if available
    company_summary = None
    if job.get("company"):
        cached = get_cached_company(job["company"])
        if cached and isinstance(cached, dict) and "ai_summary" in cached:
            company_summary = cached["ai_summary"]

    # Load alternate sources from merge records
    merge_sources = get_merge_sources(job.get("job_key", ""))
    if merge_sources and not job.get("alternate_sources"):
        job["alternate_sources"] = [{"source": m["source_name"], "apply_url": m.get("source_url")} for m in merge_sources]

    return render_template(
        "job_detail.html", job=job,
        applied_keys=applied_keys, bookmarked_keys=bookmarked_keys, dismissed_keys=dismissed_keys,
        has_description_changes=has_changes,
        company_summary=company_summary,
    )


@app.route("/jobs/<job_key>/description-diff")
@login_required
def job_description_diff(job_key):
    """Show diff between job description snapshots."""
    import difflib
    snapshots = get_job_description_snapshots(current_user.id, job_key)
    if len(snapshots) < 2:
        return jsonify({"diff": None, "message": "No changes detected."})

    # Compare last two versions
    old = snapshots[-2]["description"]
    new = snapshots[-1]["description"]
    old_date = snapshots[-2]["snapshot_at"]
    new_date = snapshots[-1]["snapshot_at"]

    diff = difflib.unified_diff(
        old.splitlines(keepends=True),
        new.splitlines(keepends=True),
        fromfile=f"Version ({old_date})",
        tofile=f"Version ({new_date})",
        lineterm="",
    )
    diff_text = "\n".join(diff)

    # Also create an HTML diff
    html_diff = difflib.HtmlDiff().make_table(
        old.splitlines(), new.splitlines(),
        fromdesc=f"Version ({old_date[:10]})",
        todesc=f"Version ({new_date[:10]})",
        context=True, numlines=3,
    )

    return jsonify({
        "diff": diff_text,
        "html_diff": html_diff,
        "snapshot_count": len(snapshots),
        "old_date": old_date,
        "new_date": new_date,
    })


# --- Interview Prep ---

@app.route("/jobs/interview-prep", methods=["POST"])
@login_required
@limiter.limit("10 per minute")
def interview_prep():
    from services.interview_prep import generate_interview_prep
    data = request.get_json() or {}

    job_title = data.get("title", "")
    company = data.get("company", "")
    job_description = data.get("description", "")
    job_key = data.get("job_key", "")

    # Check cache first
    cached = get_cached_interview_prep(current_user.id, company, job_title)
    if cached:
        return jsonify(cached["prep"])

    from services.resume_loader import require_resume
    resume, err = require_resume(current_user.id)
    if err:
        return err

    result = generate_interview_prep(
        resume["text"],
        job_title,
        company,
        job_description,
        user_name=current_user.name,
    )

    # Save to cache
    save_interview_prep(current_user.id, company, job_title, job_key, result)

    return jsonify(result)


# --- Calendar / Interview Scheduling ---

@app.route("/calendar")
@login_required
def calendar():
    interviews = get_applied_jobs(current_user.id, stage="interview")
    all_applied = get_applied_jobs(current_user.id)
    return render_template("calendar.html", interviews=interviews, all_applied_jobs=all_applied)


@app.route("/calendar/schedule", methods=["POST"])
@login_required
def schedule_interview():
    job_key = request.form.get("job_key")
    date = request.form.get("interview_date", "")
    time = request.form.get("interview_time", "")
    notes = request.form.get("interview_notes", "")

    if not job_key or not date:
        flash("Job and date are required.", "error")
        return redirect(url_for("calendar"))

    # Move to interview stage and save date/time in notes
    schedule_note = f"{date} {time}".strip()
    if notes:
        schedule_note += f" - {notes}"
    update_applied_stage(current_user.id, job_key, "interview")
    update_applied_notes(current_user.id, job_key, schedule_note)
    flash("Interview scheduled.", "success")
    return redirect(url_for("calendar"))


@app.route("/calendar/ics/<job_key>")
@login_required
def download_ics(job_key):
    """Generate an ICS file for an interview."""
    jobs = get_applied_jobs(current_user.id, stage="interview")
    job = None
    for j in jobs:
        if j["job_key"] == job_key:
            job = dict(j)
            break
    if not job:
        flash("Interview not found.", "error")
        return redirect(url_for("calendar"))

    # Parse date from notes (format: YYYY-MM-DD HH:MM)
    notes = job.get("notes", "") or ""
    interview_dt = None
    date_match = re.search(r"(\d{4}-\d{2}-\d{2})\s+(\d{1,2}:\d{2})", notes)
    if date_match:
        try:
            interview_dt = datetime.strptime(
                f"{date_match.group(1)} {date_match.group(2)}", "%Y-%m-%d %H:%M"
            )
        except ValueError:
            pass

    if not interview_dt:
        interview_dt = datetime.now() + timedelta(days=1)

    end_dt = interview_dt + timedelta(hours=1)
    now = datetime.utcnow()

    def _ics_escape(text):
        """Escape text for ICS format (RFC 5545)."""
        return text.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")

    ics_title = _ics_escape(job['title'])
    ics_company = _ics_escape(job['company'])

    ics = f"""BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Nexus//EN
BEGIN:VEVENT
DTSTART:{interview_dt.strftime('%Y%m%dT%H%M%S')}
DTEND:{end_dt.strftime('%Y%m%dT%H%M%S')}
DTSTAMP:{now.strftime('%Y%m%dT%H%M%SZ')}
SUMMARY:Interview - {ics_title} at {ics_company}
DESCRIPTION:Interview for {ics_title} at {ics_company}
END:VEVENT
END:VCALENDAR"""

    return Response(
        ics,
        mimetype="text/calendar",
        headers={"Content-Disposition": f"attachment; filename=interview_{re.sub(r'[^a-zA-Z0-9_-]', '_', job_key)}.ics"},
    )



# --- API Usage Dashboard ---

@app.route("/usage")
@login_required
def usage():
    days = _safe_int(request.args.get("days"), 30)
    summary = get_api_usage_summary(user_id=current_user.id, days=days)
    daily = get_api_usage_daily(user_id=current_user.id, days=days)
    recent = get_api_usage_recent(user_id=current_user.id, days=days, limit=50)
    total_cost = sum(s["total_cost"] or 0 for s in summary)
    total_calls = sum(s["call_count"] for s in summary)

    return render_template(
        "usage.html",
        summary=summary, daily=daily, recent=recent,
        total_cost=total_cost, total_calls=total_calls,
        days=days,
    )


# --- Search Templates ---

@app.route("/templates/search", methods=["GET"])
def list_search_templates():
    user_id = current_user.id if current_user.is_authenticated else None
    templates = get_search_templates(user_id)
    return jsonify({"templates": templates})


@app.route("/templates/search", methods=["POST"])
@login_required
def create_search_template_route():
    data = request.get_json() or {}
    name = (data.get("name") or "").strip()
    query = (data.get("query") or "").strip()
    if not name or not query:
        return jsonify({"error": "Name and query are required."}), 400
    tid = create_search_template(
        current_user.id,
        name=name,
        query=query,
        location=data.get("location", ""),
        remote_only=bool(data.get("remote_only")),
        description=data.get("description", ""),
        category=data.get("category", "Custom"),
    )
    return jsonify({"status": "ok", "id": tid})


@app.route("/templates/search/<int:tid>/delete", methods=["POST"])
@login_required
def delete_search_template_route(tid):
    delete_search_template(tid, current_user.id)
    return jsonify({"status": "ok"})


# --- Job Contacts ---

@app.route("/jobs/<job_key>/contacts", methods=["POST"])
@login_required
def add_contact(job_key):
    data = request.get_json() or {}
    cid = add_job_contact(
        current_user.id, job_key,
        name=data.get("name", ""),
        email=data.get("email", ""),
        phone=data.get("phone", ""),
        role=data.get("role", ""),
        notes=data.get("notes", ""),
    )
    return jsonify({"status": "ok", "id": cid})


@app.route("/jobs/<job_key>/contacts", methods=["GET"])
@login_required
def list_contacts(job_key):
    contacts = get_job_contacts(current_user.id, job_key)
    return jsonify({"contacts": contacts})


@app.route("/jobs/<job_key>/contacts/<int:cid>", methods=["DELETE"])
@login_required
def remove_contact(job_key, cid):
    delete_job_contact(cid, current_user.id)
    return jsonify({"status": "ok"})


@app.route("/jobs/<job_key>/follow-up", methods=["POST"])
@login_required
def set_follow_up(job_key):
    data = request.get_json() or {}
    update_follow_up_date(current_user.id, job_key, data.get("follow_up_date", ""))
    return jsonify({"status": "ok"})


# --- Interview Prep Persistence ---

@app.route("/interview-prep")
@login_required
def interview_prep_list():
    preps = get_all_interview_preps(current_user.id)
    return render_template("interview_prep.html", preps=preps)


@app.route("/interview-prep/<int:pid>")
@login_required
def interview_prep_detail(pid):
    prep = get_interview_prep_by_id(pid, current_user.id)
    if not prep:
        flash("Interview prep not found.", "error")
        return redirect(url_for("interview_prep_list"))
    return render_template("interview_prep_detail.html", prep=prep)


@app.route("/interview-prep/<int:pid>/delete", methods=["POST"])
@login_required
def interview_prep_delete(pid):
    delete_interview_prep(pid, current_user.id)
    flash("Interview prep deleted.", "success")
    return redirect(url_for("interview_prep_list"))


# --- CSV Import ---

@app.route("/jobs/import-csv", methods=["POST"])
@login_required
def import_csv_route():
    """Import job listings from a CSV file."""
    file = request.files.get("csv_file")
    if not file or not file.filename:
        flash("No file selected.", "error")
        return redirect(url_for("bookmarks"))

    if not file.filename.lower().endswith(".csv"):
        flash("Please upload a CSV file.", "error")
        return redirect(url_for("bookmarks"))

    try:
        content = file.read().decode("utf-8-sig")
        reader = csv.DictReader(io.StringIO(content))

        success_count = 0
        error_count = 0

        for row in reader:
            try:
                job_data = {
                    "job_key": f"csv_{row.get('title', '')}_{row.get('company', '')}_{success_count}".replace(" ", "_")[:100],
                    "title": row.get("title", "").strip(),
                    "company": row.get("company", "").strip(),
                    "location": row.get("location", "").strip(),
                    "apply_url": row.get("apply_url", "").strip(),
                    "salary_min": float(row["salary_min"]) if row.get("salary_min") else None,
                    "salary_max": float(row["salary_max"]) if row.get("salary_max") else None,
                    "description": row.get("description", "").strip(),
                    "remote_status": row.get("remote_status", "").strip(),
                    "source": row.get("source", "CSV Import").strip() or "CSV Import",
                }
                if not job_data["title"]:
                    error_count += 1
                    continue
                bookmark_job(current_user.id, job_data)
                success_count += 1
            except Exception:
                error_count += 1

        if success_count > 0:
            flash(f"Successfully imported {success_count} job(s).", "success")
        if error_count > 0:
            flash(f"Failed to import {error_count} row(s).", "warning")
        if success_count == 0 and error_count == 0:
            flash("No valid rows found in the CSV.", "warning")

    except Exception as e:
        logger.error("CSV import failed: %s", e)
        flash(f"Failed to parse CSV file: {str(e)}", "error")

    return redirect(url_for("bookmarks"))


# --- Resume Tailoring ---

@app.route("/jobs/tailor-resume", methods=["POST"])
@login_required
@limiter.limit("10 per minute")
def tailor_resume_route():
    """Generate tailored resume suggestions for a specific job."""
    from services.resume_tailor import tailor_resume
    data = request.get_json() or {}

    job_title = data.get("title", "")
    company = data.get("company", "")
    job_description = data.get("description", "")

    from services.resume_loader import require_resume
    resume, err = require_resume(current_user.id)
    if err:
        return err

    result = tailor_resume(resume["text"], job_title, company, job_description)

    # Track AI call
    try:
        from services.metrics import inc_ai_calls
        inc_ai_calls("resume_tailor")
    except Exception:
        pass

    return jsonify(result)


# --- Application Auto-fill ---

@app.route("/jobs/autofill-data", methods=["GET"])
@login_required
def autofill_data():
    """Get extracted application data from the user's resume."""
    user_settings = get_user_settings(current_user.id)

    # Return cached data if available
    if user_settings.get("user_autofill_data"):
        try:
            return jsonify(json.loads(user_settings["user_autofill_data"]))
        except (json.JSONDecodeError, TypeError):
            pass

    # Generate fresh data
    from services.application_autofill import generate_autofill
    from services.resume_loader import require_resume
    resume, err = require_resume(current_user.id)
    if err:
        return err

    result = generate_autofill(resume["text"], user_settings)

    # Cache the result
    update_user_settings(current_user.id, user_autofill_data=json.dumps(result))

    return jsonify(result)


# --- Salary Insights ---

@app.route("/salary-insights")
@login_required
def salary_insights():
    """Page showing salary data aggregated from user's searched roles."""
    from services.salary_intelligence import get_salary_insights
    role = request.args.get("role", "")
    location = request.args.get("location", "")
    insights = get_salary_insights(current_user.id, role_query=role or None, location=location or None)
    return render_template("salary_insights.html", insights=insights, role=role, location=location)


# --- Prometheus Metrics ---

@app.route("/metrics")
@csrf.exempt
@limiter.exempt
def prometheus_metrics():
    """Prometheus-compatible metrics endpoint. Protected by METRICS_SECRET if set."""
    metrics_secret = os.environ.get("METRICS_SECRET")
    if metrics_secret and request.headers.get("X-Metrics-Token") != metrics_secret:
        return "", 404
    from services.metrics import render_metrics
    return Response(render_metrics(), mimetype="text/plain; version=0.0.4; charset=utf-8")


# --- Webhooks ---

@app.route("/settings/webhooks", methods=["GET", "POST"])
@login_required
def webhooks_settings():
    if request.method == "POST":
        url = request.form.get("url", "").strip()
        secret = request.form.get("secret", "").strip() or None
        event_types_raw = request.form.getlist("event_types")
        if not event_types_raw:
            event_types_raw = ["new_matches"]

        if not url:
            flash("Webhook URL is required.", "error")
            return redirect(url_for("webhooks_settings"))

        if not url.startswith("http://") and not url.startswith("https://"):
            flash("Webhook URL must start with http:// or https://", "error")
            return redirect(url_for("webhooks_settings"))

        create_webhook(current_user.id, url, event_types=event_types_raw, secret=secret)
        flash("Webhook created.", "success")
        return redirect(url_for("webhooks_settings"))

    hooks = get_webhooks(current_user.id)
    return render_template("webhooks.html", webhooks=hooks)


@app.route("/settings/webhooks/<int:wid>/delete", methods=["POST"])
@login_required
def webhook_delete(wid):
    delete_webhook(wid, current_user.id)
    flash("Webhook deleted.", "success")
    return redirect(url_for("webhooks_settings"))


@app.route("/settings/webhooks/<int:wid>/test", methods=["POST"])
@login_required
def webhook_test(wid):
    hooks = get_webhooks(current_user.id)
    wh = next((h for h in hooks if h["id"] == wid), None)
    if not wh:
        flash("Webhook not found.", "error")
        return redirect(url_for("webhooks_settings"))

    from services.webhook_sender import send_test_webhook
    success, detail = send_test_webhook(wh["url"], secret=wh.get("secret"))
    if success:
        flash(f"Test webhook sent successfully (status {detail}).", "success")
    else:
        flash(f"Test webhook failed: {detail}", "error")
    return redirect(url_for("webhooks_settings"))


# --- Bulk Actions ---

@app.route("/jobs/bulk/bookmark", methods=["POST"])
@login_required
def bulk_bookmark():
    data = request.get_json() or {}
    jobs = data.get("jobs", [])
    count = 0
    for job_data in jobs:
        try:
            bookmark_job(current_user.id, job_data)
            count += 1
        except Exception:
            pass
    return jsonify({"status": "ok", "count": count})


@app.route("/jobs/bulk/apply", methods=["POST"])
@login_required
def bulk_apply():
    data = request.get_json() or {}
    jobs = data.get("jobs", [])
    count = 0
    for job_data in jobs:
        try:
            mark_applied(
                current_user.id,
                job_data.get("job_key", ""),
                title=job_data.get("title", ""),
                company=job_data.get("company", ""),
            )
            count += 1
        except Exception:
            pass
    return jsonify({"status": "ok", "count": count})


@app.route("/jobs/bulk/dismiss", methods=["POST"])
@login_required
def bulk_dismiss():
    data = request.get_json() or {}
    jobs = data.get("jobs", [])
    count = 0
    for job_data in jobs:
        try:
            dismiss_job(
                current_user.id,
                job_data.get("job_key", ""),
                title=job_data.get("title", ""),
                company=job_data.get("company", ""),
            )
            count += 1
        except Exception:
            pass
    return jsonify({"status": "ok", "count": count})


# --- LinkedIn Helper ---

@app.route("/jobs/linkedin-note", methods=["POST"])
@login_required
@limiter.limit("10 per minute")
def linkedin_note():
    from services.linkedin_helper import generate_linkedin_note, generate_linkedin_message, get_linkedin_search_url
    data = request.get_json() or {}

    job_title = data.get("title", "")
    company = data.get("company", "")
    recruiter_name = data.get("recruiter_name", "")

    from services.resume_loader import load_resume_or_empty
    resume = load_resume_or_empty(current_user.id)

    note = generate_linkedin_note(resume["text"], job_title, company, user_id=current_user.id)
    message = generate_linkedin_message(resume["text"], job_title, company,
                                         recruiter_name=recruiter_name or None,
                                         user_id=current_user.id)
    search_urls = get_linkedin_search_url(job_title, company)

    return jsonify({
        "connection_note": note,
        "inmail_message": message,
        "search_urls": search_urls,
    })


# --- Networking Advice ---

@app.route("/jobs/networking-advice", methods=["POST"])
@login_required
@limiter.limit("10 per minute")
def networking_advice():
    from services.networking_advisor import get_networking_suggestions
    data = request.get_json() or {}

    job_title = data.get("title", "")
    company = data.get("company", "")
    job_description = data.get("description", "")

    from services.resume_loader import load_resume_or_empty
    resume = load_resume_or_empty(current_user.id)

    result = get_networking_suggestions(resume["text"], job_title, company,
                                        job_description=job_description,
                                        user_id=current_user.id)
    return jsonify(result)


# --- Teams ---

@app.route("/teams")
@login_required
def teams_list():
    teams = get_user_teams(current_user.id)
    return render_template("teams.html", teams=teams)


@app.route("/teams", methods=["POST"])
@login_required
def teams_create():
    name = request.form.get("name", "").strip()
    if not name:
        flash("Team name is required.", "error")
        return redirect(url_for("teams_list"))
    create_team(name, current_user.id)
    flash(f'Team "{name}" created.', "success")
    return redirect(url_for("teams_list"))


@app.route("/teams/<int:tid>")
@login_required
def team_detail(tid):
    if not is_team_member(tid, current_user.id):
        flash("You are not a member of this team.", "error")
        return redirect(url_for("teams_list"))

    team = get_team(tid)
    if not team:
        flash("Team not found.", "error")
        return redirect(url_for("teams_list"))

    members = get_team_members(tid)
    shared_jobs = get_team_shared_jobs(tid)
    activity = get_team_activity(tid, limit=20)
    user_role = get_team_member_role(tid, current_user.id)

    return render_template("team_detail.html", team=team, members=members,
                           shared_jobs=shared_jobs, activity=activity,
                           user_role=user_role)


@app.route("/teams/<int:tid>/invite", methods=["POST"])
@login_required
def team_invite(tid):
    role = get_team_member_role(tid, current_user.id)
    if role != "admin":
        flash("Only team admins can invite members.", "error")
        return redirect(url_for("team_detail", tid=tid))

    email = request.form.get("email", "").strip()
    if not email:
        flash("Email is required.", "error")
        return redirect(url_for("team_detail", tid=tid))

    user = get_user_by_email(email)
    if not user:
        flash("No user found with that email.", "error")
        return redirect(url_for("team_detail", tid=tid))

    if is_team_member(tid, user["id"]):
        flash("User is already a member of this team.", "warning")
        return redirect(url_for("team_detail", tid=tid))

    add_team_member(tid, user["id"], role="member")
    team = get_team(tid)
    create_notification(user["id"],
                        message=f'You were added to team "{team["name"]}"',
                        link="/teams")
    flash(f'Invited {email} to the team.', "success")
    return redirect(url_for("team_detail", tid=tid))


@app.route("/teams/<int:tid>/leave", methods=["POST"])
@login_required
def team_leave(tid):
    if not is_team_member(tid, current_user.id):
        flash("You are not a member of this team.", "error")
        return redirect(url_for("teams_list"))

    team = get_team(tid)
    # If the user is the creator and only admin, delete the team
    role = get_team_member_role(tid, current_user.id)
    if role == "admin" and team["created_by"] == current_user.id:
        members = get_team_members(tid)
        admin_count = sum(1 for m in members if m["role"] == "admin")
        if admin_count <= 1:
            delete_team(tid)
            flash("Team deleted (you were the only admin).", "success")
            return redirect(url_for("teams_list"))

    remove_team_member(tid, current_user.id)
    flash("You left the team.", "success")
    return redirect(url_for("teams_list"))


@app.route("/teams/<int:tid>/share-job", methods=["POST"])
@login_required
def team_share_job(tid):
    if not is_team_member(tid, current_user.id):
        return jsonify({"error": "Not a team member."}), 403

    data = request.get_json() or {}
    job_key = data.get("job_key", "")
    if not job_key:
        return jsonify({"error": "job_key is required."}), 400

    jid = share_job_with_team(
        tid, current_user.id, job_key,
        title=data.get("title", ""),
        company=data.get("company", ""),
        location=data.get("location", ""),
        apply_url=data.get("apply_url", ""),
        notes=data.get("notes", ""),
    )
    return jsonify({"status": "ok", "id": jid})


@app.route("/teams/<int:tid>/jobs/<int:jid>/comment", methods=["POST"])
@login_required
def team_job_comment(tid, jid):
    if not is_team_member(tid, current_user.id):
        return jsonify({"error": "Not a team member."}), 403

    data = request.get_json() or {}
    comment = (data.get("comment") or "").strip()
    if not comment:
        return jsonify({"error": "Comment is required."}), 400

    cid = add_team_job_comment(jid, current_user.id, comment)

    # Notify the job sharer if it's not the commenter
    job = get_team_shared_job(jid)
    if job and job["shared_by"] != current_user.id:
        team = get_team(tid)
        create_notification(
            job["shared_by"],
            message=f'{current_user.name or current_user.email} commented on "{job["title"]}" in {team["name"]}',
            link=f"/teams/{tid}",
        )

    return jsonify({"status": "ok", "id": cid})


@app.route("/teams/<int:tid>/jobs/<int:jid>/comments", methods=["GET"])
@login_required
def team_job_comments_list(tid, jid):
    if not is_team_member(tid, current_user.id):
        return jsonify({"error": "Not a team member."}), 403
    comments = get_team_job_comments(jid)
    return jsonify({"comments": comments})


# --- Elevator Pitch ---

@app.route("/jobs/elevator-pitch", methods=["POST"])
@login_required
@limiter.limit("10 per minute")
def elevator_pitch():
    from services.elevator_pitch import generate_elevator_pitch
    data = request.get_json() or {}

    job_title = data.get("title", "")
    company = data.get("company", "")
    job_description = data.get("description", "")

    from services.resume_loader import require_resume
    resume, err = require_resume(current_user.id)
    if err:
        return err

    result = generate_elevator_pitch(
        resume["text"], job_title, company, job_description,
        user_id=current_user.id,
    )
    return jsonify(result)


# --- Company Research ---

@app.route("/jobs/company-research", methods=["POST"])
@login_required
@limiter.limit("10 per minute")
def company_research():
    from services.company_enricher import generate_company_summary
    data = request.get_json() or {}
    company_name = data.get("company", "").strip()

    if not company_name:
        return jsonify({"error": "Company name is required."}), 400

    # Check existing cached data
    existing = get_cached_company(company_name)

    # Generate AI summary
    summary = generate_company_summary(company_name, existing)

    # Store enhanced data in company_cache
    enhanced = existing or {}
    enhanced["ai_summary"] = summary
    cache_company(company_name, enhanced)

    return jsonify(summary)


# --- Kanban Board ---

@app.route("/kanban")
@login_required
def kanban():
    applied = get_applied_jobs(current_user.id)
    kanban_stages = ["saved", "applied", "screen", "interview", "offer", "rejected", "withdrawn"]
    today = datetime.now().strftime("%Y-%m-%d")

    # Group jobs by stage
    columns = {stage: [] for stage in kanban_stages}
    for job in applied:
        job_dict = dict(job)
        stage = job_dict.get("stage", "applied")
        if stage not in columns:
            columns[stage] = []
        # Compute days in stage
        updated = job_dict.get("updated_at", "")
        if updated:
            try:
                updated_dt = datetime.strptime(updated[:10], "%Y-%m-%d")
                job_dict["days_in_stage"] = (datetime.now() - updated_dt).days
            except (ValueError, TypeError):
                job_dict["days_in_stage"] = None
        else:
            job_dict["days_in_stage"] = None

        # Get contacts for the job (just first contact name)
        contacts = get_job_contacts(current_user.id, job_dict["job_key"])
        job_dict["contact_name"] = contacts[0]["name"] if contacts else None
        columns[stage].append(job_dict)

    return render_template("kanban.html", columns=columns, stages=kanban_stages, today=today)


# --- Search History Trends ---

@app.route("/history/trends")
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


# --- Enhanced Analytics ---

@app.route("/analytics")
@login_required
def analytics():
    from services.analytics import get_search_analytics, get_response_rates, get_funnel_metrics
    data = get_search_analytics(current_user.id)
    response_rates = get_response_rates(current_user.id)
    funnel = get_funnel_metrics(current_user.id)

    # Salary benchmarks
    benchmarks = get_salary_benchmarks(current_user.id)

    return render_template("analytics.html", analytics=data, response_rates=response_rates,
                           funnel=funnel, salary_benchmarks=benchmarks)


# --- API Tokens ---

@app.route("/settings/api-tokens", methods=["POST"])
@login_required
def create_api_token_route():
    token, tid = create_api_token(current_user.id)
    session["new_api_token"] = token
    flash("API token created. Copy it now; it won't be shown again.", "success")
    return redirect(url_for("settings"))


@app.route("/settings/api-tokens/<int:tid>/delete", methods=["POST"])
@login_required
def delete_api_token_route(tid):
    delete_api_token(tid, current_user.id)
    flash("API token revoked.", "success")
    return redirect(url_for("settings"))


# --- Extension API ---

@app.route("/api/extension/my-jobs")
@csrf.exempt
def extension_my_jobs():
    """Return applied/bookmarked job keys for the browser extension. Token auth required."""
    token = request.headers.get("X-API-Token", "")
    if not token:
        auth = request.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            token = auth[7:]
    if not token:
        return jsonify({"error": "Missing API token"}), 401

    user_id = validate_api_token(token)
    if not user_id:
        return jsonify({"error": "Invalid API token"}), 401

    data = get_user_applied_and_bookmarked_keys(user_id)
    return jsonify(data)


# --- Email Import ---

@app.route("/jobs/import-email", methods=["GET"])
@login_required
def import_email():
    return render_template("import_email.html", parsed=None, email_text=None, stages=PIPELINE_STAGES)


@app.route("/jobs/import-email", methods=["POST"])
@login_required
def import_email_post():
    step = request.form.get("step", "parse")
    email_text = request.form.get("email_text", "")

    if step == "parse":
        from services.email_parser import parse_recruiter_email
        parsed = parse_recruiter_email(email_text)
        return render_template("import_email.html", parsed=parsed, email_text=email_text, stages=PIPELINE_STAGES)

    elif step == "confirm":
        title = request.form.get("job_title", "").strip()
        company = request.form.get("company", "").strip()
        location = request.form.get("location", "").strip()
        stage = request.form.get("stage", "applied")
        notes = request.form.get("notes", "").strip()

        if not title or not company:
            flash("Job title and company are required.", "error")
            return redirect(url_for("import_email"))

        # Generate a job key from title + company
        job_key = re.sub(r'[^a-z0-9]+', '-', f"{title}-{company}".lower()).strip('-')

        # Create pipeline entry
        mark_applied(current_user.id, job_key, title, company,
                     notes=notes, location=location, stage=stage)

        # Add recruiter contact if provided
        r_name = request.form.get("recruiter_name", "").strip()
        r_email = request.form.get("recruiter_email", "").strip()
        r_phone = request.form.get("recruiter_phone", "").strip()

        if r_name or r_email or r_phone:
            add_job_contact(current_user.id, job_key,
                            name=r_name, email=r_email, phone=r_phone,
                            role="Recruiter")

        flash(f"Imported '{title}' at {company} to pipeline.", "success")
        return redirect(url_for("pipeline"))

    return redirect(url_for("import_email"))


# --- Data Export ---

@app.route("/export/full")
@login_required
def export_full():
    """Export all user data as a ZIP file."""
    user_id = current_user.id
    buf = io.BytesIO()

    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        # Applied jobs
        applied = get_applied_jobs(user_id)
        csv_buf = io.StringIO()
        if applied:
            writer = csv.DictWriter(csv_buf, fieldnames=dict(applied[0]).keys())
            writer.writeheader()
            for row in applied:
                writer.writerow(dict(row))
        zf.writestr("applied_jobs.csv", csv_buf.getvalue())

        # Bookmarked jobs
        bookmarked = get_bookmarked_jobs(user_id)
        csv_buf = io.StringIO()
        if bookmarked:
            writer = csv.DictWriter(csv_buf, fieldnames=dict(bookmarked[0]).keys())
            writer.writeheader()
            for row in bookmarked:
                writer.writerow(dict(row))
        zf.writestr("bookmarked_jobs.csv", csv_buf.getvalue())

        # Search history
        history = get_search_history(user_id, limit=1000)
        csv_buf = io.StringIO()
        if history:
            writer = csv.DictWriter(csv_buf, fieldnames=dict(history[0]).keys())
            writer.writeheader()
            for row in history:
                writer.writerow(dict(row))
        zf.writestr("search_history.csv", csv_buf.getvalue())

        # Resumes (text only)
        resumes = get_resumes(user_id)
        csv_buf = io.StringIO()
        if resumes:
            fields = ["id", "name", "raw_text", "skills_json", "is_default", "created_at", "updated_at"]
            writer = csv.DictWriter(csv_buf, fieldnames=fields)
            writer.writeheader()
            for r in resumes:
                rd = dict(r)
                writer.writerow({k: rd.get(k, "") for k in fields})
        zf.writestr("resumes.csv", csv_buf.getvalue())

        # Contacts
        from database import get_db, _safe_close
        conn = get_db()
        contacts = conn.execute(
            "SELECT * FROM job_contacts WHERE user_id = ? ORDER BY created_at DESC",
            (user_id,),
        ).fetchall()
        _safe_close(conn)
        csv_buf = io.StringIO()
        if contacts:
            writer = csv.DictWriter(csv_buf, fieldnames=dict(contacts[0]).keys())
            writer.writeheader()
            for row in contacts:
                writer.writerow(dict(row))
        zf.writestr("contacts.csv", csv_buf.getvalue())

        # Settings
        user_settings = get_user_settings(user_id)
        zf.writestr("settings.json", json.dumps(user_settings, indent=2, default=str))

    buf.seek(0)
    return send_file(
        buf,
        mimetype="application/zip",
        as_attachment=True,
        download_name=f"nexus-export-{datetime.utcnow().strftime('%Y%m%d')}.zip",
    )


# --- API Documentation ---

@app.route("/api/docs")
@login_required
def api_docs():
    return render_template("api_docs.html")


# --- Google OAuth ---

@app.route("/auth/google")
def google_login():
    """Redirect to Google OAuth consent screen."""
    if not Config.GOOGLE_CLIENT_ID:
        flash("Google login is not configured.", "error")
        return redirect(url_for("login"))

    import secrets as _secrets
    state = _secrets.token_urlsafe(32)
    session["oauth_state"] = state

    params = {
        "client_id": Config.GOOGLE_CLIENT_ID,
        "redirect_uri": Config.GOOGLE_REDIRECT_URI,
        "response_type": "code",
        "scope": "openid email profile",
        "access_type": "offline",
        "state": state,
    }
    query = "&".join(f"{k}={v}" for k, v in params.items())
    return redirect(f"https://accounts.google.com/o/oauth2/v2/auth?{query}")


@app.route("/auth/google/callback")
def google_callback():
    """Handle Google OAuth callback."""
    if not Config.GOOGLE_CLIENT_ID:
        flash("Google login is not configured.", "error")
        return redirect(url_for("login"))

    error = request.args.get("error")
    if error:
        flash(f"Google login failed: {error}", "error")
        return redirect(url_for("login"))

    code = request.args.get("code")
    state = request.args.get("state")

    # Verify state
    if state != session.pop("oauth_state", None):
        flash("Invalid OAuth state. Please try again.", "error")
        return redirect(url_for("login"))

    if not code:
        flash("No authorization code received.", "error")
        return redirect(url_for("login"))

    try:
        import requests as _requests

        # Exchange code for token
        token_response = _requests.post(
            "https://oauth2.googleapis.com/token",
            data={
                "code": code,
                "client_id": Config.GOOGLE_CLIENT_ID,
                "client_secret": Config.GOOGLE_CLIENT_SECRET,
                "redirect_uri": Config.GOOGLE_REDIRECT_URI,
                "grant_type": "authorization_code",
            },
            timeout=10,
        )
        token_response.raise_for_status()
        tokens = token_response.json()

        # Get user info
        userinfo_response = _requests.get(
            "https://www.googleapis.com/oauth2/v2/userinfo",
            headers={"Authorization": f"Bearer {tokens['access_token']}"},
            timeout=10,
        )
        userinfo_response.raise_for_status()
        userinfo = userinfo_response.json()

        google_id = userinfo.get("id")
        email = userinfo.get("email", "").lower()
        name = userinfo.get("name", "")

        if not google_id or not email:
            flash("Could not retrieve your Google account info.", "error")
            return redirect(url_for("login"))

        # Check if OAuth account exists
        oauth_acc = get_oauth_account("google", google_id)
        if oauth_acc:
            # Existing OAuth link - log in
            user_data = get_user_by_id(oauth_acc["user_id"])
            if user_data:
                login_user(User(user_data), remember=True)
                flash("Logged in with Google.", "success")
                return redirect(url_for("index"))

        # Check if user with this email already exists
        existing_user = get_user_by_email(email)
        if existing_user:
            # Link Google to existing account
            link_oauth_account(existing_user["id"], "google", google_id, email)
            login_user(User(existing_user), remember=True)
            flash("Google account linked and logged in.", "success")
            return redirect(url_for("index"))

        # Create new user
        user_id = create_user_oauth(email, name)
        if user_id:
            create_oauth_account(user_id, "google", google_id, email)
            user_data = get_user_by_id(user_id)
            login_user(User(user_data), remember=True)
            flash("Account created with Google. Welcome!", "success")
            return redirect(url_for("index"))
        else:
            flash("Failed to create account.", "error")
            return redirect(url_for("login"))

    except Exception as e:
        logger.error("Google OAuth failed: %s", e)
        flash("Google login failed. Please try again.", "error")
        return redirect(url_for("login"))


# --- Admin ---

def admin_required(f):
    """Decorator to require admin access."""
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for("login"))
        if not is_user_admin(current_user.id):
            flash("Admin access required.", "error")
            return redirect(url_for("index"))
        return f(*args, **kwargs)
    return decorated


@app.route("/admin")
@admin_required
def admin_dashboard():
    stats = get_admin_stats()
    return render_template("admin.html", stats=stats)


@app.route("/admin/users")
@admin_required
def admin_users():
    users = get_admin_users()
    return render_template("admin_users.html", users=users)


# --- Startup ---

with app.app_context():
    os.makedirs(os.path.dirname(Config.DB_PATH) or ".", exist_ok=True)
    init_db()
    from database import purge_old_api_usage
    purge_old_api_usage(days=90)
    warnings = Config.validate()
    for w in warnings:
        logger.warning(w)

# Register API v1 blueprint
from api_v1 import api_v1
app.register_blueprint(api_v1)
csrf.exempt(api_v1)

from scheduler import init_scheduler
init_scheduler(app)

if __name__ == "__main__":
    app.run(debug=True, port=5000)
