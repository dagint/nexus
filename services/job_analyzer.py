import logging
import re

logger = logging.getLogger(__name__)

# Remote detection patterns
REMOTE_PATTERNS = {
    "remote": [
        r"\bfully\s+remote\b", r"\b100%\s+remote\b", r"\bremote[\s-]+first\b",
        r"\bwork\s+from\s+(?:home|anywhere)\b", r"\bwfh\b",
    ],
    "hybrid": [
        r"\bhybrid\b", r"\b\d[\s-]+days?\s+(?:in\s+(?:the\s+)?office|on[\s-]*site)\b",
        r"\bremote\s+with\s+(?:occasional|quarterly|monthly)\s+(?:onsite|on-site|office)\b",
        r"\bflexible\s+(?:work|schedule)\b.*\b(?:office|onsite)\b",
    ],
}

REMOTE_GRANULAR = {
    "fully_remote": [r"\bfully\s+remote\b", r"\b100%\s+remote\b", r"\bremote[\s-]+first\b"],
    "remote_quarterly_onsite": [r"\bremote\s+with\s+quarterly\s+(?:onsite|on-site|visit)\b"],
    "hybrid_2_3_days": [r"\bhybrid\s*\(?2[\s-]+3\s+days?\b", r"\b2[\s-]+3\s+days?\s+(?:in\s+)?office\b"],
    "remote_friendly": [r"\bremote[\s-]+friendly\b", r"\bremote\s+(?:option|possible|available)\b"],
}

# Travel detection patterns
TRAVEL_PATTERNS = [
    r"(\d+)\s*%\s*travel",
    r"travel\s+(\d+)\s*%",
    r"travel\s+(?:is\s+)?required",
    r"travel\s+(?:is\s+)?expected",
    r"willing\s+to\s+travel",
    r"(?:domestic|international)\s+travel",
    r"overnight\s+travel",
]

# Timezone patterns
TIMEZONE_PATTERNS = [
    r"\b(EST|CST|MST|PST|ET|CT|MT|PT|Eastern|Central|Mountain|Pacific)\s+(?:time\s*zone|hours|business\s+hours)\b",
    r"\bUS\s+time\s*zones?\b",
    r"\b(GMT[+-]\d+|UTC[+-]\d+)\b",
    r"\b(EMEA|APAC|Americas?)\s+(?:time\s*zone|hours)\b",
]

# Easy apply patterns
EASY_APPLY_PATTERNS = [
    r"\beasy\s+apply\b",
    r"\bquick\s+apply\b",
    r"\bone[\s-]+click\s+apply\b",
    r"\bapply\s+(?:with|via)\s+linkedin\b",
]


def analyze_job(job):
    """Analyze a job listing for remote status, travel requirements, and more."""
    desc = job.get("description", "")
    title = job.get("title", "")
    text = f"{title} {desc}"

    # Remote status
    remote_status = _detect_remote_status(text, job.get("remote_status", "unknown"))
    remote_detail = _detect_remote_granular(text)

    # Travel
    travel_info = _detect_travel(text)

    # Timezone requirements
    timezone_req = _detect_timezone(text)

    # Easy apply
    easy_apply = _detect_easy_apply(text)

    job["remote_status"] = remote_status
    job["remote_detail"] = remote_detail
    job["travel_info"] = travel_info
    job["timezone_req"] = timezone_req
    job["easy_apply"] = easy_apply

    return job


def analyze_jobs(jobs):
    """Analyze a list of job listings."""
    return [analyze_job(job) for job in jobs]


def _detect_remote_status(text, api_status):
    """Detect remote status from text and API data."""
    text_lower = text.lower()

    # Trust API if it says remote
    if api_status == "remote":
        # But check if it's actually hybrid
        for pattern in REMOTE_PATTERNS["hybrid"]:
            if re.search(pattern, text_lower):
                return "hybrid"
        return "remote"

    # Check text patterns
    for pattern in REMOTE_PATTERNS["remote"]:
        if re.search(pattern, text_lower):
            return "remote"

    for pattern in REMOTE_PATTERNS["hybrid"]:
        if re.search(pattern, text_lower):
            return "hybrid"

    return api_status if api_status != "unknown" else "onsite"


def _detect_remote_granular(text):
    """Detect granular remote classification."""
    text_lower = text.lower()
    for label, patterns in REMOTE_GRANULAR.items():
        for pattern in patterns:
            if re.search(pattern, text_lower):
                return label
    return None


def _detect_travel(text):
    """Detect travel requirements from job description."""
    text_lower = text.lower()

    # Look for percentage
    for pattern in [r"(\d+)\s*%\s*travel", r"travel\s+(\d+)\s*%"]:
        match = re.search(pattern, text_lower)
        if match:
            return f"{match.group(1)}% travel"

    # Look for general travel mentions
    for pattern in TRAVEL_PATTERNS[2:]:
        if re.search(pattern, text_lower):
            return "Travel required"

    return None


def _detect_timezone(text):
    """Extract timezone requirements."""
    text_lower = text.lower()
    for pattern in TIMEZONE_PATTERNS:
        match = re.search(pattern, text_lower, re.IGNORECASE)
        if match:
            return match.group(0).strip()
    return None


def _detect_easy_apply(text):
    """Detect if job has easy/quick apply."""
    text_lower = text.lower()
    for pattern in EASY_APPLY_PATTERNS:
        if re.search(pattern, text_lower):
            return True
    return False
