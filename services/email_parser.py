"""Parse recruiter emails and extract structured job + contact data."""
import json
import logging
import re

logger = logging.getLogger(__name__)


def _extract_emails(text):
    """Extract email addresses from text."""
    pattern = r'[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}'
    return list(set(re.findall(pattern, text)))


def _extract_phones(text):
    """Extract phone numbers from text."""
    patterns = [
        r'\+?1?[\s.-]?\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}',
        r'\+\d{1,3}[\s.-]?\d{2,4}[\s.-]?\d{3,4}[\s.-]?\d{3,4}',
    ]
    phones = []
    for pat in patterns:
        phones.extend(re.findall(pat, text))
    return list(set(p.strip() for p in phones if len(p.strip()) >= 10))


def _extract_name_from_signature(text):
    """Try to extract a name from an email signature or From line."""
    # Check "From:" header
    from_match = re.search(r'From:\s*([^<\n]+?)(?:\s*<|\n)', text)
    if from_match:
        name = from_match.group(1).strip().strip('"')
        if name and not '@' in name:
            return name

    # Try common signature patterns (last lines that look like names)
    lines = text.strip().split('\n')
    # Look at the last 10 lines for signature
    sig_lines = lines[-10:]
    for line in sig_lines:
        line = line.strip()
        # Skip empty lines, URLs, phone numbers, emails
        if not line or '@' in line or 'http' in line.lower():
            continue
        if re.match(r'^[\d\(\)+\-\s.]+$', line):  # phone number
            continue
        # A name is typically 2-4 words, all capitalized
        words = line.split()
        if 2 <= len(words) <= 4 and all(w[0].isupper() for w in words if w):
            # Check it's not a common non-name phrase
            lower = line.lower()
            if any(kw in lower for kw in ['regards', 'best', 'thank', 'sincerely', 'cheers']):
                continue
            return line

    return ""


def _extract_job_title_regex(text):
    """Try to extract job title from common email patterns."""
    patterns = [
        r'(?:regarding|about|for)\s+(?:the\s+)?(.+?)\s+(?:position|role|opening|opportunity)',
        r'(?:position|role|opening|opportunity):\s*(.+?)(?:\n|$)',
        r'(?:job\s+title|title):\s*(.+?)(?:\n|$)',
        r'(?:we\s+have\s+an?\s+)(.+?)\s+(?:position|role|opening)',
        r'(?:hiring\s+(?:a|an)\s+)(.+?)(?:\s+(?:to|for|at|in)|\.|,|\n)',
        r'(?:looking\s+for\s+(?:a|an)\s+)(.+?)(?:\s+(?:to|for|at|in)|\.|,|\n)',
    ]
    for pat in patterns:
        match = re.search(pat, text, re.IGNORECASE)
        if match:
            title = match.group(1).strip()
            if 3 < len(title) < 80:
                return title
    return ""


def _extract_company_regex(text):
    """Try to extract company name from common email patterns."""
    patterns = [
        r'(?:at|with|from|join)\s+([A-Z][A-Za-z0-9\s&.]+?)(?:\.|,|\n|\s+(?:is|are|we|and|for))',
        r'(?:company|organization|firm):\s*(.+?)(?:\n|$)',
        r'([A-Z][A-Za-z0-9]+(?:\s+[A-Z][A-Za-z0-9]+)*)\s+is\s+(?:looking|hiring|seeking)',
    ]
    for pat in patterns:
        match = re.search(pat, text)
        if match:
            company = match.group(1).strip()
            if 2 < len(company) < 60:
                return company
    return ""


def _extract_location_regex(text):
    """Try to extract location from email text."""
    patterns = [
        r'(?:location|based\s+in|located\s+in|office\s+in):\s*(.+?)(?:\n|$)',
        r'(?:location|based\s+in|located\s+in|office\s+in)\s+(.+?)(?:\.|,|\n)',
    ]
    for pat in patterns:
        match = re.search(pat, text, re.IGNORECASE)
        if match:
            loc = match.group(1).strip()
            if 2 < len(loc) < 80:
                return loc

    # Check for "Remote" mention
    if re.search(r'\b(?:remote|work\s+from\s+home|wfh)\b', text, re.IGNORECASE):
        return "Remote"
    return ""


def _extract_deadline_regex(text):
    """Try to extract deadline or date from email."""
    patterns = [
        r'(?:deadline|due\s+by|by|before|respond\s+by):\s*(.+?)(?:\n|$)',
        r'(?:deadline|due\s+by|respond\s+by)\s+(.+?)(?:\.|,|\n)',
    ]
    for pat in patterns:
        match = re.search(pat, text, re.IGNORECASE)
        if match:
            date_str = match.group(1).strip()
            if 4 < len(date_str) < 40:
                return date_str
    return ""


def _regex_fallback(email_text):
    """Extract data using regex patterns only."""
    emails = _extract_emails(email_text)
    phones = _extract_phones(email_text)
    name = _extract_name_from_signature(email_text)

    return {
        "job_title": _extract_job_title_regex(email_text),
        "company": _extract_company_regex(email_text),
        "location": _extract_location_regex(email_text),
        "recruiter_name": name,
        "recruiter_email": emails[0] if emails else "",
        "recruiter_phone": phones[0] if phones else "",
        "next_steps": "",
        "deadline": _extract_deadline_regex(email_text),
    }


def parse_recruiter_email(email_text):
    """Parse a recruiter email and extract structured data.

    Uses AI (via ai_client) if available, with regex fallback.
    Returns dict with: job_title, company, location, recruiter_name,
    recruiter_email, recruiter_phone, next_steps, deadline.
    """
    if not email_text or not email_text.strip():
        return {
            "job_title": "", "company": "", "location": "",
            "recruiter_name": "", "recruiter_email": "", "recruiter_phone": "",
            "next_steps": "", "deadline": "",
        }

    # Try AI extraction first
    try:
        from services.ai_client import is_available, call
        if is_available():
            prompt = f"""Extract the following information from this recruiter email. Return ONLY valid JSON with these keys:
- job_title: the job title/position being discussed
- company: the company name
- location: job location (or "Remote" if remote)
- recruiter_name: name of the recruiter/sender
- recruiter_email: recruiter's email address
- recruiter_phone: recruiter's phone number
- next_steps: any mentioned next steps or action items
- deadline: any mentioned deadlines or dates

If a field cannot be determined, use an empty string.

Email:
{email_text[:3000]}"""

            response = call(prompt, max_tokens=500, endpoint="email_parser")
            if response:
                # Try to parse JSON from the response
                # Handle cases where AI wraps in code blocks
                cleaned = response.strip()
                if cleaned.startswith("```"):
                    cleaned = re.sub(r'^```(?:json)?\s*', '', cleaned)
                    cleaned = re.sub(r'\s*```$', '', cleaned)

                parsed = json.loads(cleaned)
                # Validate expected keys
                expected_keys = ["job_title", "company", "location", "recruiter_name",
                                 "recruiter_email", "recruiter_phone", "next_steps", "deadline"]
                result = {k: str(parsed.get(k, "")).strip() for k in expected_keys}
                return result
    except Exception as e:
        logger.warning("AI email parsing failed, falling back to regex: %s", e)

    # Regex fallback
    return _regex_fallback(email_text)
