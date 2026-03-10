import csv
import io
import json
import logging
import re

from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required, current_user

from database import (
    mark_applied, unmark_applied,
    get_applied_job_keys, get_applied_jobs,
    update_applied_stage, update_applied_notes, PIPELINE_STAGES,
    get_user_settings, update_user_settings,
    bookmark_job, unbookmark_job,
    get_bookmarked_jobs, get_bookmarked_job_keys,
    dismiss_job, undismiss_job, get_dismissed_job_keys,
    create_shared_job, get_shared_job,
    add_job_contact, get_job_contacts, delete_job_contact,
    update_follow_up_date,
    get_cached_interview_prep, save_interview_prep,
    snapshot_job_description, get_job_description_snapshots,
    get_cached_company, cache_company,
    get_merge_sources,
)

logger = logging.getLogger(__name__)

jobs_bp = Blueprint("jobs", __name__)


def init_jobs_limiter(limiter):
    """Apply rate limits to AI-powered job routes. Called during blueprint registration."""
    rate = "10 per minute"
    limiter.limit(rate)(generate_cover_letter_route)
    limiter.limit(rate)(screening_answers)
    limiter.limit(rate)(application_draft)
    limiter.limit(rate)(interview_prep)
    limiter.limit(rate)(tailor_resume_route)
    limiter.limit(rate)(linkedin_note)
    limiter.limit(rate)(networking_advice)
    limiter.limit(rate)(elevator_pitch)
    limiter.limit(rate)(company_research)


# --- Applied Jobs / Pipeline ---

@jobs_bp.route("/jobs/<job_key>/applied", methods=["POST"])
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


@jobs_bp.route("/jobs/<job_key>/applied", methods=["DELETE"])
@login_required
def unmark_job_applied(job_key):
    unmark_applied(current_user.id, job_key)
    return jsonify({"status": "ok"})


@jobs_bp.route("/jobs/<job_key>/stage", methods=["POST"])
@login_required
def update_job_stage(job_key):
    data = request.get_json() or {}
    stage = data.get("stage", "applied")
    notes = data.get("notes")
    if stage not in PIPELINE_STAGES:
        return jsonify({"error": "Invalid stage"}), 400
    update_applied_stage(current_user.id, job_key, stage, notes)
    return jsonify({"status": "ok", "stage": stage})


@jobs_bp.route("/jobs/<job_key>/notes", methods=["POST"])
@login_required
def update_job_notes(job_key):
    data = request.get_json() or {}
    update_applied_notes(current_user.id, job_key, data.get("notes", ""))
    return jsonify({"status": "ok"})


# --- Bookmarks ---

@jobs_bp.route("/jobs/<job_key>/bookmark", methods=["POST"])
@login_required
def bookmark_job_route(job_key):
    data = request.get_json() or {}
    data["job_key"] = job_key
    bookmark_job(current_user.id, data)
    return jsonify({"status": "ok"})


@jobs_bp.route("/jobs/<job_key>/bookmark", methods=["DELETE"])
@login_required
def unbookmark_job_route(job_key):
    unbookmark_job(current_user.id, job_key)
    return jsonify({"status": "ok"})


# --- Dismissed Jobs ---

@jobs_bp.route("/jobs/<job_key>/dismiss", methods=["POST"])
@login_required
def dismiss_job_route(job_key):
    data = request.get_json() or {}
    dismiss_job(
        current_user.id, job_key,
        data.get("title", ""), data.get("company", ""),
    )
    return jsonify({"status": "ok"})


@jobs_bp.route("/jobs/<job_key>/dismiss", methods=["DELETE"])
@login_required
def undismiss_job_route(job_key):
    undismiss_job(current_user.id, job_key)
    return jsonify({"status": "ok"})


# --- Cover Letter ---

@jobs_bp.route("/jobs/cover-letter", methods=["POST"])
@login_required
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

@jobs_bp.route("/jobs/screening-answers", methods=["POST"])
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

    from services.resume_loader import load_resume_or_empty
    resume = load_resume_or_empty(current_user.id)

    answers = generate_screening_answers(
        resume["text"], job_title, company, job_description, questions,
        user_name=current_user.name
    )

    return jsonify({"answers": answers})


# --- Application Draft ---

@jobs_bp.route("/jobs/application-draft", methods=["POST"])
@login_required
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


# --- Share Job ---

@jobs_bp.route("/jobs/share", methods=["POST"])
@login_required
def share_job():
    data = request.get_json() or {}
    if not data.get("title"):
        return jsonify({"error": "Job data required"}), 400
    token = create_shared_job(current_user.id, data)
    share_url = request.url_root.rstrip("/") + url_for("jobs.view_shared_job", token=token)
    return jsonify({"share_url": share_url, "token": token})


@jobs_bp.route("/shared/<token>")
def view_shared_job(token):
    job = get_shared_job(token)
    if not job:
        flash("Shared job not found or has expired.", "error")
        return redirect(url_for("index"))
    return render_template("shared_job.html", job=job)


# --- Job Detail ---

@jobs_bp.route("/jobs/<job_key>")
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


@jobs_bp.route("/jobs/<job_key>/description-diff")
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


# --- Job Contacts ---

@jobs_bp.route("/jobs/<job_key>/contacts", methods=["POST"])
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


@jobs_bp.route("/jobs/<job_key>/contacts", methods=["GET"])
@login_required
def list_contacts(job_key):
    contacts = get_job_contacts(current_user.id, job_key)
    return jsonify({"contacts": contacts})


@jobs_bp.route("/jobs/<job_key>/contacts/<int:cid>", methods=["DELETE"])
@login_required
def remove_contact(job_key, cid):
    delete_job_contact(cid, current_user.id)
    return jsonify({"status": "ok"})


@jobs_bp.route("/jobs/<job_key>/follow-up", methods=["POST"])
@login_required
def set_follow_up(job_key):
    data = request.get_json() or {}
    update_follow_up_date(current_user.id, job_key, data.get("follow_up_date", ""))
    return jsonify({"status": "ok"})


# --- Interview Prep ---

@jobs_bp.route("/jobs/interview-prep", methods=["POST"])
@login_required
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


# --- CSV Import ---

@jobs_bp.route("/jobs/import-csv", methods=["POST"])
@login_required
def import_csv_route():
    """Import job listings from a CSV file."""
    file = request.files.get("csv_file")
    if not file or not file.filename:
        flash("No file selected.", "error")
        return redirect(url_for("pipeline.bookmarks"))

    if not file.filename.lower().endswith(".csv"):
        flash("Please upload a CSV file.", "error")
        return redirect(url_for("pipeline.bookmarks"))

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

    return redirect(url_for("pipeline.bookmarks"))


# --- Resume Tailoring ---

@jobs_bp.route("/jobs/tailor-resume", methods=["POST"])
@login_required
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

@jobs_bp.route("/jobs/autofill-data", methods=["GET"])
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


# --- Bulk Actions ---

@jobs_bp.route("/jobs/bulk/bookmark", methods=["POST"])
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


@jobs_bp.route("/jobs/bulk/apply", methods=["POST"])
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


@jobs_bp.route("/jobs/bulk/dismiss", methods=["POST"])
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

@jobs_bp.route("/jobs/linkedin-note", methods=["POST"])
@login_required
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

@jobs_bp.route("/jobs/networking-advice", methods=["POST"])
@login_required
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


# --- Elevator Pitch ---

@jobs_bp.route("/jobs/elevator-pitch", methods=["POST"])
@login_required
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

@jobs_bp.route("/jobs/company-research", methods=["POST"])
@login_required
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


# --- Email Import ---

@jobs_bp.route("/jobs/import-email", methods=["GET"])
@login_required
def import_email():
    return render_template("import_email.html", parsed=None, email_text=None, stages=PIPELINE_STAGES)


@jobs_bp.route("/jobs/import-email", methods=["POST"])
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
            return redirect(url_for("jobs.import_email"))

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
        return redirect(url_for("pipeline.pipeline"))

    return redirect(url_for("jobs.import_email"))
