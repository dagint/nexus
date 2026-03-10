"""Prometheus-compatible metrics collector (no external dependency)."""
import threading
import time
import logging

logger = logging.getLogger(__name__)

_lock = threading.Lock()

# Counters
_request_count = {}       # {endpoint: count}
_error_count = {}         # {endpoint: count}
_ai_call_count = {}       # {endpoint: count}
_total_jobs_searched = 0

# Histogram buckets for latency (seconds)
_LATENCY_BUCKETS = [0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, float("inf")]
_request_latency = {}     # {endpoint: {bucket: count}}
_request_latency_sum = {} # {endpoint: total_seconds}
_request_latency_count = {} # {endpoint: count}


def inc_request(endpoint, method="GET"):
    """Increment request counter for an endpoint."""
    key = f"{method} {endpoint}"
    with _lock:
        _request_count[key] = _request_count.get(key, 0) + 1


def inc_error(endpoint, method="GET"):
    """Increment error counter for an endpoint."""
    key = f"{method} {endpoint}"
    with _lock:
        _error_count[key] = _error_count.get(key, 0) + 1


def inc_ai_calls(endpoint):
    """Increment AI API call counter."""
    with _lock:
        _ai_call_count[endpoint] = _ai_call_count.get(endpoint, 0) + 1


def inc_jobs_searched(count):
    """Add to total jobs searched count."""
    global _total_jobs_searched
    with _lock:
        _total_jobs_searched += count


def observe_latency(endpoint, method, duration_seconds):
    """Record a request latency observation."""
    key = f"{method} {endpoint}"
    with _lock:
        if key not in _request_latency:
            _request_latency[key] = {b: 0 for b in _LATENCY_BUCKETS}
            _request_latency_sum[key] = 0.0
            _request_latency_count[key] = 0

        for bucket in _LATENCY_BUCKETS:
            if duration_seconds <= bucket:
                _request_latency[key][bucket] += 1

        _request_latency_sum[key] += duration_seconds
        _request_latency_count[key] += 1


def get_active_users_count():
    """Get count of active users from DB (best-effort)."""
    try:
        from database import get_db, _safe_close
        conn = get_db()
        row = conn.execute("SELECT COUNT(*) as c FROM users").fetchone()
        _safe_close(conn)
        return row["c"] if row else 0
    except Exception:
        return 0


def render_metrics():
    """Render all metrics in Prometheus text exposition format."""
    lines = []

    with _lock:
        # Request count
        lines.append("# HELP nexus_http_requests_total Total HTTP requests by endpoint and method.")
        lines.append("# TYPE nexus_http_requests_total counter")
        for key, count in sorted(_request_count.items()):
            method, endpoint = key.split(" ", 1)
            lines.append(f'nexus_http_requests_total{{method="{method}",endpoint="{endpoint}"}} {count}')

        # Error count
        lines.append("# HELP nexus_http_errors_total Total HTTP errors by endpoint.")
        lines.append("# TYPE nexus_http_errors_total counter")
        for key, count in sorted(_error_count.items()):
            method, endpoint = key.split(" ", 1)
            lines.append(f'nexus_http_errors_total{{method="{method}",endpoint="{endpoint}"}} {count}')

        # Request latency histogram
        lines.append("# HELP nexus_http_request_duration_seconds HTTP request latency histogram.")
        lines.append("# TYPE nexus_http_request_duration_seconds histogram")
        for key in sorted(_request_latency.keys()):
            method, endpoint = key.split(" ", 1)
            labels = f'method="{method}",endpoint="{endpoint}"'
            cumulative = 0
            for bucket in _LATENCY_BUCKETS:
                cumulative += _request_latency[key][bucket]
                le = "+Inf" if bucket == float("inf") else str(bucket)
                lines.append(f'nexus_http_request_duration_seconds_bucket{{{labels},le="{le}"}} {cumulative}')
            lines.append(f'nexus_http_request_duration_seconds_sum{{{labels}}} {_request_latency_sum[key]:.6f}')
            lines.append(f'nexus_http_request_duration_seconds_count{{{labels}}} {_request_latency_count[key]}')

        # AI call count
        lines.append("# HELP nexus_ai_calls_total Total AI API calls by endpoint.")
        lines.append("# TYPE nexus_ai_calls_total counter")
        for endpoint, count in sorted(_ai_call_count.items()):
            lines.append(f'nexus_ai_calls_total{{endpoint="{endpoint}"}} {count}')

        # Total jobs searched
        lines.append("# HELP nexus_jobs_searched_total Total number of jobs returned from searches.")
        lines.append("# TYPE nexus_jobs_searched_total counter")
        lines.append(f"nexus_jobs_searched_total {_total_jobs_searched}")

    # Active users (outside lock since it does DB query)
    active_users = get_active_users_count()
    lines.append("# HELP nexus_active_users Current number of registered users.")
    lines.append("# TYPE nexus_active_users gauge")
    lines.append(f"nexus_active_users {active_users}")

    return "\n".join(lines) + "\n"
