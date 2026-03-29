"""Webhook notification sender for Nexus."""
import atexit
import hashlib
import hmac
import ipaddress
import json
import logging
import socket
import threading
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse

import requests

from database import get_active_webhooks, update_webhook_triggered

logger = logging.getLogger(__name__)

# Private/reserved networks that webhooks must not target
_BLOCKED_NETWORKS = [
    ipaddress.ip_network("127.0.0.0/8"),       # Loopback
    ipaddress.ip_network("10.0.0.0/8"),         # Private Class A
    ipaddress.ip_network("172.16.0.0/12"),      # Private Class B
    ipaddress.ip_network("192.168.0.0/16"),     # Private Class C
    ipaddress.ip_network("169.254.0.0/16"),     # Link-local / cloud metadata
    ipaddress.ip_network("::1/128"),            # IPv6 loopback
    ipaddress.ip_network("fc00::/7"),           # IPv6 private
    ipaddress.ip_network("fe80::/10"),          # IPv6 link-local
]


def validate_webhook_url(url):
    """Validate a webhook URL for SSRF safety.

    Returns (is_valid, error_message). Checks:
    - HTTPS only
    - No private/link-local/metadata IPs
    - Hostname resolves to a public IP
    """
    if not url:
        return False, "URL is required."

    parsed = urlparse(url)

    # HTTPS only
    if parsed.scheme != "https":
        return False, "Webhook URL must use HTTPS."

    hostname = parsed.hostname
    if not hostname:
        return False, "Invalid URL: no hostname."

    # Block obvious localhost aliases
    if hostname in ("localhost", "0.0.0.0", "[::]"):
        return False, "Webhook URL must not target localhost."

    # Resolve hostname and check all IPs
    try:
        addr_infos = socket.getaddrinfo(hostname, parsed.port or 443,
                                        proto=socket.IPPROTO_TCP)
    except socket.gaierror:
        return False, f"Cannot resolve hostname: {hostname}"

    for family, _, _, _, sockaddr in addr_infos:
        ip = ipaddress.ip_address(sockaddr[0])
        for net in _BLOCKED_NETWORKS:
            if ip in net:
                return False, f"Webhook URL must not target private/reserved addresses."

    return True, None

# Thread pool for webhook delivery; limits concurrency and supports clean shutdown.
_webhook_pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="webhook")
atexit.register(_webhook_pool.shutdown, wait=False)


def send_webhook(url, event_type, payload, secret=None):
    """Send a webhook POST request with optional HMAC-SHA256 signature.

    Returns True on success, False on failure.
    """
    valid, err = validate_webhook_url(url)
    if not valid:
        logger.warning("Webhook blocked (%s): %s", url, err)
        return False

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

        _webhook_pool.submit(_send)


def send_test_webhook(url, secret=None):
    """Send a test webhook payload. Returns (success, status_code_or_error)."""
    valid, err = validate_webhook_url(url)
    if not valid:
        return False, err

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
