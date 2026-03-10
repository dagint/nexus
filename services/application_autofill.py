"""Extract structured application data from resume for auto-fill."""
import json
import logging
import re

logger = logging.getLogger(__name__)


def generate_autofill(resume_text, user_settings=None):
    """Extract structured data from resume text for application auto-fill.

    Returns a dict with fields like:
    - name, email, phone, location, linkedin, github
    - years_of_experience, education, current_title, summary
    """
    # Start with regex extraction
    data = _extract_with_regex(resume_text)

    # Overlay user settings if available
    if user_settings:
        if not data.get("name") and user_settings.get("name"):
            data["name"] = user_settings["name"]

    # Try AI for more complete extraction
    from services.ai_client import is_available, call
    if is_available():
        try:
            ai_data = _extract_with_ai(resume_text)
            if ai_data:
                # Merge: AI fills in blanks, regex values take priority
                for key, val in ai_data.items():
                    if not data.get(key) and val:
                        data[key] = val
        except Exception as e:
            logger.warning("AI autofill extraction failed: %s", e)

    return data


def _extract_with_regex(text):
    """Extract structured fields from resume using regex patterns."""
    data = {
        "name": "",
        "email": "",
        "phone": "",
        "location": "",
        "linkedin": "",
        "github": "",
        "years_of_experience": "",
        "education": "",
        "current_title": "",
        "summary": "",
    }

    # Email
    email_match = re.search(r"[\w.+-]+@[\w-]+\.[\w.]+", text)
    if email_match:
        data["email"] = email_match.group()

    # Phone
    phone_match = re.search(
        r"(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}", text
    )
    if phone_match:
        data["phone"] = phone_match.group().strip()

    # LinkedIn
    linkedin_match = re.search(r"(?:linkedin\.com/in/|linkedin:\s*)([\w-]+)", text, re.IGNORECASE)
    if linkedin_match:
        data["linkedin"] = f"https://linkedin.com/in/{linkedin_match.group(1)}"

    # GitHub
    github_match = re.search(r"(?:github\.com/|github:\s*)([\w-]+)", text, re.IGNORECASE)
    if github_match:
        data["github"] = f"https://github.com/{github_match.group(1)}"

    # Name - typically first line of resume
    lines = text.strip().split("\n")
    for line in lines[:5]:
        line = line.strip()
        # Skip empty lines and lines that look like headers/labels
        if not line or "@" in line or line.startswith("http"):
            continue
        # Name is usually short and doesn't contain common header words
        if len(line) < 60 and not any(kw in line.lower() for kw in [
            "resume", "curriculum", "objective", "summary", "experience",
            "education", "skills", "phone", "email", "address"
        ]):
            data["name"] = line
            break

    # Years of experience
    years_match = re.search(r"(\d+)\+?\s*years?\s*(?:of\s+)?(?:experience|professional)", text, re.IGNORECASE)
    if years_match:
        data["years_of_experience"] = years_match.group(1)

    # Education - look for degree patterns
    edu_patterns = [
        r"((?:Bachelor|Master|Ph\.?D|MBA|B\.?S\.?|M\.?S\.?|B\.?A\.?|M\.?A\.?)[^.\n]{0,100})",
    ]
    for pattern in edu_patterns:
        edu_match = re.search(pattern, text, re.IGNORECASE)
        if edu_match:
            data["education"] = edu_match.group(1).strip()
            break

    # Current title - look for title-like patterns near the top
    title_patterns = [
        r"(?:^|\n)\s*([A-Z][a-zA-Z]+(?: [A-Z][a-zA-Z]+)*\s*(?:Engineer|Developer|Manager|Analyst|Designer|Architect|Scientist|Lead|Director|Consultant|Specialist))",
    ]
    for pattern in title_patterns:
        title_match = re.search(pattern, text[:1000])
        if title_match:
            data["current_title"] = title_match.group(1).strip()
            break

    # Location - look for city, state patterns
    location_match = re.search(
        r"([A-Z][a-zA-Z\s]+,\s*[A-Z]{2}(?:\s+\d{5})?)", text[:500]
    )
    if location_match:
        data["location"] = location_match.group(1).strip()

    return data


def _extract_with_ai(resume_text):
    """Use AI to extract structured application data."""
    from services.ai_client import call

    prompt = f"""Extract structured application data from this resume. Return a JSON object with these fields:
- "name": full name
- "email": email address
- "phone": phone number
- "location": city, state/country
- "linkedin": LinkedIn URL
- "github": GitHub URL
- "years_of_experience": number as string
- "education": highest degree and institution
- "current_title": most recent job title
- "summary": 2-3 sentence professional summary

RESUME:
{resume_text[:3000]}

Return ONLY valid JSON, no preamble."""

    response = call(prompt, max_tokens=500, endpoint="autofill_extract")
    if response:
        try:
            json_match = re.search(r"\{[\s\S]*?\}", response)
            if json_match:
                return json.loads(json_match.group())
        except (json.JSONDecodeError, ValueError) as e:
            logger.warning("Failed to parse AI autofill response: %s", e)

    return None
