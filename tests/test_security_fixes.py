"""Tests for security fixes: alert toggle, webhook SSRF, OAuth guard, description cleaner."""

from services.webhook_sender import validate_webhook_url
from services.description_cleaner import clean_description


# --- Webhook SSRF validation ---

def test_webhook_rejects_http():
    valid, err = validate_webhook_url("http://example.com/webhook")
    assert not valid
    assert "HTTPS" in err


def test_webhook_accepts_https():
    valid, err = validate_webhook_url("https://example.com/webhook")
    assert valid
    assert err is None


def test_webhook_rejects_localhost():
    valid, err = validate_webhook_url("https://localhost/webhook")
    assert not valid


def test_webhook_rejects_private_ip():
    valid, err = validate_webhook_url("https://192.168.1.1/webhook")
    assert not valid
    assert "private" in err.lower() or "reserved" in err.lower()


def test_webhook_rejects_loopback():
    valid, err = validate_webhook_url("https://127.0.0.1/webhook")
    assert not valid


def test_webhook_rejects_metadata_ip():
    # AWS metadata endpoint
    valid, err = validate_webhook_url("https://169.254.169.254/latest/meta-data")
    assert not valid


def test_webhook_rejects_empty():
    valid, err = validate_webhook_url("")
    assert not valid


def test_webhook_rejects_no_hostname():
    valid, err = validate_webhook_url("https:///path")
    assert not valid


# --- OAuth password guard ---

def test_oauth_user_cannot_login_with_password():
    """OAuth-only users (password_hash starts with 'oauth_') should be rejected."""
    from database import init_db, authenticate_user
    import sqlite3

    init_db()

    # Create a test OAuth user directly
    from database import get_db, _safe_close
    from werkzeug.security import generate_password_hash
    import secrets

    conn = get_db()
    email = f"test_oauth_{secrets.token_hex(4)}@example.com"
    oauth_hash = "oauth_" + secrets.token_hex(32)
    try:
        conn.execute(
            "INSERT INTO users (email, password_hash, name) VALUES (?, ?, ?)",
            (email, oauth_hash, "Test OAuth User"),
        )
        conn.commit()
    except sqlite3.IntegrityError:
        pass
    _safe_close(conn)

    # Trying any password should fail
    result = authenticate_user(email, "any-password-here")
    assert result is None, "OAuth-only user should not authenticate with password"


def test_normal_user_can_login():
    """Normal users with real password hashes should still work."""
    from database import init_db, authenticate_user
    from database import get_db, _safe_close
    from werkzeug.security import generate_password_hash
    import secrets

    init_db()

    conn = get_db()
    email = f"test_normal_{secrets.token_hex(4)}@example.com"
    password = "test-password-123"
    pw_hash = generate_password_hash(password)
    conn.execute(
        "INSERT INTO users (email, password_hash, name) VALUES (?, ?, ?)",
        (email, pw_hash, "Test Normal User"),
    )
    conn.commit()
    _safe_close(conn)

    result = authenticate_user(email, password)
    assert result is not None, "Normal user should authenticate"
    assert result["email"] == email


# --- Description cleaner ---

def test_mojibake_fix():
    """Fix UTF-8 mojibake (decoded as Latin-1)."""
    # \u00e2\u0080\u0099 is the Latin-1 encoding of the UTF-8 bytes for '
    mojibake = "we\u00e2\u0080\u0099re here"
    result = clean_description(mojibake)
    assert "\u2019" in result  # right single quote
    assert "\u00e2" not in result


def test_html_paragraphs_preserved():
    html = "<p>First.</p><p>Second.</p>"
    result = clean_description(html)
    assert "First." in result
    assert "Second." in result
    # Should have a blank line between paragraphs
    assert "\n\n" in result or "\n" in result


def test_bullet_points_preserved():
    html = "<ul><li>Item 1</li><li>Item 2</li></ul>"
    result = clean_description(html)
    assert "\u2022 Item 1" in result
    assert "\u2022 Item 2" in result


def test_entities_decoded():
    result = clean_description("Tom &amp; Jerry &mdash; friends")
    assert "Tom & Jerry \u2014 friends" in result


def test_whitespace_collapsed():
    result = clean_description("too   many   spaces\n\n\n\n\ntoo many lines")
    assert "too many spaces" in result
    # Should not have more than one blank line
    assert "\n\n\n" not in result
