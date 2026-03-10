"""Webhook notification sender for Nexus."""
import hashlib
import hmac
import json
import logging
import threading

import requests

from database import get_active_webhooks, update_webhook_triggered

logger = logging.getLogger(__name__)


def send_webhook(url, event_type, payload, secret=None):
    """Send a webhook POST request with optional HMAC-SHA256 signature.

    Returns True on success, False on failure.
    """
    body = json.dumps({
        "event": event_type,
        "data": payload,
    })

    headers = {
        "Content-Type": "application/json",
        "X-Nexus-Event": event_type,
    }

    if secret:
        signature = hmac.new(
            secret.encode("utf-8"),
            body.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        headers["X-Nexus-Signature"] = f"sha256={signature}"

    try:
        resp = requests.post(url, data=body, headers=headers, timeout=10)
        resp.raise_for_status()
        logger.info("Webhook sent to %s (status %d)", url, resp.status_code)
        return True
    except requests.RequestException as e:
        logger.warning("Webhook to %s failed: %s", url, e)
        return False


def trigger_webhooks(user_id, event_type, payload):
    """Find active webhooks for a user and send them in background threads.

    This is fire-and-forget: failures are logged but not raised.
    """
    try:
        webhooks = get_active_webhooks(user_id, event_type)
    except Exception as e:
        logger.warning("Failed to load webhooks for user %d: %s", user_id, e)
        return

    for wh in webhooks:
        def _send(webhook=wh):
            success = send_webhook(
                webhook["url"],
                event_type,
                payload,
                secret=webhook.get("secret"),
            )
            if success:
                try:
                    update_webhook_triggered(webhook["id"])
                except Exception:
                    pass

        t = threading.Thread(target=_send, daemon=True)
        t.start()


def send_test_webhook(url, secret=None):
    """Send a test webhook payload. Returns (success, status_code_or_error)."""
    payload = {
        "message": "This is a test webhook from Nexus.",
        "test": True,
    }
    body = json.dumps({
        "event": "test",
        "data": payload,
    })

    headers = {
        "Content-Type": "application/json",
        "X-Nexus-Event": "test",
    }

    if secret:
        signature = hmac.new(
            secret.encode("utf-8"),
            body.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        headers["X-Nexus-Signature"] = f"sha256={signature}"

    try:
        resp = requests.post(url, data=body, headers=headers, timeout=10)
        resp.raise_for_status()
        return True, resp.status_code
    except requests.RequestException as e:
        return False, str(e)
