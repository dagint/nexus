"""AI-powered networking advisor for job seekers."""
import json
import logging

from services.ai_client import call as ai_call, is_available as ai_available

logger = logging.getLogger(__name__)


def get_networking_suggestions(resume_text, job_title, company, job_description="", user_id=None):
    """Generate networking advice for a target company and role.

    Returns a dict with:
    - who_to_connect_with: list of role titles to target
    - conversation_starters: list of conversation starter ideas
    - linkedin_groups: list of relevant LinkedIn groups to join
    - events_to_attend: list of event types to look for
    - email_templates: list of dicts with subject and body
    """
    if ai_available():
        prompt = f"""You are a career networking advisor. Generate specific, actionable networking advice
for someone applying to a {job_title} role at {company}.

Job description excerpt:
{job_description[:800]}

Resume excerpt:
{resume_text[:500]}

Return a JSON object with these keys:
- "who_to_connect_with": array of 4-5 specific role titles at {company} that would be valuable connections (e.g., "Engineering Manager", "Senior Developer on the Platform team")
- "conversation_starters": array of 4-5 conversation starters tailored to {company} and the role
- "linkedin_groups": array of 3-4 relevant LinkedIn groups or communities to join
- "events_to_attend": array of 3-4 types of events, conferences, or meetups relevant to this role/industry
- "email_templates": array of 2 objects, each with "subject" and "body" keys, for cold outreach emails

Make all suggestions specific to the company and role, not generic.
Return ONLY valid JSON, no other text."""

        result = ai_call(prompt, max_tokens=1500, endpoint="networking_advice", user_id=user_id)
        if result:
            try:
                # Try to extract JSON from the response
                text = result.strip()
                if text.startswith("```"):
                    text = text.split("\n", 1)[1] if "\n" in text else text[3:]
                    text = text.rsplit("```", 1)[0]
                data = json.loads(text)
                return data
            except (json.JSONDecodeError, KeyError) as e:
                logger.warning("Failed to parse networking advice JSON: %s", e)

    # Heuristic fallback
    return {
        "who_to_connect_with": [
            f"Hiring Manager for {job_title}",
            f"Technical Lead or Senior Engineer at {company}",
            f"HR/Talent Acquisition Specialist at {company}",
            f"Current {job_title} at {company}",
            f"Department Director at {company}",
        ],
        "conversation_starters": [
            f"I noticed {company}'s recent work in the industry -- would love to hear about your experience on the team.",
            f"I'm exploring {job_title} roles and {company} stands out. What do you enjoy most about working there?",
            f"I saw that {company} is hiring for {job_title}. Could you share what the team culture is like?",
            "I'd love to learn more about the technical challenges your team is solving.",
            "What skills or qualities does your team value most in new hires?",
        ],
        "linkedin_groups": [
            f"{job_title} Professionals Network",
            f"{company} Alumni & Employees",
            "Industry-specific professional group (search for your tech stack)",
            "Local tech community or meetup group",
        ],
        "events_to_attend": [
            "Industry conferences related to your tech stack",
            f"Local meetups in your area (search Meetup.com for {job_title} events)",
            f"{company} hosted webinars or tech talks (check their engineering blog)",
            "Virtual career fairs in your industry",
        ],
        "email_templates": [
            {
                "subject": f"Interest in {job_title} at {company}",
                "body": f"Hi [Name],\n\nI came across the {job_title} position at {company} and I'm very interested. I have experience in [relevant skills] and would love to learn more about the role and team.\n\nWould you be open to a brief 15-minute call this week? I'm flexible on timing.\n\nBest regards,\n[Your Name]",
            },
            {
                "subject": f"Quick question about {company}'s engineering team",
                "body": f"Hi [Name],\n\nI hope this email finds you well. I've been following {company}'s work and I'm impressed by [specific thing].\n\nI'm currently exploring {job_title} opportunities and I'd value your perspective on what it's like working at {company}. Would you have 10 minutes for a quick chat?\n\nThank you for your time,\n[Your Name]",
            },
        ],
    }
