import csv
import io
import json
import logging
import os

from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, Response
from flask_wtf.csrf import CSRFProtect
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user

from config import Config
from logging_config import setup_logging
from database import (
    init_db, get_user_by_id, create_user, authenticate_user,
    create_saved_search, get_saved_searches, delete_saved_search,
    mark_applied, unmark_applied, get_applied_job_keys, get_applied_jobs,
    get_applied_stats, update_applied_stage, update_applied_notes, PIPELINE_STAGES,
    get_user_settings, update_user_settings,
    save_resume, get_resumes, get_resume, get_default_resume,
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
)

setup_logging()
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.config.from_object(Config)

RESULTS_PER_PAGE = 20

# Security
csrf = CSRFProtect(app)
limiter = Limiter(
    app=app,
    key_func=get_remote_address,
    default_limits=["60 per minute"],
    storage_uri="memory://",
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


@login_manager.user_loader
def load_user(user_id):
    data = get_user_by_id(int(user_id))
    if data:
        return User(data)
    return None


@app.after_request
def set_security_headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "style-src 'self' 'unsafe-inline'; "
        "script-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; "
        "font-src 'self';"
    )
    return response


@app.context_processor
def inject_notification_count():
    if current_user.is_authenticated:
        return {"notification_count": get_unread_count(current_user.id)}
    return {"notification_count": 0}


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

        update_user_password(user_id, new_password)
        consume_reset_token(token)
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
    if current_user.is_authenticated:
        saved_resumes = get_resumes(current_user.id)
    return render_template("index.html", saved_resumes=saved_resumes)


@app.route("/search", methods=["GET", "POST"])
@limiter.limit("10 per minute")
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

        # Use saved resume for GET re-searches
        if current_user.is_authenticated and not resume_data:
            default = get_default_resume(current_user.id)
            if default:
                resume_text = default["raw_text"]
                resume_id = default["id"]
                if default.get("skills_json"):
                    resume_data = json.loads(default["skills_json"])

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
        jobs = search_all(query, location, remote_only, date_posted)
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

    # Commute check for non-remote jobs
    if current_user.is_authenticated and location:
        try:
            from services.commute_checker import check_commute_for_jobs
            settings = get_user_settings(current_user.id)
            max_commute = settings.get("max_commute_minutes", 60)
            jobs = check_commute_for_jobs(jobs, location, max_commute)
        except Exception as e:
            logger.warning("Commute check failed: %s", e)

    # Score and tier
    user_prefs = {}
    preference_profile = None
    if resume_data:
        if current_user.is_authenticated:
            user_prefs = get_user_settings(current_user.id)
            # Build preference profile from bookmarked/applied/dismissed jobs
            try:
                from services.preference_learner import build_preference_profile
                preference_profile = build_preference_profile(current_user.id)
            except Exception as e:
                logger.warning("Preference learning failed: %s", e)
        if remote_only:
            user_prefs["remote_only"] = True
        jobs = score_jobs(jobs, resume_data, user_prefs, preference_profile)

        # Generate heuristic summaries only (AI summaries are on-demand via button)
        for job in jobs:
            if job.get("match_tier") == "strong" and job.get("match_reasons"):
                job["match_summary"] = "Matches your profile: " + "; ".join(job["match_reasons"][:3]) + "."

    # Role velocity signal
    from database import get_role_velocity
    for job in jobs:
        try:
            velocity = get_role_velocity(job.get("company", ""), job.get("title", ""))
            job["role_velocity"] = velocity if velocity > 1 else None
        except Exception:
            job["role_velocity"] = None

    # Sort
    sort_by = request.args.get("sort", request.form.get("sort", "score"))
    if sort_by == "date":
        jobs.sort(key=lambda j: j.get("posted_date", ""), reverse=True)
    elif sort_by == "salary":
        jobs.sort(key=lambda j: j.get("salary_annual_max") or j.get("salary_annual_min") or j.get("salary_max") or j.get("salary_min") or 0, reverse=True)
    else:
        jobs = sort_within_tiers(jobs)

    # Record search history
    if current_user.is_authenticated:
        add_search_history(current_user.id, query, location, remote_only, resume_id, len(jobs))
        if len(jobs) > 0:
            create_notification(
                current_user.id,
                f"Found {len(jobs)} jobs for \"{query}\"",
                url_for("search", query=query, location=location),
            )

    # Pagination
    page = int(request.args.get("page", request.form.get("page", 1)))
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
        all_jobs=jobs,  # For export
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
                      "Posted Date", "Source", "Apply URL"])
    for job in jobs:
        writer.writerow([
            job.get("title", ""), job.get("company", ""), job.get("location", ""),
            job.get("remote_status", ""), job.get("salary_min", ""), job.get("salary_max", ""),
            job.get("posted_date", ""), job.get("source", ""), job.get("apply_url", ""),
        ])

    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename=jobs_{query.replace(' ', '_')}.csv"},
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


# --- Applied Jobs / Pipeline ---

@app.route("/jobs/<job_key>/applied", methods=["POST"])
@csrf.exempt
@login_required
def mark_job_applied(job_key):
    data = request.get_json() or {}
    mark_applied(
        current_user.id, job_key,
        data.get("title", ""), data.get("company", ""),
        data.get("notes", ""), data.get("location", ""),
        data.get("apply_url", ""), data.get("stage", "applied"),
    )
    return jsonify({"status": "ok"})


@app.route("/jobs/<job_key>/applied", methods=["DELETE"])
@csrf.exempt
@login_required
def unmark_job_applied(job_key):
    unmark_applied(current_user.id, job_key)
    return jsonify({"status": "ok"})


@app.route("/jobs/<job_key>/stage", methods=["POST"])
@csrf.exempt
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
@csrf.exempt
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
    return render_template("pipeline.html", jobs=applied, stats=stats,
                           stages=PIPELINE_STAGES, current_stage=stage_filter)


# --- Bookmarks ---

@app.route("/jobs/<job_key>/bookmark", methods=["POST"])
@csrf.exempt
@login_required
def bookmark_job_route(job_key):
    data = request.get_json() or {}
    data["job_key"] = job_key
    bookmark_job(current_user.id, data)
    return jsonify({"status": "ok"})


@app.route("/jobs/<job_key>/bookmark", methods=["DELETE"])
@csrf.exempt
@login_required
def unbookmark_job_route(job_key):
    unbookmark_job(current_user.id, job_key)
    return jsonify({"status": "ok"})


# --- Dismissed Jobs ---

@app.route("/jobs/<job_key>/dismiss", methods=["POST"])
@csrf.exempt
@login_required
def dismiss_job_route(job_key):
    data = request.get_json() or {}
    dismiss_job(
        current_user.id, job_key,
        data.get("title", ""), data.get("company", ""),
    )
    return jsonify({"status": "ok"})


@app.route("/jobs/<job_key>/dismiss", methods=["DELETE"])
@csrf.exempt
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
@csrf.exempt
@login_required
def generate_cover_letter_route():
    from services.cover_letter import generate_cover_letter
    data = request.get_json() or {}

    job_title = data.get("title", "")
    company = data.get("company", "")
    job_description = data.get("description", "")

    # Get user's default resume
    default = get_default_resume(current_user.id)
    if not default:
        return jsonify({"error": "No resume saved. Upload a resume first."}), 400

    letter = generate_cover_letter(
        default["raw_text"], job_title, company, job_description,
        user_name=current_user.name
    )

    return jsonify({"cover_letter": letter})


# --- Screening Answers ---

@app.route("/jobs/screening-answers", methods=["POST"])
@csrf.exempt
@login_required
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

    default = get_default_resume(current_user.id)
    resume_text = default["raw_text"] if default else ""

    answers = generate_screening_answers(
        resume_text, job_title, company, job_description, questions,
        user_name=current_user.name
    )

    return jsonify({"answers": answers})


# --- Application Draft ---

@app.route("/jobs/application-draft", methods=["POST"])
@csrf.exempt
@login_required
def application_draft():
    """Generate an application draft."""
    from services.application_drafter import generate_application_draft
    data = request.get_json() or {}

    job_title = data.get("title", "")
    company = data.get("company", "")
    job_description = data.get("description", "")

    default = get_default_resume(current_user.id)
    if not default:
        return jsonify({"error": "No resume saved. Upload a resume first."}), 400

    resume_text = default["raw_text"]
    resume_data = {}
    if default.get("skills_json"):
        resume_data = json.loads(default["skills_json"])

    draft = generate_application_draft(
        resume_text, resume_data, job_title, company, job_description,
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
@csrf.exempt
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
    searches = get_search_history(current_user.id)
    return render_template("history.html", searches=searches)


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
    return render_template("settings.html", settings=user_settings, api_status=api_status)


@app.route("/settings", methods=["POST"])
@login_required
def save_settings():
    update_user_settings(
        current_user.id,
        name=request.form.get("name", ""),
        timezone=request.form.get("timezone", "UTC"),
        max_commute_minutes=int(request.form.get("max_commute_minutes", 60)),
        seniority_tier=request.form.get("seniority_tier", ""),
        blocked_companies=request.form.get("blocked_companies", ""),
    )
    flash("Settings saved.", "success")
    return redirect(url_for("settings"))


# --- Notifications ---

@app.route("/notifications")
@csrf.exempt
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
@csrf.exempt
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

    return render_template(
        "job_detail.html", job=job,
        applied_keys=applied_keys, bookmarked_keys=bookmarked_keys, dismissed_keys=dismissed_keys,
    )


# --- Analytics ---

@app.route("/analytics")
@login_required
def analytics():
    from services.analytics import get_search_analytics
    data = get_search_analytics(current_user.id)
    return render_template("analytics.html", analytics=data)


# --- Interview Prep ---

@app.route("/jobs/interview-prep", methods=["POST"])
@csrf.exempt
@login_required
def interview_prep():
    from services.interview_prep import generate_interview_prep
    data = request.get_json() or {}

    default = get_default_resume(current_user.id)
    if not default:
        return jsonify({"error": "No resume saved. Upload a resume first."}), 400

    result = generate_interview_prep(
        default["raw_text"],
        data.get("title", ""),
        data.get("company", ""),
        data.get("description", ""),
        user_name=current_user.name,
    )
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
    update_applied_stage(job_key, current_user.id, "interview")
    update_applied_notes(job_key, current_user.id, schedule_note)
    flash("Interview scheduled.", "success")
    return redirect(url_for("calendar"))


@app.route("/calendar/ics/<job_key>")
@login_required
def download_ics(job_key):
    """Generate an ICS file for an interview."""
    from datetime import datetime, timedelta
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
    import re
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

    ics = f"""BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Job Search Tool//EN
BEGIN:VEVENT
DTSTART:{interview_dt.strftime('%Y%m%dT%H%M%S')}
DTEND:{end_dt.strftime('%Y%m%dT%H%M%S')}
DTSTAMP:{now.strftime('%Y%m%dT%H%M%SZ')}
SUMMARY:Interview - {job['title']} at {job['company']}
DESCRIPTION:Interview for {job['title']} at {job['company']}
END:VEVENT
END:VCALENDAR"""

    return Response(
        ics,
        mimetype="text/calendar",
        headers={"Content-Disposition": f"attachment; filename=interview_{job_key}.ics"},
    )



# --- Startup ---

with app.app_context():
    os.makedirs(os.path.dirname(Config.DB_PATH) or ".", exist_ok=True)
    init_db()
    warnings = Config.validate()
    for w in warnings:
        logger.warning(w)

from scheduler import init_scheduler
init_scheduler(app)

if __name__ == "__main__":
    app.run(debug=True, port=5000)
