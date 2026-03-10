"""Tests for screening_answerer and application_drafter services."""

import json
from unittest.mock import patch, MagicMock

from services.screening_answerer import generate_screening_answers, _estimate_experience_years
from services.application_drafter import generate_application_draft


SAMPLE_RESUME = """
John Doe
Senior Software Engineer

Experience: 8+ years of professional experience

Skills: Python, JavaScript, TypeScript, React, Node.js, AWS, Docker, Kubernetes,
PostgreSQL, Redis, REST APIs, GraphQL, CI/CD, Agile

Work Experience:
- Senior Software Engineer at TechCorp (2020-Present)
  Led development of microservices architecture using Python and AWS.
  Managed team of 5 engineers. Implemented CI/CD pipelines with GitHub Actions.

- Software Engineer at StartupXYZ (2017-2020)
  Full stack development with React and Node.js.
  Built real-time data pipeline using Kafka and PostgreSQL.

- Junior Developer at WebAgency (2015-2017)
  Frontend development with JavaScript and React.

Education: BS Computer Science, State University, 2015
"""

SAMPLE_JOB_DESC = """
We're looking for a Senior Software Engineer to join our team.
You'll work with Python, AWS, and React to build scalable microservices.
Requirements: 5+ years experience, strong Python skills, AWS experience.
Fully remote position with quarterly onsite meetings.
"""


# --- Screening Answerer Tests ---


class TestEstimateExperienceYears:
    def test_skill_with_date_ranges(self):
        years = _estimate_experience_years(SAMPLE_RESUME, "Python")
        assert years > 0

    def test_unknown_skill_returns_one_if_found(self):
        # "Agile" is mentioned but no date range context
        years = _estimate_experience_years(SAMPLE_RESUME, "Agile")
        assert years >= 1

    def test_missing_skill_returns_zero(self):
        years = _estimate_experience_years(SAMPLE_RESUME, "Rust")
        assert years == 0


class TestScreeningAnswererHeuristic:
    def test_salary_question(self):
        results = generate_screening_answers(
            SAMPLE_RESUME, "Engineer", "Acme", SAMPLE_JOB_DESC,
            ["What are your salary expectations?"]
        )
        assert len(results) == 1
        assert "salary" not in results[0]["answer"].lower() or "flexible" in results[0]["answer"].lower() or "open" in results[0]["answer"].lower()
        assert results[0]["question"] == "What are your salary expectations?"

    def test_experience_years_question(self):
        results = generate_screening_answers(
            SAMPLE_RESUME, "Engineer", "Acme", SAMPLE_JOB_DESC,
            ["How many years of experience do you have with Python?"]
        )
        assert len(results) == 1
        assert "years" in results[0]["answer"].lower()

    def test_interest_question(self):
        results = generate_screening_answers(
            SAMPLE_RESUME, "Senior Engineer", "Acme Corp", SAMPLE_JOB_DESC,
            ["Why are you interested in this role?"]
        )
        assert len(results) == 1
        assert "Acme Corp" in results[0]["answer"]

    def test_why_company_question(self):
        results = generate_screening_answers(
            SAMPLE_RESUME, "Engineer", "BigTech", SAMPLE_JOB_DESC,
            ["Why do you want to work at BigTech?"]
        )
        assert "BigTech" in results[0]["answer"]

    def test_authorization_question(self):
        results = generate_screening_answers(
            SAMPLE_RESUME, "Engineer", "Acme", SAMPLE_JOB_DESC,
            ["Are you authorized to work in the United States?"]
        )
        assert "customize" in results[0]["answer"].lower()

    def test_empty_questions(self):
        results = generate_screening_answers(
            SAMPLE_RESUME, "Engineer", "Acme", SAMPLE_JOB_DESC, []
        )
        assert results == []

    def test_missing_resume(self):
        results = generate_screening_answers(
            "", "Engineer", "Acme", SAMPLE_JOB_DESC,
            ["Why are you interested in this role?"]
        )
        assert len(results) == 1
        assert len(results[0]["answer"]) > 0

    def test_multiple_questions(self):
        questions = [
            "What are your salary expectations?",
            "Why are you interested in this role?",
            "Are you willing to relocate?",
        ]
        results = generate_screening_answers(
            SAMPLE_RESUME, "Engineer", "Acme", SAMPLE_JOB_DESC, questions
        )
        assert len(results) == 3


class TestScreeningAnswererWithClaude:
    @patch("services.ai_client.call")
    @patch("services.ai_client.is_available", return_value=True)
    def test_claude_api_called(self, mock_available, mock_call):
        mock_call.return_value = "1. I have 8 years of experience.\n2. I am very interested."

        results = generate_screening_answers(
            SAMPLE_RESUME, "Engineer", "Acme", SAMPLE_JOB_DESC,
            ["How many years of experience?", "Why are you interested?"]
        )
        assert len(results) == 2
        assert "8 years" in results[0]["answer"]
        mock_call.assert_called_once()


# --- Application Drafter Tests ---


class TestApplicationDrafterHeuristic:
    def test_has_all_required_keys(self):
        result = generate_application_draft(
            SAMPLE_RESUME, {"skills": ["Python", "AWS", "React"]},
            "Senior Engineer", "Acme", SAMPLE_JOB_DESC
        )
        assert "summary" in result
        assert "key_qualifications" in result
        assert "cover_letter_intro" in result
        assert "skills_highlight" in result
        assert "experience_highlight" in result

    def test_skills_highlight_contains_matching(self):
        result = generate_application_draft(
            SAMPLE_RESUME, {"skills": ["Python", "AWS", "React", "Java"]},
            "Senior Engineer", "Acme", SAMPLE_JOB_DESC
        )
        skills = [s.lower() for s in result["skills_highlight"]]
        assert any("python" in s for s in skills)

    def test_empty_job_description(self):
        result = generate_application_draft(
            SAMPLE_RESUME, {"skills": ["Python"]},
            "Engineer", "Acme", ""
        )
        assert result["summary"]
        assert len(result["key_qualifications"]) >= 3

    def test_empty_resume_data(self):
        result = generate_application_draft(
            SAMPLE_RESUME, {},
            "Engineer", "Acme", SAMPLE_JOB_DESC
        )
        assert result["summary"]
        assert result["cover_letter_intro"]

    def test_user_name_in_summary(self):
        result = generate_application_draft(
            SAMPLE_RESUME, {"skills": ["Python"]},
            "Engineer", "Acme", SAMPLE_JOB_DESC,
            user_name="Jane Smith"
        )
        assert "Jane Smith" in result["summary"]


class TestApplicationDrafterWithClaude:
    @patch("services.ai_client.call")
    @patch("services.ai_client.is_available", return_value=True)
    def test_claude_api_called(self, mock_available, mock_call):
        mock_call.return_value = """SUMMARY:
A talented engineer with Python and AWS skills.

KEY_QUALIFICATIONS:
- Expert in Python
- AWS certified
- Team leader

COVER_LETTER_INTRO:
I am excited to apply for this role.

SKILLS_HIGHLIGHT:
- Python
- AWS
- React

EXPERIENCE_HIGHLIGHT:
- Led microservices development
- Built data pipelines"""

        result = generate_application_draft(
            SAMPLE_RESUME, {"skills": ["Python"]},
            "Engineer", "Acme", SAMPLE_JOB_DESC
        )
        assert "talented engineer" in result["summary"].lower()
        assert len(result["key_qualifications"]) == 3
        assert "Python" in result["skills_highlight"]
        mock_call.assert_called_once()
