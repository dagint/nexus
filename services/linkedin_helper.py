"""LinkedIn networking helper - generates connection notes, messages, and search URLs."""
import logging
import urllib.parse

from services.ai_client import call as ai_call, is_available as ai_available

logger = logging.getLogger(__name__)


def generate_linkedin_note(resume_text, job_title, company, user_id=None):
    """Generate a LinkedIn connection request note (max 300 characters).

    Returns the note text, or a fallback if AI is unavailable.
    """
    if ai_available():
        prompt = f"""Write a short LinkedIn connection request note (max 280 characters) from a job seeker
to someone at {company} for the {job_title} role.

The note should be:
- Professional but warm
- Mention genuine interest in the company
- Reference a relevant skill from the resume
- End with a clear but non-pushy ask

Resume excerpt (first 500 chars):
{resume_text[:500]}

Return ONLY the note text, nothing else. Keep it under 280 characters."""

        result = ai_call(prompt, max_tokens=200, endpoint="linkedin_note", user_id=user_id)
        if result:
            # Enforce 300 char limit
            return result[:300]

    # Heuristic fallback
    return (
        f"Hi! I'm interested in the {job_title} role at {company} and would love to connect. "
        f"I have relevant experience and would appreciate the chance to learn more about the team. "
        f"Thanks for considering!"
    )[:300]


def generate_linkedin_message(resume_text, job_title, company, recruiter_name=None, user_id=None):
    """Generate a LinkedIn InMail/message for a recruiter or hiring manager.

    Returns the message text, or a fallback if AI is unavailable.
    """
    name_ref = recruiter_name or "the hiring team"

    if ai_available():
        prompt = f"""Write a LinkedIn message from a job seeker to {name_ref} at {company}
about the {job_title} position.

The message should:
- Be 3-4 short paragraphs
- Open with a personalized greeting
- Briefly highlight 2-3 relevant qualifications from the resume
- Express genuine interest in the company/role
- End with a clear call to action (request a brief call or meeting)
- Be professional but conversational

Resume excerpt (first 800 chars):
{resume_text[:800]}

Return ONLY the message text."""

        result = ai_call(prompt, max_tokens=500, endpoint="linkedin_message", user_id=user_id)
        if result:
            return result

    # Heuristic fallback
    greeting = f"Hi {recruiter_name}," if recruiter_name else "Hello,"
    return f"""{greeting}

I hope this message finds you well. I came across the {job_title} position at {company} and I'm very interested in the opportunity.

With my background and experience, I believe I could be a strong fit for the role. I'm particularly drawn to {company}'s work and would welcome the chance to discuss how my skills align with what you're looking for.

Would you be open to a brief conversation about the role? I'm flexible on timing and happy to work around your schedule.

Thank you for your time, and I look forward to hearing from you."""


def get_linkedin_search_url(job_title, company):
    """Generate a LinkedIn search URL to find relevant people at the company.

    Returns a dict with different search URLs.
    """
    base = "https://www.linkedin.com/search/results/people/"

    # Search for people at the company
    company_search = base + "?" + urllib.parse.urlencode({
        "keywords": company,
        "origin": "GLOBAL_SEARCH_HEADER",
    })

    # Search for recruiters at the company
    recruiter_search = base + "?" + urllib.parse.urlencode({
        "keywords": f"{company} recruiter",
        "origin": "GLOBAL_SEARCH_HEADER",
    })

    # Search for hiring managers (title-based)
    manager_search = base + "?" + urllib.parse.urlencode({
        "keywords": f"{company} hiring manager {job_title}",
        "origin": "GLOBAL_SEARCH_HEADER",
    })

    # Company page search
    company_page = "https://www.linkedin.com/search/results/companies/?" + urllib.parse.urlencode({
        "keywords": company,
        "origin": "GLOBAL_SEARCH_HEADER",
    })

    return {
        "company_people": company_search,
        "recruiters": recruiter_search,
        "hiring_managers": manager_search,
        "company_page": company_page,
    }
