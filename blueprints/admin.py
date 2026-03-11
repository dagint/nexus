from functools import wraps

from flask import Blueprint, render_template, redirect, url_for, flash
from flask_login import current_user

from database import get_admin_stats, get_admin_users, is_user_admin

admin_bp = Blueprint("admin", __name__)


def admin_required(f):
    """Decorator to require admin access."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for("auth.login"))
        if not is_user_admin(current_user.id):
            flash("Admin access required.", "error")
            return redirect(url_for("index"))
        return f(*args, **kwargs)
    return decorated


@admin_bp.route("/admin")
@admin_required
def admin_dashboard():
    stats = get_admin_stats()
    return render_template("admin.html", stats=stats)


@admin_bp.route("/admin/users")
@admin_required
def admin_users():
    users = get_admin_users()
    return render_template("admin_users.html", users=users)
