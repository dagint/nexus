import logging
from config import Config

logger = logging.getLogger(__name__)


def generate_cover_letter(resume_text, job_title, company, job_description, user_name=""):
    """Generate a tailored cover letter using Claude API.

    Returns the cover letter text, or None if API is unavailable.
    """
    if not Config.ANTHROPIC_API_KEY:
        return None

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=Config.ANTHROPIC_API_KEY)

        prompt = f"""Write a professional, concise cover letter for the following job application.
The letter should:
- Be 3-4 paragraphs
- Highlight relevant experience from the resume that matches the job requirements
- Show enthusiasm for the specific role and company
- Be professional but personable
- NOT use generic filler phrases like "I am writing to express my interest"
- End with a clear call to action

Candidate Name: {user_name or 'the candidate'}

Resume:
{resume_text[:3000]}

Job Title: {job_title}
Company: {company}
Job Description:
{job_description[:2000]}

Return ONLY the cover letter text, no preamble or metadata."""

        message = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1000,
            messages=[{"role": "user", "content": prompt}],
        )
        return message.content[0].text.strip()
    except Exception as e:
        logger.error("Cover letter generation failed: %s", e)
        return None
