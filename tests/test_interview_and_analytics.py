"""Tests for interview_prep and analytics services."""

import json
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock

from services.interview_prep import generate_interview_prep, _extract_skills_from_text
from services.analytics import get_search_analytics
from database import get_db


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


# --- Interview Prep Tests ---


class TestExtractSkills:
    def test_finds_python(self):
        skills = _extract_skills_from_text("We need a Python developer")
        assert "python" in skills

    def test_finds_multiple_skills(self):
        skills = _extract_skills_from_text(
            "Experience with Python, React, and AWS required"
        )
        assert "python" in skills
        assert "react" in skills
        assert "aws" in skills

    def test_empty_text(self):
        skills = _extract_skills_from_text("")
        assert skills == []


class TestInterviewPrepHeuristic:
    @patch("services.interview_prep.Config")
    def test_returns_all_required_keys(self, mock_config):
        mock_config.ANTHROPIC_API_KEY = ""
        result = generate_interview_prep(
            SAMPLE_RESUME, "Senior Software Engineer", "TechCo", SAMPLE_JOB_DESC
        )
        assert "technical_questions" in result
        assert "behavioral_questions" in result
        assert "questions_to_ask" in result
        assert "company_research_tips" in result

    @patch("services.interview_prep.Config")
    def test_technical_questions_based_on_skills(self, mock_config):
        mock_config.ANTHROPIC_API_KEY = ""
        result = generate_interview_prep(
            SAMPLE_RESUME, "Python Developer", "TechCo",
            "We need an expert in Python and AWS to build microservices."
        )
        tech_qs = result["technical_questions"]
        assert len(tech_qs) > 0
        # At least one question should reference python or AWS content
        all_questions = " ".join(q["question"].lower() for q in tech_qs)
        assert "python" in all_questions or "aws" in all_questions

    @patch("services.interview_prep.Config")
    def test_technical_questions_have_talking_points(self, mock_config):
        mock_config.ANTHROPIC_API_KEY = ""
        result = generate_interview_prep(
            SAMPLE_RESUME, "Developer", "Co", SAMPLE_JOB_DESC
        )
        for q in result["technical_questions"]:
            assert "question" in q
            assert "talking_points" in q
            assert len(q["talking_points"]) > 0

    @patch("services.interview_prep.Config")
    def test_behavioral_questions_present(self, mock_config):
        mock_config.ANTHROPIC_API_KEY = ""
        result = generate_interview_prep(
            SAMPLE_RESUME, "Engineer", "Co", SAMPLE_JOB_DESC
        )
        bq = result["behavioral_questions"]
        assert len(bq) >= 4
        # Should have STAR method tips
        all_tp = " ".join(q["talking_points"].lower() for q in bq)
        assert "star" in all_tp

    @patch("services.interview_prep.Config")
    def test_questions_to_ask_non_empty(self, mock_config):
        mock_config.ANTHROPIC_API_KEY = ""
        result = generate_interview_prep(
            SAMPLE_RESUME, "Engineer", "Acme Corp", "Build software."
        )
        assert len(result["questions_to_ask"]) > 0

    @patch("services.interview_prep.Config")
    def test_company_name_in_research_tips(self, mock_config):
        mock_config.ANTHROPIC_API_KEY = ""
        result = generate_interview_prep(
            SAMPLE_RESUME, "Engineer", "Acme Corp", "Build software."
        )
        tips_text = " ".join(result["company_research_tips"])
        assert "Acme Corp" in tips_text

    @patch("services.interview_prep.Config")
    def test_remote_adds_remote_question(self, mock_config):
        mock_config.ANTHROPIC_API_KEY = ""
        result = generate_interview_prep(
            SAMPLE_RESUME, "Engineer", "Co",
            "This is a fully remote position."
        )
        q_text = " ".join(result["questions_to_ask"]).lower()
        assert "remote" in q_text


class TestInterviewPrepWithAI:
    @patch("services.interview_prep.Config")
    def test_uses_ai_when_available(self, mock_config):
        mock_config.ANTHROPIC_API_KEY = "test-key"
        ai_result = {
            "technical_questions": [{"question": "AI Q1", "talking_points": "AI TP1"}],
            "behavioral_questions": [{"question": "AI BQ1", "talking_points": "AI BTP1"}],
            "questions_to_ask": ["AI ask 1"],
            "company_research_tips": ["AI tip 1"],
        }
        mock_message = MagicMock()
        mock_message.content = [MagicMock(text=json.dumps(ai_result))]

        mock_anthropic_module = MagicMock()
        mock_client = MagicMock()
        mock_anthropic_module.Anthropic.return_value = mock_client
        mock_client.messages.create.return_value = mock_message

        with patch.dict("sys.modules", {"anthropic": mock_anthropic_module}):
            from services.interview_prep import _generate_ai_prep
            result = _generate_ai_prep(
                SAMPLE_RESUME, "Engineer", "Co", SAMPLE_JOB_DESC
            )

        assert result is not None
        assert result["technical_questions"][0]["question"] == "AI Q1"

    @patch("services.interview_prep.Config")
    def test_falls_back_on_ai_failure(self, mock_config):
        mock_config.ANTHROPIC_API_KEY = "test-key"

        with patch("services.interview_prep._generate_ai_prep", return_value=None):
            result = generate_interview_prep(
                SAMPLE_RESUME, "Engineer", "Co", SAMPLE_JOB_DESC
            )

        # Should still get valid heuristic results
        assert "technical_questions" in result
        assert "behavioral_questions" in result


# --- Analytics Tests ---


class TestAnalyticsEmpty:
    def test_empty_analytics(self, fresh_db):
        """New user with no data should return zeroed analytics."""
        from database import create_user
        user_id = create_user("analytics@test.com", "pass123", "Test")
        result = get_search_analytics(user_id)

        assert result["total_applications"] == 0
        assert result["applications_by_stage"] == {}
        assert result["applications_by_week"] == []
        assert result["response_rate"] == 0.0
        assert result["avg_time_to_response"] == 0.0
        assert result["top_skills_in_applied"] == []
        assert result["sources_breakdown"] == {}
        assert result["bookmarks_count"] == 0
        assert result["searches_count"] == 0
        assert result["active_alerts"] == 0


class TestAnalyticsWithData:
    def _setup_user_with_applications(self):
        """Helper to create a user with some applied jobs."""
        from database import create_user, mark_applied
        user_id = create_user("analytics2@test.com", "pass123", "Test")

        # Add applied jobs
        mark_applied(user_id, "job1", "Python Developer", "CompanyA", stage="applied")
        mark_applied(user_id, "job2", "React Developer", "CompanyB", stage="screen")
        mark_applied(user_id, "job3", "Python Engineer", "CompanyC", stage="interview")
        mark_applied(user_id, "job4", "Data Scientist", "CompanyD", stage="rejected")

        return user_id

    def test_total_applications(self, fresh_db):
        user_id = self._setup_user_with_applications()
        result = get_search_analytics(user_id)
        assert result["total_applications"] == 4

    def test_applications_by_stage(self, fresh_db):
        user_id = self._setup_user_with_applications()
        result = get_search_analytics(user_id)
        stages = result["applications_by_stage"]
        assert stages.get("applied") == 1
        assert stages.get("screen") == 1
        assert stages.get("interview") == 1
        assert stages.get("rejected") == 1

    def test_response_rate(self, fresh_db):
        user_id = self._setup_user_with_applications()
        result = get_search_analytics(user_id)
        # 3 out of 4 moved past 'applied'
        assert result["response_rate"] == 75.0

    def test_top_skills_in_applied(self, fresh_db):
        user_id = self._setup_user_with_applications()
        result = get_search_analytics(user_id)
        skills = result["top_skills_in_applied"]
        # "python" appears in two titles
        skill_names = [s["skill"] for s in skills]
        assert "python" in skill_names

    def test_applications_by_week(self, fresh_db):
        """Applications inserted today should appear in the current week."""
        user_id = self._setup_user_with_applications()
        result = get_search_analytics(user_id)
        # All 4 apps were just inserted, so there should be at least one week entry
        assert len(result["applications_by_week"]) >= 1
        total_in_weeks = sum(w["count"] for w in result["applications_by_week"])
        assert total_in_weeks == 4

    def test_bookmarks_and_searches_counted(self, fresh_db):
        from database import create_user, bookmark_job, add_search_history
        user_id = create_user("analytics3@test.com", "pass123", "Test")

        bookmark_job(user_id, {
            "job_key": "bk1", "title": "Dev", "company": "Co",
            "location": "NY", "apply_url": "http://example.com",
        })
        bookmark_job(user_id, {
            "job_key": "bk2", "title": "Dev2", "company": "Co2",
            "location": "SF", "apply_url": "http://example.com",
        })
        add_search_history(user_id, "python", "NYC", False, result_count=5)

        result = get_search_analytics(user_id)
        assert result["bookmarks_count"] == 2
        assert result["searches_count"] == 1

    def test_active_alerts_counted(self, fresh_db):
        from database import create_user, create_saved_search
        user_id = create_user("analytics4@test.com", "pass123", "Test")
        create_saved_search(user_id, "python", "NYC", False, "[]", "daily")
        create_saved_search(user_id, "react", "SF", True, "[]", "weekly")

        result = get_search_analytics(user_id)
        assert result["active_alerts"] == 2
