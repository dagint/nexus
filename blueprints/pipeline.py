import re
import logging
from datetime import datetime, timedelta

from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, Response
from flask_login import login_required, current_user

from database import (
    get_applied_jobs, get_applied_stats, get_bookmarked_jobs, get_applied_job_keys,
    update_applied_stage, update_applied_notes,
    get_job_contacts, PIPELINE_STAGES,
)

logger = logging.getLogger(__name__)

pipeline_bp = Blueprint("pipeline", __name__)


@pipeline_bp.route("/pipeline")
@login_required
def pipeline():
    stage_filter = request.args.get("stage")
    applied = get_applied_jobs(current_user.id, stage_filter)
    stats = get_applied_stats(current_user.id)
    today = datetime.now().strftime("%Y-%m-%d")
    return render_template("pipeline.html", jobs=applied, stats=stats,
                           stages=PIPELINE_STAGES, current_stage=stage_filter, today=today)


@pipeline_bp.route("/bookmarks")
@login_required
def bookmarks():
    jobs = get_bookmarked_jobs(current_user.id)
    applied_keys = get_applied_job_keys(current_user.id)
    return render_template("bookmarks.html", jobs=jobs, applied_keys=applied_keys)


@pipeline_bp.route("/compare")
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


@pipeline_bp.route("/kanban")
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


@pipeline_bp.route("/calendar")
@login_required
def calendar():
    interviews = get_applied_jobs(current_user.id, stage="interview")
    all_applied = get_applied_jobs(current_user.id)
    return render_template("calendar.html", interviews=interviews, all_applied_jobs=all_applied)


@pipeline_bp.route("/calendar/schedule", methods=["POST"])
@login_required
def schedule_interview():
    job_key = request.form.get("job_key")
    date = request.form.get("interview_date", "")
    time = request.form.get("interview_time", "")
    notes = request.form.get("interview_notes", "")

    if not job_key or not date:
        flash("Job and date are required.", "error")
        return redirect(url_for("pipeline.calendar"))

    # Move to interview stage and save date/time in notes
    schedule_note = f"{date} {time}".strip()
    if notes:
        schedule_note += f" - {notes}"
    update_applied_stage(current_user.id, job_key, "interview")
    update_applied_notes(current_user.id, job_key, schedule_note)
    flash("Interview scheduled.", "success")
    return redirect(url_for("pipeline.calendar"))


@pipeline_bp.route("/calendar/ics/<job_key>")
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
        return redirect(url_for("pipeline.calendar"))

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
