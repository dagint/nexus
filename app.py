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
    init_db, get_user_by_id,
    create_saved_search, get_saved_searches, delete_saved_search,
    toggle_saved_search, toggle_all_saved_searches,
    get_applied_jobs, get_applied_stats, PIPELINE_STAGES,
    get_user_settings,
    get_resumes,
    get_search_history,
    get_bookmarked_job_keys, get_bookmarked_jobs,
    get_unread_count,
    get_api_usage_summary, get_api_usage_daily, get_api_usage_recent,
    get_search_templates, create_search_template, delete_search_template,
    get_all_interview_preps, get_interview_prep_by_id, delete_interview_prep,
    get_user_due_follow_ups,
    get_salary_benchmarks,
    validate_api_token, get_user_applied_and_bookmarked_keys,
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
login_manager.login_view = "auth.login"
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


# --- Alerts ---

@app.route("/alerts", methods=["GET"])
@login_required
def alerts():
    saved = get_saved_searches(current_user.id)
    return render_template("alerts.html", saved_searches=saved)


@app.route("/alerts", methods=["POST"])
@login_required
def create_alert():
    query = request.form.get("query", "").strip()
    location = request.form.get("location", "").strip()
    remote_only = bool(request.form.get("remote_only"))
    frequency = request.form.get("frequency", "daily")

    if not query:
        flash("Search query is required.", "error")
        return redirect(url_for("alerts"))

    create_saved_search(
        current_user.id, query, location, remote_only,
        frequency=frequency,
    )
    flash("Alert created! You'll be notified of new matches.", "success")
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
    new_state = toggle_saved_search(alert_id, current_user.id)
    if new_state is not None:
        status = "enabled" if new_state else "paused"
        flash(f"Alert {status}.", "success")
    return redirect(url_for("alerts"))


@app.route("/alerts/toggle-all", methods=["POST"])
@login_required
def toggle_all_alerts():
    action = request.form.get("action", "pause")
    is_active = action != "pause"
    toggle_all_saved_searches(current_user.id, is_active)
    flash(f"All alerts {'enabled' if is_active else 'paused'}.", "success")
    return redirect(url_for("alerts"))


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

# Register feature blueprints
from blueprints.auth import auth_bp, init_auth_limiter
from blueprints.jobs import jobs_bp, init_jobs_limiter
from blueprints.search import search_bp, init_search_limiter
from blueprints.pipeline import pipeline_bp
from blueprints.resumes import resumes_bp
from blueprints.teams import teams_bp
from blueprints.settings import settings_bp
from blueprints.admin import admin_bp

app.register_blueprint(auth_bp)
app.register_blueprint(jobs_bp)
app.register_blueprint(search_bp)
app.register_blueprint(pipeline_bp)
app.register_blueprint(resumes_bp)
app.register_blueprint(teams_bp)
app.register_blueprint(settings_bp)
app.register_blueprint(admin_bp)

# Apply rate limits to blueprint routes
init_auth_limiter(limiter)
init_jobs_limiter(limiter)
init_search_limiter(limiter)

from scheduler import init_scheduler
init_scheduler(app)

if __name__ == "__main__":
    app.run(debug=True, port=5000)
