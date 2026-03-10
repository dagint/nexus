"""Elevator pitch generator: creates a concise 'Why I'm a fit' pitch for a job."""
import logging
import re

from services.ai_client import call, is_available

logger = logging.getLogger(__name__)


def generate_elevator_pitch(resume_text, job_title, company, job_description, user_id=None):
    """Generate a 2-3 sentence elevator pitch explaining why the candidate fits the role.

    Uses AI when available, otherwise falls back to heuristic extraction.
    Returns dict with 'pitch' string.
    """
    if is_available() and resume_text:
        pitch = _ai_pitch(resume_text, job_title, company, job_description, user_id)
        if pitch:
            return {"pitch": pitch, "method": "ai"}

    # Heuristic fallback
    pitch = _heuristic_pitch(resume_text, job_title, company, job_description)
    return {"pitch": pitch, "method": "heuristic"}


def _ai_pitch(resume_text, job_title, company, job_description, user_id=None):
    """Use AI to generate a tailored elevator pitch."""
    prompt = f"""You are a career coach. Write a concise 2-3 sentence elevator pitch for a candidate applying to the following role. The pitch should be suitable for cold emails or LinkedIn messages. It should highlight the most relevant experience and skills from the resume that match the job.

Job Title: {job_title}
Company: {company}
Job Description (excerpt): {job_description[:1500]}

Resume (excerpt): {resume_text[:2000]}

Write ONLY the pitch, nothing else. Do not include greetings or sign-offs. Keep it under 75 words."""

    return call(prompt, max_tokens=300, endpoint="elevator_pitch", user_id=user_id)


def _heuristic_pitch(resume_text, job_title, company, job_description):
    """Build a template-based pitch from resume and job data."""
    # Extract years of experience
    years = _extract_years(resume_text)
    # Extract matching skills
    matching_skills = _extract_matching_skills(resume_text, job_description)

    parts = []

    if years:
        parts.append(f"With {years}+ years of experience")
    else:
        parts.append("As an experienced professional")

    if matching_skills:
        skill_str = ", ".join(matching_skills[:4])
        parts.append(f"in {skill_str}")

    sentence1 = " ".join(parts) + f", I'm excited about the {job_title} role at {company}."

    if matching_skills and len(matching_skills) > 2:
        sentence2 = (
            f"My background in {matching_skills[0]} and {matching_skills[1]} "
            f"aligns well with what you're looking for."
        )
    else:
        sentence2 = "My skills and experience align well with what you're looking for."

    sentence3 = "I'd love to discuss how I can contribute to your team."

    return f"{sentence1} {sentence2} {sentence3}"


def _extract_years(resume_text):
    """Extract approximate years of experience from resume text."""
    patterns = [
        r"(\d+)\+?\s*years?\s*(?:of\s+)?(?:experience|professional)",
        r"over\s+(\d+)\s*years?",
        r"(\d+)\+?\s*years?\s*in\s+",
    ]
    for pattern in patterns:
        match = re.search(pattern, resume_text, re.IGNORECASE)
        if match:
            try:
                return int(match.group(1))
            except (ValueError, IndexError):
                pass
    return None


def _extract_matching_skills(resume_text, job_description):
    """Find skills that appear in both the resume and the job description."""
    # Common tech skills to look for
    skill_patterns = [
        "python", "javascript", "typescript", "java", "c\\+\\+", "c#", "go", "rust",
        "react", "angular", "vue", "node\\.js", "django", "flask", "spring",
        "aws", "azure", "gcp", "docker", "kubernetes", "terraform",
        "sql", "postgresql", "mongodb", "redis", "elasticsearch",
        "machine learning", "data science", "deep learning", "nlp",
        "devops", "ci/cd", "agile", "scrum",
        "rest api", "graphql", "microservices",
        "html", "css", "sass",
        "git", "linux", "security",
        "product management", "project management", "leadership",
        "data analysis", "data engineering", "etl",
        "figma", "design systems", "ux",
    ]

    resume_lower = resume_text.lower()
    desc_lower = job_description.lower()
    matches = []

    for skill in skill_patterns:
        if re.search(r"\b" + skill + r"\b", resume_lower) and re.search(r"\b" + skill + r"\b", desc_lower):
            # Capitalize nicely
            display = skill.replace("\\", "")
            if display in ("aws", "gcp", "sql", "css", "html", "nlp", "etl", "ux", "ci/cd"):
                display = display.upper()
            elif display == "node.js":
                display = "Node.js"
            elif display == "c#":
                display = "C#"
            elif display == "c++":
                display = "C++"
            else:
                display = display.title()
            matches.append(display)

    return matches[:6]
