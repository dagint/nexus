import logging
import re
from config import Config

logger = logging.getLogger(__name__)

# Common technical skills and associated interview questions
SKILL_QUESTIONS = {
    "python": [
        "Explain the difference between a list and a tuple in Python.",
        "How do you handle memory management in Python?",
        "Describe your experience with Python's async/await pattern.",
        "What are decorators and how have you used them?",
    ],
    "javascript": [
        "Explain closures in JavaScript and give a practical example.",
        "What is the event loop and how does it work?",
        "Describe the difference between var, let, and const.",
        "How do you handle asynchronous operations in JavaScript?",
    ],
    "typescript": [
        "How do TypeScript generics improve code reusability?",
        "Explain the difference between interfaces and type aliases.",
        "How do you handle strict null checks in TypeScript?",
    ],
    "react": [
        "Explain the virtual DOM and reconciliation process.",
        "When would you use useEffect vs useMemo vs useCallback?",
        "How do you manage state in a large React application?",
        "Describe your approach to component testing in React.",
    ],
    "node": [
        "How does Node.js handle concurrent requests?",
        "Explain the difference between process.nextTick and setImmediate.",
        "How do you handle errors in Express middleware?",
    ],
    "aws": [
        "Describe the AWS services you have worked with and how you used them.",
        "How would you design a highly available system on AWS?",
        "Explain the difference between SQS and SNS.",
        "How do you manage infrastructure as code on AWS?",
    ],
    "docker": [
        "Explain multi-stage Docker builds and their benefits.",
        "How do you optimize Docker image sizes?",
        "Describe your experience with Docker networking.",
    ],
    "kubernetes": [
        "Explain the difference between a Deployment and a StatefulSet.",
        "How do you handle rolling updates in Kubernetes?",
        "Describe your experience with Kubernetes networking and services.",
    ],
    "sql": [
        "Explain the difference between INNER JOIN and LEFT JOIN.",
        "How do you optimize slow SQL queries?",
        "Describe your experience with database indexing strategies.",
    ],
    "postgresql": [
        "What PostgreSQL-specific features have you used?",
        "How do you handle database migrations in production?",
        "Explain your approach to query optimization in PostgreSQL.",
    ],
    "redis": [
        "What data structures in Redis have you used and for what purpose?",
        "How do you handle cache invalidation?",
        "Describe your experience with Redis pub/sub or streams.",
    ],
    "graphql": [
        "What are the advantages and drawbacks of GraphQL vs REST?",
        "How do you handle N+1 query problems in GraphQL?",
        "Describe your approach to GraphQL schema design.",
    ],
    "ci/cd": [
        "Describe your CI/CD pipeline setup and tools used.",
        "How do you handle rollbacks in your deployment process?",
        "What testing strategies do you include in your CI pipeline?",
    ],
    "microservices": [
        "How do you handle inter-service communication?",
        "Describe your approach to distributed tracing and monitoring.",
        "How do you handle data consistency across microservices?",
    ],
    "agile": [
        "Describe your experience with Agile methodologies.",
        "How do you handle changing requirements mid-sprint?",
    ],
    "machine learning": [
        "Describe a machine learning model you have built and deployed.",
        "How do you handle imbalanced datasets?",
        "What is your approach to feature engineering?",
    ],
    "java": [
        "Explain the Java memory model and garbage collection.",
        "How do you handle concurrency in Java?",
        "Describe your experience with Spring Boot.",
    ],
    "go": [
        "Explain goroutines and channels in Go.",
        "How does Go handle error management differently from other languages?",
        "Describe your experience with Go's concurrency model.",
    ],
    "rust": [
        "Explain ownership and borrowing in Rust.",
        "How does Rust prevent data races at compile time?",
    ],
}

BEHAVIORAL_QUESTIONS = [
    {
        "question": "Tell me about a time you had to deal with a difficult team member or stakeholder.",
        "talking_points": "Use the STAR method (Situation, Task, Action, Result). Focus on how you communicated, found common ground, and what the outcome was. Emphasize empathy and professionalism.",
    },
    {
        "question": "Describe a situation where you had to meet a tight deadline.",
        "talking_points": "Use the STAR method. Explain how you prioritized tasks, communicated with stakeholders about scope, and what trade-offs you made. Highlight the successful delivery.",
    },
    {
        "question": "Tell me about a project you are most proud of.",
        "talking_points": "Choose a project that demonstrates relevant skills. Describe the challenge, your specific contributions, the impact, and what you learned. Quantify results if possible.",
    },
    {
        "question": "Describe a time when you made a mistake at work. How did you handle it?",
        "talking_points": "Be honest about a real mistake. Focus on how you identified it, communicated it to stakeholders, fixed it, and what you did to prevent it from happening again.",
    },
    {
        "question": "Tell me about a time you had to learn a new technology or skill quickly.",
        "talking_points": "Describe your learning approach, resources you used, and how you applied the new knowledge. Emphasize adaptability and self-directed learning.",
    },
    {
        "question": "Describe a situation where you disagreed with a technical decision. What did you do?",
        "talking_points": "Show that you can disagree constructively. Explain how you presented your case with data, listened to other perspectives, and either convinced others or committed to the group decision.",
    },
    {
        "question": "Tell me about a time you mentored or helped a junior colleague.",
        "talking_points": "Describe specific actions you took to support their growth. Highlight patience, clear communication, and the positive outcome for both the individual and the team.",
    },
    {
        "question": "Describe how you handle multiple competing priorities.",
        "talking_points": "Explain your prioritization framework (urgency vs importance, business impact). Give a concrete example of juggling tasks and communicating trade-offs to stakeholders.",
    },
]

DEFAULT_QUESTIONS_TO_ASK = [
    "What does a typical day look like for someone in this role?",
    "How is success measured for this position in the first 90 days?",
    "Can you tell me about the team I would be working with?",
    "What are the biggest challenges facing the team right now?",
    "How does the company support professional development?",
    "What is the engineering culture like here?",
    "How do you handle technical debt?",
    "What is the code review and deployment process like?",
]

DEFAULT_RESEARCH_TIPS = [
    "Review the company's recent blog posts and press releases.",
    "Look up the company on Glassdoor for employee reviews and interview experiences.",
    "Check the company's LinkedIn page for recent hires and team structure.",
    "Research the company's competitors and market position.",
    "Look for the company's engineering blog or tech talks for technical culture insights.",
    "Check Crunchbase or similar sites for funding history and company size.",
]


def _extract_skills_from_text(text):
    """Extract known skills from text by simple keyword matching."""
    text_lower = text.lower()
    found = []
    for skill in SKILL_QUESTIONS:
        # Handle multi-word skills and partial matches
        if skill in text_lower:
            found.append(skill)
        # Also check for "node.js" matching "node"
        elif skill == "node" and "node.js" in text_lower:
            found.append(skill)
        elif skill == "sql" and any(
            w in text_lower for w in ["sql", "database", "mysql", "sqlite"]
        ):
            found.append(skill)
        elif skill == "machine learning" and any(
            w in text_lower for w in ["ml", "machine learning", "deep learning", "ai"]
        ):
            found.append(skill)
    return found


def _generate_heuristic_prep(resume_text, job_title, company, job_description, user_name=""):
    """Generate interview prep using heuristic pattern matching."""
    # Find skills in job description
    jd_skills = _extract_skills_from_text(job_description)
    resume_skills = _extract_skills_from_text(resume_text)

    # Prioritize overlapping skills, then JD-only skills
    overlapping = [s for s in jd_skills if s in resume_skills]
    jd_only = [s for s in jd_skills if s not in resume_skills]
    all_relevant = overlapping + jd_only

    # Build technical questions from matched skills
    technical_questions = []
    for skill in all_relevant:
        questions = SKILL_QUESTIONS.get(skill, [])
        for q in questions[:2]:  # Take up to 2 per skill
            talking_points = (
                f"Draw from your experience with {skill}. "
                f"Reference specific projects or accomplishments from your resume. "
                f"Be concrete with examples and quantify impact where possible."
            )
            if skill in overlapping:
                talking_points += (
                    f" You have {skill} on your resume, so highlight that direct experience."
                )
            technical_questions.append({
                "question": q,
                "talking_points": talking_points,
            })

    # If no skills matched, add generic technical questions
    if not technical_questions:
        technical_questions = [
            {
                "question": f"What technical skills would you bring to the {job_title} role?",
                "talking_points": "Review the job description and align your skills with their requirements. Give concrete examples.",
            },
            {
                "question": "Describe a complex technical problem you solved recently.",
                "talking_points": "Use the STAR method. Focus on your problem-solving process and the technical decisions you made.",
            },
            {
                "question": "How do you approach learning new technologies?",
                "talking_points": "Describe your learning strategy with a real example. Show you are self-motivated and adaptable.",
            },
        ]

    # Select behavioral questions (always include a core set)
    behavioral_questions = BEHAVIORAL_QUESTIONS[:6]

    # Build questions to ask, customized to company/role
    questions_to_ask = list(DEFAULT_QUESTIONS_TO_ASK)
    if company:
        questions_to_ask.insert(
            0, f"What excites you most about working at {company}?"
        )
    if "remote" in job_description.lower():
        questions_to_ask.append(
            "How does the team stay connected and collaborate in a remote environment?"
        )
    if "lead" in job_title.lower() or "senior" in job_title.lower() or "manager" in job_title.lower():
        questions_to_ask.append(
            "What is the team's current size and how do you see it evolving?"
        )

    # Company research tips
    research_tips = list(DEFAULT_RESEARCH_TIPS)
    if company:
        research_tips.insert(
            0, f"Search for recent news about {company} to discuss during the interview."
        )

    return {
        "technical_questions": technical_questions,
        "behavioral_questions": behavioral_questions,
        "questions_to_ask": questions_to_ask,
        "company_research_tips": research_tips,
    }


def _generate_ai_prep(resume_text, job_title, company, job_description, user_name=""):
    """Generate interview prep using the Claude API."""
    try:
        from services.ai_client import call as ai_call

        prompt = f"""You are an expert interview coach. Generate interview preparation materials for the following candidate and job.

Candidate Name: {user_name or 'the candidate'}

Resume:
{resume_text[:3000]}

Job Title: {job_title}
Company: {company}
Job Description:
{job_description[:2000]}

Return a JSON object with exactly these keys:
- "technical_questions": array of objects with "question" and "talking_points" keys (5-8 questions based on skills in the job description)
- "behavioral_questions": array of objects with "question" and "talking_points" keys (4-6 questions using STAR method tips)
- "questions_to_ask": array of strings (5-8 questions the candidate should ask the interviewer)
- "company_research_tips": array of strings (4-6 tips for researching {company})

Make the technical questions specific to the technologies and skills mentioned in the job description.
Make the talking points reference the candidate's actual experience from their resume.
Return ONLY valid JSON, no markdown or other text."""

        response_text = ai_call(prompt, model="claude-sonnet-4-20250514", max_tokens=2000)
        if not response_text:
            return None

        import json
        # Handle potential markdown code blocks
        if response_text.startswith("```"):
            response_text = re.sub(r"^```(?:json)?\n?", "", response_text)
            response_text = re.sub(r"\n?```$", "", response_text)
        result = json.loads(response_text)

        # Validate required keys
        required_keys = ["technical_questions", "behavioral_questions", "questions_to_ask", "company_research_tips"]
        for key in required_keys:
            if key not in result:
                logger.warning("AI response missing key: %s, falling back to heuristic", key)
                return None

        return result
    except Exception as e:
        logger.error("AI interview prep generation failed: %s", e)
        return None


def generate_interview_prep(resume_text, job_title, company, job_description, user_name=""):
    """Generate interview preparation materials.

    Returns dict with:
        - technical_questions: list of {"question": str, "talking_points": str}
        - behavioral_questions: list of {"question": str, "talking_points": str}
        - questions_to_ask: list of str (questions the candidate should ask the interviewer)
        - company_research_tips: list of str
    """
    # Try AI generation first if API key is available
    from services.ai_client import is_available
    if is_available():
        result = _generate_ai_prep(resume_text, job_title, company, job_description, user_name)
        if result:
            return result

    # Fall back to heuristic generation
    return _generate_heuristic_prep(resume_text, job_title, company, job_description, user_name)
