"""AI-powered resume tailoring per job description."""
import json
import logging
import re

logger = logging.getLogger(__name__)


def tailor_resume(resume_text, job_title, company, job_description):
    """Suggest resume modifications tailored to a specific job.

    Returns a dict with structured suggestions:
    - sections_to_emphasize: list of str
    - keywords_to_add: list of str
    - skills_to_highlight: list of str
    - reworded_bullets: list of {original, suggested}
    - summary_suggestion: str
    """
    from services.ai_client import is_available, call

    if is_available():
        try:
            return _ai_tailor(resume_text, job_title, company, job_description)
        except Exception as e:
            logger.warning("AI resume tailoring failed, falling back to heuristic: %s", e)

    return _heuristic_tailor(resume_text, job_title, company, job_description)


def _ai_tailor(resume_text, job_title, company, job_description):
    """Use AI to generate tailored resume suggestions."""
    from services.ai_client import call

    prompt = f"""You are a professional resume coach. Analyze this resume against the job description and provide specific tailoring suggestions.

RESUME:
{resume_text[:3000]}

JOB TITLE: {job_title}
COMPANY: {company}
JOB DESCRIPTION:
{job_description[:2000]}

Return a JSON object with these fields:
- "sections_to_emphasize": list of resume sections to move up or expand (e.g., "Technical Skills", "Project Experience")
- "keywords_to_add": list of keywords from the job description missing from the resume that should be incorporated
- "skills_to_highlight": list of skills from the resume that are most relevant to this role
- "reworded_bullets": list of objects with "original" (a bullet point from the resume) and "suggested" (reworded to better match the job), max 5
- "summary_suggestion": a tailored professional summary paragraph for this specific role

Return ONLY valid JSON, no preamble or explanation."""

    response = call(prompt, max_tokens=1500, endpoint="resume_tailor")
    if response:
        try:
            json_match = re.search(r"\{[\s\S]*?\}", response)
            if json_match:
                result = json.loads(json_match.group())
                # Ensure all expected keys exist
                result.setdefault("sections_to_emphasize", [])
                result.setdefault("keywords_to_add", [])
                result.setdefault("skills_to_highlight", [])
                result.setdefault("reworded_bullets", [])
                result.setdefault("summary_suggestion", "")
                return result
        except (json.JSONDecodeError, ValueError) as e:
            logger.warning("Failed to parse AI tailor response: %s", e)

    return _heuristic_tailor(resume_text, job_title, company, job_description)


def _heuristic_tailor(resume_text, job_title, company, job_description):
    """Heuristic keyword-matching fallback for resume tailoring."""
    resume_lower = resume_text.lower()
    desc_lower = job_description.lower()

    # Extract keywords from job description (simple word frequency)
    import re as _re
    from services.constants import STOP_WORDS
    stop_words = STOP_WORDS | {"work", "working", "including", "etc", "don", "now", "down"}

    # Get meaningful words from job description
    desc_words = _re.findall(r"\b[a-z]{3,}\b", desc_lower)
    word_freq = {}
    for w in desc_words:
        if w not in stop_words:
            word_freq[w] = word_freq.get(w, 0) + 1

    # Sort by frequency
    sorted_words = sorted(word_freq.items(), key=lambda x: x[1], reverse=True)

    # Keywords missing from resume
    keywords_to_add = []
    for word, freq in sorted_words[:30]:
        if word not in resume_lower and freq >= 2:
            keywords_to_add.append(word)
        if len(keywords_to_add) >= 10:
            break

    # Skills to highlight (present in both)
    skills_to_highlight = []
    for word, freq in sorted_words[:20]:
        if word in resume_lower and freq >= 2:
            skills_to_highlight.append(word)
        if len(skills_to_highlight) >= 8:
            break

    # Common sections to emphasize based on job type
    sections = []
    title_lower = job_title.lower()
    if any(kw in title_lower for kw in ["engineer", "developer", "architect", "devops"]):
        sections.append("Technical Skills")
        sections.append("Projects / Technical Experience")
    if any(kw in title_lower for kw in ["manager", "lead", "director", "head"]):
        sections.append("Leadership Experience")
        sections.append("Team Management")
    if any(kw in desc_lower for kw in ["certification", "certified", "license"]):
        sections.append("Certifications")
    sections.append("Professional Experience")

    return {
        "sections_to_emphasize": sections[:5],
        "keywords_to_add": keywords_to_add,
        "skills_to_highlight": skills_to_highlight,
        "reworded_bullets": [],
        "summary_suggestion": f"Experienced professional seeking {job_title} role at {company}. "
                              f"Key strengths include: {', '.join(skills_to_highlight[:5]) if skills_to_highlight else 'relevant domain expertise'}.",
    }
