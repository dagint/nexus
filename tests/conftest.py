import os
import sys
import tempfile

import pytest

# Add project root to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

os.environ["FLASK_SECRET_KEY"] = "test-secret"

_counter = 0


@pytest.fixture(autouse=True)
def fresh_db(tmp_path):
    """Give each test a fresh database."""
    global _counter
    _counter += 1
    db_path = str(tmp_path / f"test_{_counter}.db")
    os.environ["DB_PATH"] = db_path

    from config import Config
    Config.DB_PATH = db_path

    from database import init_db
    init_db()

    yield


@pytest.fixture
def app():
    from app import app, limiter
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    limiter.enabled = False
    yield app


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def auth_client(app):
    """A test client with a logged-in user."""
    c = app.test_client()
    c.post("/register", data={
        "email": "test@example.com",
        "password": "testpass123",
        "name": "Test User",
    })
    return c


@pytest.fixture
def sample_resume_text():
    return """
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


@pytest.fixture
def sample_job():
    return {
        "title": "Senior Software Engineer",
        "company": "Great Company",
        "location": "San Francisco, CA",
        "remote_status": "remote",
        "description": """
        We're looking for a Senior Software Engineer to join our team.
        You'll work with Python, AWS, and React to build scalable microservices.
        Requirements: 5+ years experience, strong Python skills, AWS experience.
        Fully remote position with quarterly onsite meetings.
        Travel 10% for team events.
        """,
        "apply_url": "https://example.com/apply",
        "salary_min": 150000,
        "salary_max": 200000,
        "posted_date": "2026-03-01",
        "source": "JSearch",
        "job_key": "test123",
    }


@pytest.fixture
def mock_jsearch_response():
    return {
        "data": [
            {
                "job_title": "Python Developer",
                "employer_name": "TechCo",
                "job_city": "New York",
                "job_is_remote": True,
                "job_description": "Build Python applications with Django and AWS.",
                "job_apply_link": "https://example.com/apply1",
                "job_min_salary": 120000,
                "job_max_salary": 160000,
                "job_posted_at_datetime_utc": "2026-03-05T00:00:00Z",
            }
        ]
    }


@pytest.fixture
def mock_remotive_response():
    return {
        "jobs": [
            {
                "title": "Backend Engineer",
                "company_name": "RemoteCo",
                "candidate_required_location": "Worldwide",
                "description": "Join our remote team as a backend engineer.",
                "url": "https://example.com/apply2",
                "publication_date": "2026-03-04",
            }
        ]
    }
