import logging
import re

from config import Config

logger = logging.getLogger(__name__)


def _estimate_experience_years(resume_text, skill):
    """Estimate years of experience with a skill from resume text."""
    skill_lower = skill.lower()
    resume_lower = resume_text.lower()

    if skill_lower not in resume_lower:
        return 0

    # Look for explicit year mentions near the skill
    # e.g., "5+ years of Python", "Python (3 years)"
    patterns = [
        rf"(\d+)\+?\s*(?:years?|yrs?)\s+(?:of\s+)?(?:experience\s+(?:with|in)\s+)?{re.escape(skill_lower)}",
        rf"{re.escape(skill_lower)}\s*[\(\-:]\s*(\d+)\+?\s*(?:years?|yrs?)",
        rf"(\d+)\+?\s*(?:years?|yrs?)\s+(?:of\s+)?{re.escape(skill_lower)}",
    ]
    for pattern in patterns:
        match = re.search(pattern, resume_lower)
        if match:
            return int(match.group(1))

    # Look for date ranges in work experience sections and count if skill appears nearby
    date_ranges = re.findall(r"(\d{4})\s*[-–]\s*(\d{4}|[Pp]resent|[Cc]urrent)", resume_text)
    total_years = 0
    for start_str, end_str in date_ranges:
        start = int(start_str)
        if end_str.lower() in ("present", "current"):
            end = 2026
        else:
            end = int(end_str)
        # Check if skill appears in a nearby context (within ~200 chars of dates)
        idx = resume_text.find(start_str)
        if idx >= 0:
            context = resume_lower[max(0, idx - 100):idx + 300]
            if skill_lower in context:
                total_years += max(0, end - start)

    return total_years if total_years > 0 else 1  # default to 1 if skill found in resume


def _heuristic_answer(question, resume_text, job_title, company, job_description, user_name=""):
    """Generate a heuristic answer for common screening questions."""
    q_lower = question.lower().strip()

    # Salary expectations
    if any(kw in q_lower for kw in ["salary", "compensation", "pay expectation", "desired pay"]):
        return (
            "I am open to discussing compensation and would appreciate learning more about "
            "the full benefits package. I am flexible and looking for a fair offer that "
            "reflects the role's responsibilities and my experience."
        )

    # Work authorization
    if any(kw in q_lower for kw in ["authorized", "authorization", "work permit", "visa", "right to work", "legally"]):
        return "Please customize this answer"

    # Relocation
    if any(kw in q_lower for kw in ["relocat", "willing to move"]):
        return "Please customize this answer"

    # Notice period
    if any(kw in q_lower for kw in ["notice period", "start date", "when can you start", "availability"]):
        return "Please customize this answer"

    # Years of experience with a specific skill
    exp_match = re.search(
        r"(?:how many|number of)\s+years?\s+(?:of\s+)?(?:experience|exp)\s+(?:with|in|using)\s+(.+?)[\?\.]?\s*$",
        q_lower,
    )
    if exp_match:
        skill = exp_match.group(1).strip().rstrip("?.")
        years = _estimate_experience_years(resume_text, skill)
        if years > 0:
            return f"I have approximately {years} years of experience with {skill}."
        return f"While {skill} is not prominently featured on my resume, I am eager to develop my skills in this area."

    # Generic experience years question
    if re.search(r"how many years", q_lower) and "experience" in q_lower:
        years_match = re.search(r"(\d+)\+?\s*years?\s+(?:of\s+)?(?:professional\s+)?experience", resume_text.lower())
        if years_match:
            return f"I have {years_match.group(1)}+ years of professional experience."
        # Count from date ranges
        date_ranges = re.findall(r"(\d{4})\s*[-–]\s*(\d{4}|[Pp]resent|[Cc]urrent)", resume_text)
        if date_ranges:
            earliest = min(int(d[0]) for d in date_ranges)
            total = 2026 - earliest
            return f"I have approximately {total} years of professional experience."
        return "I have several years of relevant professional experience. Please see my resume for details."

    # Why this company
    if any(phrase in q_lower for phrase in ["why do you want to work at", "why this company", "why do you want to join"]):
        return (
            f"I am drawn to {company} because of its reputation in the industry. "
            f"The {job_title} role aligns well with my background and career goals, "
            f"and I am excited about the opportunity to contribute to the team's success."
        )

    # Why interested in this role
    if any(phrase in q_lower for phrase in ["why are you interested", "why this role", "what attracted you", "why do you want this"]):
        return (
            f"The {job_title} position at {company} is a strong match for my skills and experience. "
            f"I am particularly interested in the opportunity to apply my expertise in a role that "
            f"offers both challenge and growth potential."
        )

    # Describe experience with technology
    desc_match = re.search(
        r"(?:describe|tell us about|explain)\s+(?:your\s+)?experience\s+(?:with|in|using)\s+(.+?)[\?\.]?\s*$",
        q_lower,
    )
    if desc_match:
        tech = desc_match.group(1).strip().rstrip("?.")
        tech_lower = tech.lower()
        # Find sentences mentioning the tech
        sentences = re.split(r'[.\n]', resume_text)
        relevant = [s.strip() for s in sentences if tech_lower in s.lower() and len(s.strip()) > 20]
        if relevant:
            snippet = ". ".join(relevant[:2]) + "."
            return f"I have hands-on experience with {tech}. {snippet}"
        return (
            f"While my resume does not highlight {tech} extensively, I have a strong foundation "
            f"in related technologies and am confident in my ability to ramp up quickly."
        )

    # Default fallback
    display_name = user_name or "the candidate"
    return (
        f"As a candidate for the {job_title} role at {company}, "
        f"I bring relevant skills and experience that align well with the position requirements. "
        f"Please see my resume for specific details."
    )


def generate_screening_answers(resume_text, job_title, company, job_description, questions, user_name=""):
    """Generate answers to a list of screening questions.

    Args:
        resume_text: User's resume text
        job_title: The job title
        company: Company name
        job_description: Job description text
        questions: list of question strings
        user_name: User's name for personalization

    Returns:
        list of {"question": str, "answer": str} dicts
    """
    if not questions:
        return []

    # Try Claude API first
    if Config.ANTHROPIC_API_KEY and resume_text:
        try:
            import anthropic
            client = anthropic.Anthropic(api_key=Config.ANTHROPIC_API_KEY)

            questions_text = "\n".join(f"{i+1}. {q}" for i, q in enumerate(questions))

            prompt = f"""Answer the following job application screening questions based on the candidate's resume.
For each question, provide a professional, concise answer (2-4 sentences).
If the resume doesn't contain enough information to answer confidently, provide a reasonable template answer.
For salary questions, give a diplomatic response without committing to specific numbers.
For authorization/relocation/notice period questions, respond with "Please customize this answer".

Candidate Name: {user_name or 'the candidate'}

Resume:
{resume_text[:3000]}

Job Title: {job_title}
Company: {company}
Job Description:
{job_description[:2000]}

Questions:
{questions_text}

Return answers in this exact format (one per question, numbered to match):
1. [answer to question 1]
2. [answer to question 2]
...and so on. Return ONLY the numbered answers, no other text."""

            message = client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=2000,
                messages=[{"role": "user", "content": prompt}],
            )

            response_text = message.content[0].text.strip()
            # Parse numbered answers
            answers = []
            lines = response_text.split("\n")
            current_answer = ""
            current_num = 0

            for line in lines:
                num_match = re.match(r"^(\d+)\.\s*(.+)", line)
                if num_match:
                    if current_num > 0 and current_num <= len(questions):
                        answers.append(current_answer.strip())
                    current_num = int(num_match.group(1))
                    current_answer = num_match.group(2)
                elif current_num > 0:
                    current_answer += " " + line.strip()

            if current_num > 0 and current_num <= len(questions):
                answers.append(current_answer.strip())

            # Build result, falling back to heuristic for any missing answers
            results = []
            for i, q in enumerate(questions):
                if i < len(answers) and answers[i]:
                    results.append({"question": q, "answer": answers[i]})
                else:
                    results.append({
                        "question": q,
                        "answer": _heuristic_answer(q, resume_text, job_title, company, job_description, user_name),
                    })
            return results

        except Exception as e:
            logger.error("Claude screening answers failed: %s", e)

    # Heuristic fallback
    results = []
    for q in questions:
        answer = _heuristic_answer(q, resume_text or "", job_title, company, job_description, user_name)
        results.append({"question": q, "answer": answer})
    return results
