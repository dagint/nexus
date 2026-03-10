import logging
import re

from config import Config

logger = logging.getLogger(__name__)


def _extract_matching_skills(resume_text, resume_data, job_description):
    """Find skills from the resume that appear in the job description."""
    jd_lower = job_description.lower()
    matching = []

    skills = resume_data.get("skills", [])
    for skill in skills:
        skill_name = skill["skill"] if isinstance(skill, dict) else skill
        if skill_name.lower() in jd_lower:
            matching.append(skill_name)

    # Also check raw resume text for common skills mentioned in JD
    if not matching:
        common_skills = re.findall(r'\b([A-Z][a-zA-Z+#]+(?:\.[a-zA-Z]+)?)\b', job_description)
        resume_lower = resume_text.lower()
        for skill in common_skills:
            if skill.lower() in resume_lower and len(skill) > 2:
                matching.append(skill)

    return list(dict.fromkeys(matching))[:10]  # deduplicate, limit to 10


def _extract_relevant_experience(resume_text, job_description):
    """Find experience sentences from resume relevant to the job."""
    jd_lower = job_description.lower()
    # Extract important keywords from job description (nouns/verbs, 4+ chars)
    jd_words = set(re.findall(r'\b[a-zA-Z]{4,}\b', jd_lower))

    sentences = re.split(r'[.\n]', resume_text)
    scored = []
    for s in sentences:
        s = s.strip()
        if len(s) < 30:
            continue
        s_lower = s.lower()
        overlap = sum(1 for w in jd_words if w in s_lower)
        if overlap > 0:
            scored.append((overlap, s))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [s for _, s in scored[:5]]


def _heuristic_draft(resume_text, resume_data, job_title, company, job_description, user_name=""):
    """Generate an application draft using heuristics."""
    name = user_name or "the candidate"
    matching_skills = _extract_matching_skills(resume_text, resume_data, job_description)
    relevant_exp = _extract_relevant_experience(resume_text, job_description)

    # Summary
    skills_str = ", ".join(matching_skills[:5]) if matching_skills else "relevant technical skills"
    summary = (
        f"{name} is an experienced professional with expertise in {skills_str}. "
        f"With a background that aligns well with the {job_title} role at {company}, "
        f"{name} brings a proven track record of delivering results in similar positions."
    )

    # Key qualifications
    qualifications = []
    if matching_skills:
        qualifications.append(f"Proficient in {', '.join(matching_skills[:3])}")
    if relevant_exp:
        for exp in relevant_exp[:3]:
            # Trim to reasonable length
            qualifications.append(exp[:150].rstrip() + ("..." if len(exp) > 150 else ""))
    # Pad to at least 3
    while len(qualifications) < 3:
        qualifications.append(
            f"Strong background relevant to the {job_title} position"
        )
    qualifications = qualifications[:5]

    # Cover letter intro
    cover_letter_intro = (
        f"I am excited to apply for the {job_title} position at {company}. "
        f"My experience with {skills_str} makes me a strong fit for this role, "
        f"and I am eager to contribute to your team's success."
    )

    # Experience highlight
    experience_highlight = relevant_exp if relevant_exp else [
        f"Experienced professional with skills relevant to the {job_title} role."
    ]

    return {
        "summary": summary,
        "key_qualifications": qualifications,
        "cover_letter_intro": cover_letter_intro,
        "skills_highlight": matching_skills if matching_skills else ["See resume for full skills list"],
        "experience_highlight": experience_highlight,
    }


def generate_application_draft(resume_text, resume_data, job_title, company, job_description, user_name=""):
    """Generate an application draft with key sections pre-filled.

    Args:
        resume_text: User's resume text
        resume_data: Parsed resume data dict (with skills, job_titles, etc.)
        job_title: The job title
        company: Company name
        job_description: Job description text
        user_name: User's name for personalization

    Returns:
        dict with: summary, key_qualifications, cover_letter_intro,
                    skills_highlight, experience_highlight
    """
    if not resume_data:
        resume_data = {}

    # Try Claude API first
    if Config.ANTHROPIC_API_KEY and resume_text:
        try:
            import anthropic
            client = anthropic.Anthropic(api_key=Config.ANTHROPIC_API_KEY)

            prompt = f"""Based on the candidate's resume and the job description, generate an application draft.

Candidate Name: {user_name or 'the candidate'}

Resume:
{resume_text[:3000]}

Job Title: {job_title}
Company: {company}
Job Description:
{job_description[:2000]}

Return the draft in this exact format:

SUMMARY:
[2-3 sentence professional summary tailored to this job]

KEY_QUALIFICATIONS:
- [qualification 1]
- [qualification 2]
- [qualification 3]
- [qualification 4]
- [qualification 5]

COVER_LETTER_INTRO:
[Opening paragraph for a cover letter]

SKILLS_HIGHLIGHT:
- [skill 1]
- [skill 2]
- [skill 3]
- [skill 4]
- [skill 5]

EXPERIENCE_HIGHLIGHT:
- [relevant experience snippet 1]
- [relevant experience snippet 2]
- [relevant experience snippet 3]

Return ONLY the formatted sections above, nothing else."""

            message = client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=1500,
                messages=[{"role": "user", "content": prompt}],
            )

            text = message.content[0].text.strip()

            # Parse sections
            def extract_section(section_name, text):
                pattern = rf"{section_name}:\s*\n(.*?)(?=\n[A-Z_]+:|$)"
                match = re.search(pattern, text, re.DOTALL)
                if match:
                    return match.group(1).strip()
                return ""

            def parse_bullets(section_text):
                items = re.findall(r"[-•]\s*(.+)", section_text)
                return [item.strip() for item in items if item.strip()]

            summary = extract_section("SUMMARY", text)
            quals_text = extract_section("KEY_QUALIFICATIONS", text)
            intro = extract_section("COVER_LETTER_INTRO", text)
            skills_text = extract_section("SKILLS_HIGHLIGHT", text)
            exp_text = extract_section("EXPERIENCE_HIGHLIGHT", text)

            result = {
                "summary": summary or _heuristic_draft(resume_text, resume_data, job_title, company, job_description, user_name)["summary"],
                "key_qualifications": parse_bullets(quals_text) or _heuristic_draft(resume_text, resume_data, job_title, company, job_description, user_name)["key_qualifications"],
                "cover_letter_intro": intro or _heuristic_draft(resume_text, resume_data, job_title, company, job_description, user_name)["cover_letter_intro"],
                "skills_highlight": parse_bullets(skills_text) or _heuristic_draft(resume_text, resume_data, job_title, company, job_description, user_name)["skills_highlight"],
                "experience_highlight": parse_bullets(exp_text) or _heuristic_draft(resume_text, resume_data, job_title, company, job_description, user_name)["experience_highlight"],
            }
            return result

        except Exception as e:
            logger.error("Claude application draft failed: %s", e)

    # Heuristic fallback
    return _heuristic_draft(resume_text or "", resume_data, job_title, company, job_description, user_name)
