"""Public REST API v1 Blueprint with token authentication and rate limiting."""
import functools
import logging
import time
from collections import defaultdict

from flask import Blueprint, jsonify, request, g

from database import (
    validate_api_token, get_applied_jobs, get_applied_job_keys,
    get_bookmarked_jobs, get_bookmarked_job_keys, bookmark_job, unbookmark_job,
    update_applied_stage, get_applied_stats, PIPELINE_STAGES,
)

logger = logging.getLogger(__name__)

api_v1 = Blueprint("api_v1", __name__, url_prefix="/api/v1")

# Simple in-memory rate limiter for API tokens
_rate_limit_store = defaultdict(list)
RATE_LIMIT = 30  # requests per minute


def _check_rate_limit(token_key):
    """Check if the token has exceeded the rate limit. Returns True if allowed."""
    now = time.time()
    window = now - 60
    # Clean old entries
    _rate_limit_store[token_key] = [t for t in _rate_limit_store[token_key] if t > window]
    if len(_rate_limit_store[token_key]) >= RATE_LIMIT:
        return False
    _rate_limit_store[token_key].append(now)
    return True


def _api_response(data=None, meta=None, status=200):
    """Build a consistent API response."""
    body = {"data": data}
    if meta is not None:
        body["meta"] = meta
    return jsonify(body), status


def _api_error(message, status=400):
    """Build a consistent error response."""
    return jsonify({"error": message}), status


def token_required(f):
    """Decorator to require API token authentication."""
    @functools.wraps(f)
    def decorated(*args, **kwargs):
        token = request.headers.get("X-API-Token", "")
        if not token:
            # Also check Authorization: Bearer
            auth = request.headers.get("Authorization", "")
            if auth.startswith("Bearer "):
                token = auth[7:]

        if not token:
            return _api_error("Missing API token. Provide X-API-Token header.", 401)

        user_id = validate_api_token(token)
        if not user_id:
            return _api_error("Invalid API token.", 401)

        # Rate limiting
        if not _check_rate_limit(f"token:{user_id}"):
            return _api_error("Rate limit exceeded. Max 30 requests per minute.", 429)

        g.api_user_id = user_id
        return f(*args, **kwargs)
    return decorated


# --- Jobs Search ---

@api_v1.route("/jobs/search")
@token_required
def api_search_jobs():
    """Search for jobs. Query params: q (required), location, remote_only, page."""
    query = request.args.get("q", "").strip()
    if not query:
        return _api_error("Query parameter 'q' is required.")

    location = request.args.get("location", "")
    remote_only = request.args.get("remote_only", "false").lower() in ("true", "1")
    page = max(1, int(request.args.get("page", 1)))

    try:
        from services.job_search import search_all
        jobs = search_all(query, location, remote_only)

        # Paginate
        per_page = 20
        start = (page - 1) * per_page
        total = len(jobs)
        page_jobs = jobs[start:start + per_page]

        # Serialize
        results = []
        for j in page_jobs:
            results.append({
                "job_key": j.get("job_key", ""),
                "title": j.get("title", ""),
                "company": j.get("company", ""),
                "location": j.get("location", ""),
                "apply_url": j.get("apply_url", ""),
                "salary_min": j.get("salary_min"),
                "salary_max": j.get("salary_max"),
                "remote_status": j.get("remote_status", ""),
                "source": j.get("source", ""),
                "posted_at": j.get("posted_at", ""),
                "match_score": j.get("match_score"),
            })

        return _api_response(results, meta={"total": total, "page": page, "per_page": per_page})
    except Exception as e:
        logger.error("API search failed: %s", e)
        return _api_error("Search failed.", 500)


# --- Pipeline ---

@api_v1.route("/pipeline")
@token_required
def api_pipeline():
    """List all applied jobs."""
    stage = request.args.get("stage")
    if stage and stage not in PIPELINE_STAGES:
        return _api_error(f"Invalid stage. Valid stages: {', '.join(PIPELINE_STAGES)}")

    jobs = get_applied_jobs(g.api_user_id, stage=stage)
    results = []
    for j in jobs:
        results.append({
            "job_key": j["job_key"],
            "title": j["title"],
            "company": j["company"],
            "location": j["location"],
            "apply_url": j["apply_url"],
            "stage": j["stage"],
            "notes": j["notes"],
            "applied_at": j["applied_at"],
            "updated_at": j["updated_at"],
            "follow_up_date": j.get("follow_up_date"),
        })

    return _api_response(results, meta={"total": len(results)})


@api_v1.route("/pipeline/<job_key>/stage", methods=["POST"])
@token_required
def api_update_stage(job_key):
    """Update the pipeline stage of a job."""
    data = request.get_json(silent=True) or {}
    stage = data.get("stage", "")
    if stage not in PIPELINE_STAGES:
        return _api_error(f"Invalid stage. Valid stages: {', '.join(PIPELINE_STAGES)}")

    notes = data.get("notes")
    update_applied_stage(g.api_user_id, job_key, stage, notes)
    return _api_response({"job_key": job_key, "stage": stage})


# --- Bookmarks ---

@api_v1.route("/bookmarks")
@token_required
def api_bookmarks():
    """List bookmarked jobs."""
    jobs = get_bookmarked_jobs(g.api_user_id)
    results = []
    for j in jobs:
        results.append({
            "job_key": j["job_key"],
            "title": j["title"],
            "company": j["company"],
            "location": j["location"],
            "apply_url": j["apply_url"],
            "bookmarked_at": j["bookmarked_at"],
            "match_score": j.get("match_score"),
        })
    return _api_response(results, meta={"total": len(results)})


@api_v1.route("/bookmarks", methods=["POST"])
@token_required
def api_add_bookmark():
    """Add a bookmark. Body: {job_key, title, company, ...}."""
    data = request.get_json(silent=True) or {}
    if not data.get("job_key"):
        return _api_error("job_key is required.")
    bookmark_job(g.api_user_id, data)
    return _api_response({"job_key": data["job_key"], "status": "bookmarked"}, status=201)


@api_v1.route("/bookmarks/<job_key>", methods=["DELETE"])
@token_required
def api_remove_bookmark(job_key):
    """Remove a bookmark."""
    unbookmark_job(g.api_user_id, job_key)
    return _api_response({"job_key": job_key, "status": "removed"})


# --- Analytics ---

@api_v1.route("/analytics")
@token_required
def api_analytics():
    """Get summary stats."""
    stats = get_applied_stats(g.api_user_id)
    bookmarked = get_bookmarked_job_keys(g.api_user_id)
    applied = get_applied_job_keys(g.api_user_id)

    data = {
        "total_applied": len(applied),
        "total_bookmarked": len(bookmarked),
        "pipeline_stages": dict(stats),
    }
    return _api_response(data)
