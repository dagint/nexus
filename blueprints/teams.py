from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required, current_user

from database import (
    create_team, get_user_teams, get_team, get_team_members,
    is_team_member, get_team_member_role, add_team_member, remove_team_member,
    delete_team, share_job_with_team, get_team_shared_jobs, get_team_shared_job,
    add_team_job_comment, get_team_job_comments, get_team_activity,
    get_user_by_email, create_notification,
)

teams_bp = Blueprint("teams", __name__)


@teams_bp.route("/teams")
@login_required
def teams_list():
    teams = get_user_teams(current_user.id)
    return render_template("teams.html", teams=teams)


@teams_bp.route("/teams", methods=["POST"])
@login_required
def teams_create():
    name = request.form.get("name", "").strip()
    if not name:
        flash("Team name is required.", "error")
        return redirect(url_for("teams.teams_list"))
    create_team(name, current_user.id)
    flash(f'Team "{name}" created.', "success")
    return redirect(url_for("teams.teams_list"))


@teams_bp.route("/teams/<int:tid>")
@login_required
def team_detail(tid):
    if not is_team_member(tid, current_user.id):
        flash("You are not a member of this team.", "error")
        return redirect(url_for("teams.teams_list"))

    team = get_team(tid)
    if not team:
        flash("Team not found.", "error")
        return redirect(url_for("teams.teams_list"))

    members = get_team_members(tid)
    shared_jobs = get_team_shared_jobs(tid)
    activity = get_team_activity(tid, limit=20)
    user_role = get_team_member_role(tid, current_user.id)

    return render_template("team_detail.html", team=team, members=members,
                           shared_jobs=shared_jobs, activity=activity,
                           user_role=user_role)


@teams_bp.route("/teams/<int:tid>/invite", methods=["POST"])
@login_required
def team_invite(tid):
    role = get_team_member_role(tid, current_user.id)
    if role != "admin":
        flash("Only team admins can invite members.", "error")
        return redirect(url_for("teams.team_detail", tid=tid))

    email = request.form.get("email", "").strip()
    if not email:
        flash("Email is required.", "error")
        return redirect(url_for("teams.team_detail", tid=tid))

    user = get_user_by_email(email)
    if not user:
        flash("No user found with that email.", "error")
        return redirect(url_for("teams.team_detail", tid=tid))

    if is_team_member(tid, user["id"]):
        flash("User is already a member of this team.", "warning")
        return redirect(url_for("teams.team_detail", tid=tid))

    add_team_member(tid, user["id"], role="member")
    team = get_team(tid)
    create_notification(user["id"],
                        message=f'You were added to team "{team["name"]}"',
                        link="/teams")
    flash(f'Invited {email} to the team.', "success")
    return redirect(url_for("teams.team_detail", tid=tid))


@teams_bp.route("/teams/<int:tid>/leave", methods=["POST"])
@login_required
def team_leave(tid):
    if not is_team_member(tid, current_user.id):
        flash("You are not a member of this team.", "error")
        return redirect(url_for("teams.teams_list"))

    team = get_team(tid)
    # If the user is the creator and only admin, delete the team
    role = get_team_member_role(tid, current_user.id)
    if role == "admin" and team["created_by"] == current_user.id:
        members = get_team_members(tid)
        admin_count = sum(1 for m in members if m["role"] == "admin")
        if admin_count <= 1:
            delete_team(tid)
            flash("Team deleted (you were the only admin).", "success")
            return redirect(url_for("teams.teams_list"))

    remove_team_member(tid, current_user.id)
    flash("You left the team.", "success")
    return redirect(url_for("teams.teams_list"))


@teams_bp.route("/teams/<int:tid>/share-job", methods=["POST"])
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


@teams_bp.route("/teams/<int:tid>/jobs/<int:jid>/comment", methods=["POST"])
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


@teams_bp.route("/teams/<int:tid>/jobs/<int:jid>/comments", methods=["GET"])
@login_required
def team_job_comments_list(tid, jid):
    if not is_team_member(tid, current_user.id):
        return jsonify({"error": "Not a team member."}), 403
    comments = get_team_job_comments(jid)
    return jsonify({"comments": comments})
