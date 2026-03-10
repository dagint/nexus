import json

from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, session
from flask_login import login_required, current_user

from config import Config
from database import (
    get_user_settings, update_user_settings,
    get_unread_notifications, get_unread_count, mark_notifications_read,
    create_webhook, get_webhooks, delete_webhook,
    create_api_token, get_api_tokens, delete_api_token,
    get_user_oauth_accounts,
)

settings_bp = Blueprint("settings", __name__)


def _safe_int(value, default=0):
    """Safely convert a value to int, returning default on failure."""
    try:
        return int(value)
    except (ValueError, TypeError):
        return default


@settings_bp.route("/settings", methods=["GET"])
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


@settings_bp.route("/settings", methods=["POST"])
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
    return redirect(url_for("settings.settings"))


@settings_bp.route("/notifications")
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


@settings_bp.route("/notifications/read", methods=["POST"])
@login_required
def read_notifications():
    data = request.get_json() or {}
    ids = data.get("ids")
    mark_notifications_read(current_user.id, ids)
    return jsonify({"status": "ok"})


@settings_bp.route("/settings/webhooks", methods=["GET", "POST"])
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
            return redirect(url_for("settings.webhooks_settings"))

        if not url.startswith("http://") and not url.startswith("https://"):
            flash("Webhook URL must start with http:// or https://", "error")
            return redirect(url_for("settings.webhooks_settings"))

        create_webhook(current_user.id, url, event_types=event_types_raw, secret=secret)
        flash("Webhook created.", "success")
        return redirect(url_for("settings.webhooks_settings"))

    hooks = get_webhooks(current_user.id)
    return render_template("webhooks.html", webhooks=hooks)


@settings_bp.route("/settings/webhooks/<int:wid>/delete", methods=["POST"])
@login_required
def webhook_delete(wid):
    delete_webhook(wid, current_user.id)
    flash("Webhook deleted.", "success")
    return redirect(url_for("settings.webhooks_settings"))


@settings_bp.route("/settings/webhooks/<int:wid>/test", methods=["POST"])
@login_required
def webhook_test(wid):
    hooks = get_webhooks(current_user.id)
    wh = next((h for h in hooks if h["id"] == wid), None)
    if not wh:
        flash("Webhook not found.", "error")
        return redirect(url_for("settings.webhooks_settings"))

    from services.webhook_sender import send_test_webhook
    success, detail = send_test_webhook(wh["url"], secret=wh.get("secret"))
    if success:
        flash(f"Test webhook sent successfully (status {detail}).", "success")
    else:
        flash(f"Test webhook failed: {detail}", "error")
    return redirect(url_for("settings.webhooks_settings"))


@settings_bp.route("/settings/api-tokens", methods=["POST"])
@login_required
def create_api_token_route():
    token, tid = create_api_token(current_user.id)
    session["new_api_token"] = token
    flash("API token created. Copy it now; it won't be shown again.", "success")
    return redirect(url_for("settings.settings"))


@settings_bp.route("/settings/api-tokens/<int:tid>/delete", methods=["POST"])
@login_required
def delete_api_token_route(tid):
    delete_api_token(tid, current_user.id)
    flash("API token revoked.", "success")
    return redirect(url_for("settings.settings"))
