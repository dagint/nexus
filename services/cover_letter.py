import logging
import re

logger = logging.getLogger(__name__)


def generate_cover_letter(resume_text, job_title, company, job_description, user_name=""):
    """Generate a tailored cover letter using Claude API, with heuristic fallback."""
    from services.ai_client import call

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

    result = call(prompt, model="claude-sonnet-4-20250514", max_tokens=1000, endpoint="cover_letter")
    if result:
        return result

    # Heuristic fallback
    return _generate_template_letter(resume_text, job_title, company, job_description, user_name)


def _generate_template_letter(resume_text, job_title, company, job_description, user_name=""):
    """Generate a basic cover letter from resume keywords and job info."""
    name = user_name or "[Your Name]"
    jd_lower = job_description.lower()
    resume_lower = resume_text.lower()

    skill_patterns = [
        "python", "javascript", "typescript", "java", "c#", "go", "rust", "ruby",
        "react", "angular", "vue", "node.js", "django", "flask", "spring",
        "aws", "azure", "gcp", "docker", "kubernetes", "terraform",
        "sql", "postgresql", "mongodb", "redis", "elasticsearch",
        "machine learning", "data analysis", "project management",
        "leadership", "agile", "scrum", "ci/cd", "devops",
        "security", "networking", "linux", "cloud", "microservices",
        "rest api", "graphql", "git", "testing", "automation",
    ]

    matching_skills = [s for s in skill_patterns if s in resume_lower and s in jd_lower]
    resume_only_skills = [s for s in skill_patterns if s in resume_lower and s not in jd_lower]

    years_match = re.search(r'(\d+)\+?\s*years?\s*(of)?\s*(experience|exp)', resume_lower)
    years = years_match.group(1) if years_match else None

    skills_str = ", ".join(matching_skills[:5]) if matching_skills else ", ".join(resume_only_skills[:5])
    experience_line = f"With {years}+ years of experience" if years else "With my professional experience"

    letter = f"""Dear Hiring Manager,

I am excited to apply for the {job_title} position at {company}. {experience_line} in {skills_str or 'this field'}, I am confident that my background aligns well with what you are looking for.

"""

    if matching_skills:
        letter += f"My expertise in {', '.join(matching_skills[:3])} directly aligns with the requirements for this role. "
    if len(matching_skills) > 3:
        letter += f"I also bring strong skills in {', '.join(matching_skills[3:6])}, which I believe would add value to your team. "
    elif resume_only_skills:
        letter += f"Additionally, my experience with {', '.join(resume_only_skills[:3])} provides a solid foundation for contributing effectively. "

    letter += f"""I am particularly drawn to {company} and the opportunity to contribute as a {job_title}.

I would welcome the opportunity to discuss how my skills and experience can contribute to your team's success. Thank you for considering my application, and I look forward to hearing from you.

Best regards,
{name}"""

    return letter.strip()
