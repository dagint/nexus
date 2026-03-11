import logging

from flask import Blueprint, request, redirect, url_for, flash, render_template, jsonify, session
from flask_login import login_required, current_user, login_user, logout_user

from config import Config
from database import (
    create_user, authenticate_user, get_user_by_id, get_user_by_email,
    create_password_reset_token, validate_reset_token, consume_reset_token,
    update_user_password,
    create_oauth_account, get_oauth_account, link_oauth_account, create_user_oauth,
)

logger = logging.getLogger(__name__)

auth_bp = Blueprint("auth", __name__)


def _get_user_class():
    """Import User class from app module (deferred to avoid circular imports)."""
    from app import User
    return User


def init_auth_limiter(limiter):
    """Apply rate limits to auth routes. Called during blueprint registration."""
    limiter.limit("5 per minute")(register)
    limiter.limit("10 per minute")(login)
    limiter.limit("5 per minute")(forgot_password)
    limiter.limit("10 per minute")(reset_password)


# --- Auth Routes ---

@auth_bp.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("index"))

    if request.method == "POST":
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "")
        name = request.form.get("name", "").strip()

        if not email or not password:
            flash("Email and password are required.", "error")
            return redirect(url_for("auth.register"))

        if len(password) < 8:
            flash("Password must be at least 8 characters.", "error")
            return redirect(url_for("auth.register"))

        user_id = create_user(email, password, name)
        if user_id is None:
            flash("An account with that email already exists.", "error")
            return redirect(url_for("auth.register"))

        User = _get_user_class()
        user_data = get_user_by_id(user_id)
        login_user(User(user_data))
        flash("Account created! Welcome.", "success")
        return redirect(url_for("index"))

    return render_template("register.html")


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("index"))

    if request.method == "POST":
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "")

        user_data = authenticate_user(email, password)
        if user_data:
            User = _get_user_class()
            login_user(User(user_data), remember=bool(request.form.get("remember")))
            next_page = request.args.get("next")
            if next_page and not next_page.startswith("/"):
                next_page = None
            if next_page and next_page.startswith("//"):
                next_page = None
            return redirect(next_page or url_for("index"))

        flash("Invalid email or password.", "error")
        return redirect(url_for("auth.login"))

    return render_template("login.html")


@auth_bp.route("/logout")
def logout():
    logout_user()
    flash("Logged out.", "success")
    return redirect(url_for("index"))


# --- Password Management ---

@auth_bp.route("/change-password", methods=["GET", "POST"])
@login_required
def change_password():
    if request.method == "POST":
        current_password = request.form.get("current_password", "")
        new_password = request.form.get("new_password", "")
        confirm_password = request.form.get("confirm_password", "")

        if not current_password or not new_password:
            flash("All fields are required.", "error")
            return redirect(url_for("auth.change_password"))

        if new_password != confirm_password:
            flash("New passwords do not match.", "error")
            return redirect(url_for("auth.change_password"))

        if len(new_password) < 8:
            flash("New password must be at least 8 characters.", "error")
            return redirect(url_for("auth.change_password"))

        user_data = authenticate_user(current_user.email, current_password)
        if not user_data:
            flash("Current password is incorrect.", "error")
            return redirect(url_for("auth.change_password"))

        update_user_password(current_user.id, new_password)
        flash("Password changed successfully.", "success")
        return redirect(url_for("settings.settings"))

    return render_template("change_password.html")


@auth_bp.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    if current_user.is_authenticated:
        return redirect(url_for("auth.change_password"))

    if request.method == "POST":
        email = request.form.get("email", "").strip()
        if not email:
            flash("Please enter your email address.", "error")
            return redirect(url_for("auth.forgot_password"))

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

        return redirect(url_for("auth.forgot_password"))

    return render_template("forgot_password.html")


@auth_bp.route("/reset-password/<token>", methods=["GET", "POST"])
def reset_password(token):
    user_id = validate_reset_token(token)
    if not user_id:
        flash("This password reset link is invalid or has expired.", "error")
        return redirect(url_for("auth.forgot_password"))

    if request.method == "POST":
        new_password = request.form.get("new_password", "")
        confirm_password = request.form.get("confirm_password", "")

        if not new_password:
            flash("Password is required.", "error")
            return redirect(url_for("auth.reset_password", token=token))

        if new_password != confirm_password:
            flash("Passwords do not match.", "error")
            return redirect(url_for("auth.reset_password", token=token))

        if len(new_password) < 8:
            flash("Password must be at least 8 characters.", "error")
            return redirect(url_for("auth.reset_password", token=token))

        # Atomically consume token to prevent race condition
        consumed_user_id = consume_reset_token(token)
        if not consumed_user_id:
            flash("This password reset link is invalid or has expired.", "error")
            return redirect(url_for("auth.forgot_password"))

        update_user_password(consumed_user_id, new_password)
        flash("Your password has been reset. You can now log in.", "success")
        return redirect(url_for("auth.login"))

    return render_template("reset_password.html", token=token)


# --- OAuth Routes ---

@auth_bp.route("/auth/google")
def google_login():
    """Redirect to Google OAuth consent screen."""
    if not Config.GOOGLE_CLIENT_ID:
        flash("Google login is not configured.", "error")
        return redirect(url_for("auth.login"))

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


@auth_bp.route("/auth/google/callback")
def google_callback():
    """Handle Google OAuth callback."""
    if not Config.GOOGLE_CLIENT_ID:
        flash("Google login is not configured.", "error")
        return redirect(url_for("auth.login"))

    error = request.args.get("error")
    if error:
        flash(f"Google login failed: {error}", "error")
        return redirect(url_for("auth.login"))

    code = request.args.get("code")
    state = request.args.get("state")

    # Verify state
    if state != session.pop("oauth_state", None):
        flash("Invalid OAuth state. Please try again.", "error")
        return redirect(url_for("auth.login"))

    if not code:
        flash("No authorization code received.", "error")
        return redirect(url_for("auth.login"))

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
            return redirect(url_for("auth.login"))

        User = _get_user_class()

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
            return redirect(url_for("auth.login"))

    except Exception as e:
        logger.error("Google OAuth failed: %s", e)
        flash("Google login failed. Please try again.", "error")
        return redirect(url_for("auth.login"))
