import json
import os

from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user

from database import (
    get_resumes, get_resume, set_default_resume, delete_resume, update_resume,
    save_resume, save_resume_version, get_resume_versions, get_resume_version,
)

resumes_bp = Blueprint("resumes", __name__)


@resumes_bp.route("/resumes")
@login_required
def resumes():
    user_resumes = get_resumes(current_user.id)
    return render_template("resumes.html", resumes=user_resumes)


@resumes_bp.route("/resumes/<int:rid>/default", methods=["POST"])
@login_required
def set_resume_default(rid):
    set_default_resume(rid, current_user.id)
    flash("Default resume updated.", "success")
    return redirect(url_for("resumes.resumes"))


@resumes_bp.route("/resumes/<int:rid>")
@login_required
def view_resume(rid):
    resume = get_resume(rid, current_user.id)
    if not resume:
        flash("Resume not found.", "error")
        return redirect(url_for("resumes.resumes"))
    skills = []
    if resume.get("skills_json"):
        try:
            skills_data = json.loads(resume["skills_json"])
            skills = skills_data.get("skills", skills_data) if isinstance(skills_data, dict) else skills_data
        except (json.JSONDecodeError, TypeError):
            pass
    return render_template("resume_view.html", resume=resume, skills=skills)


@resumes_bp.route("/resumes/<int:rid>/delete", methods=["POST"])
@login_required
def delete_resume_route(rid):
    delete_resume(rid, current_user.id)
    flash("Resume deleted.", "success")
    return redirect(url_for("resumes.resumes"))


@resumes_bp.route("/resumes/<int:rid>/versions")
@login_required
def resume_versions(rid):
    resume = get_resume(rid, current_user.id)
    if not resume:
        flash("Resume not found.", "error")
        return redirect(url_for("resumes.resumes"))
    versions = get_resume_versions(rid, current_user.id)
    return render_template("resume_versions.html", resume=resume, versions=versions)


@resumes_bp.route("/resumes/<int:rid>/versions/<int:vid>")
@login_required
def view_resume_version(rid, vid):
    version = get_resume_version(vid, current_user.id)
    if not version or version["resume_id"] != rid:
        flash("Version not found.", "error")
        return redirect(url_for("resumes.resume_versions", rid=rid))
    resume = get_resume(rid, current_user.id)
    return render_template("resume_version_detail.html", resume=resume, version=version)


@resumes_bp.route("/resumes/<int:rid>/versions/<int:vid>/restore", methods=["POST"])
@login_required
def restore_resume_version(rid, vid):
    version = get_resume_version(vid, current_user.id)
    if not version or version["resume_id"] != rid:
        flash("Version not found.", "error")
        return redirect(url_for("resumes.resume_versions", rid=rid))
    current_resume = get_resume(rid, current_user.id)
    if current_resume:
        save_resume_version(rid, current_user.id, current_resume["raw_text"], current_resume.get("skills_json"), "Before restore")
    update_resume(rid, current_user.id, version["raw_text"], version.get("skills_json"))
    flash(f"Restored to version {version['version_number']}.", "success")
    return redirect(url_for("resumes.resumes"))


@resumes_bp.route("/resumes/import-linkedin", methods=["POST"])
@login_required
def import_linkedin():
    file = request.files.get("linkedin_file")
    if not file or not file.filename:
        flash("Please select a LinkedIn PDF file.", "error")
        return redirect(url_for("resumes.resumes"))
    ext = os.path.splitext(file.filename)[1].lower()
    if ext != ".pdf":
        flash("Only PDF files are supported for LinkedIn import.", "error")
        return redirect(url_for("resumes.resumes"))
    from services.linkedin_parser import parse_linkedin_pdf, linkedin_to_resume_text
    parsed = parse_linkedin_pdf(file)
    if not parsed:
        flash("Could not parse the LinkedIn PDF. Make sure it's a valid LinkedIn profile export.", "error")
        return redirect(url_for("resumes.resumes"))
    resume_text = linkedin_to_resume_text(parsed)
    name = f"LinkedIn - {parsed.get('name', 'Import')}"
    save_resume(current_user.id, resume_text, name=name, filename=file.filename)
    flash(f"LinkedIn profile imported as '{name}'.", "success")
    return redirect(url_for("resumes.resumes"))
