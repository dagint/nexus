"""End-to-end / integration tests using the Flask test client."""

from unittest.mock import patch


# ---- helpers ----

def _register(client, email="user@test.com", password="password123", name="Test User"):
    """Register a user and return the response."""
    return client.post("/register", data={
        "email": email,
        "password": password,
        "name": name,
    }, follow_redirects=True)


def _login(client, email="user@test.com", password="password123"):
    """Log in a user and return the response."""
    return client.post("/login", data={
        "email": email,
        "password": password,
    }, follow_redirects=True)


def _make_sample_jobs():
    """Return a list of sample job dicts for mocking search_all."""
    return [
        {
            "title": "Python Developer",
            "company": "TechCo",
            "location": "Remote",
            "remote_status": "remote",
            "description": "Build Python apps with Django and AWS. 5+ years experience required.",
            "apply_url": "https://example.com/apply1",
            "salary_min": 120000,
            "salary_max": 160000,
            "posted_date": "2026-03-05",
            "source": "JSearch",
            "job_key": "job_py_001",
        },
        {
            "title": "Backend Engineer",
            "company": "StartupInc",
            "location": "New York, NY",
            "remote_status": "hybrid",
            "description": "Node.js and PostgreSQL backend work.",
            "apply_url": "https://example.com/apply2",
            "salary_min": 130000,
            "salary_max": 170000,
            "posted_date": "2026-03-04",
            "source": "Remotive",
            "job_key": "job_be_002",
        },
    ]


# ---- Tests ----


class TestHealthEndpoint:
    def test_health_returns_ok(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "ok"


class TestAuthFlow:
    def test_register_creates_account(self, client):
        resp = _register(client, email="new@example.com")
        assert resp.status_code == 200
        assert b"Account created" in resp.data

    def test_register_duplicate_email_fails(self, client):
        _register(client, email="dup@example.com")
        client.get("/logout")
        resp = _register(client, email="dup@example.com", password="otherpass123")
        assert b"already exists" in resp.data

    def test_login_with_valid_credentials(self, client):
        _register(client, email="login@example.com", password="password123")
        client.get("/logout")
        resp = _login(client, email="login@example.com", password="password123")
        assert resp.status_code == 200
        # After login we should be on the index page, not the login page
        assert b"Log In" not in resp.data or b"Log Out" in resp.data

    def test_login_with_invalid_credentials(self, client):
        _register(client, email="bad@example.com", password="password123")
        client.get("/logout")
        resp = _login(client, email="bad@example.com", password="wrongpassword")
        assert b"Invalid" in resp.data

    def test_logout(self, client):
        _register(client, email="out@example.com")
        resp = client.get("/logout", follow_redirects=True)
        assert resp.status_code == 200
        assert b"Logged out" in resp.data

    def test_protected_routes_redirect_to_login(self, client):
        protected = ["/dashboard", "/settings", "/bookmarks", "/pipeline",
                     "/alerts", "/resumes", "/history"]
        for route in protected:
            resp = client.get(route, follow_redirects=True)
            assert b"Log In" in resp.data, f"{route} did not redirect to login"


class TestSearchFlow:
    def test_search_page_loads(self, client):
        resp = client.get("/")
        assert resp.status_code == 200
        assert b"Find Your Next Role" in resp.data

    @patch("services.job_search.search_all")
    @patch("services.company_enricher.enrich_jobs", side_effect=lambda jobs: jobs)
    def test_search_with_text_resume(self, mock_enrich, mock_search, client, sample_resume_text):
        mock_search.return_value = _make_sample_jobs()
        resp = client.post("/search", data={
            "resume_text": sample_resume_text,
            "location": "Remote",
        }, follow_redirects=True)
        assert resp.status_code == 200
        mock_search.assert_called_once()

    @patch("services.job_search.search_all")
    @patch("services.company_enricher.enrich_jobs", side_effect=lambda jobs: jobs)
    def test_search_results_contain_job_cards(self, mock_enrich, mock_search, client, sample_resume_text):
        mock_search.return_value = _make_sample_jobs()
        resp = client.post("/search", data={
            "resume_text": sample_resume_text,
            "location": "Remote",
        }, follow_redirects=True)
        assert resp.status_code == 200
        assert b"Python Developer" in resp.data or b"results" in resp.data


class TestJobActions:
    def test_bookmark_job(self, client):
        _register(client)
        resp = client.post("/jobs/test_key_1/bookmark",
                           json={"title": "Dev", "company": "Co"},
                           content_type="application/json")
        assert resp.status_code == 200
        assert resp.get_json()["status"] == "ok"

    def test_mark_applied(self, client):
        _register(client)
        resp = client.post("/jobs/test_key_2/applied",
                           json={"title": "Dev", "company": "Co"},
                           content_type="application/json")
        assert resp.status_code == 200
        assert resp.get_json()["status"] == "ok"

    def test_dismiss_job(self, client):
        _register(client)
        resp = client.post("/jobs/test_key_3/dismiss",
                           json={"title": "Dev", "company": "Co"},
                           content_type="application/json")
        assert resp.status_code == 200
        assert resp.get_json()["status"] == "ok"


class TestDashboard:
    def test_dashboard_loads_for_authenticated_user(self, client):
        _register(client)
        resp = client.get("/dashboard")
        assert resp.status_code == 200
        assert b"Dashboard" in resp.data

    def test_dashboard_redirects_for_anonymous(self, client):
        resp = client.get("/dashboard", follow_redirects=True)
        assert b"Log In" in resp.data


class TestErrorPages:
    def test_404_page(self, client):
        resp = client.get("/this-page-does-not-exist")
        assert resp.status_code == 404
        assert b"Page Not Found" in resp.data
        assert b"404" in resp.data


class TestSettings:
    def test_settings_page_loads(self, client):
        _register(client)
        resp = client.get("/settings")
        assert resp.status_code == 200
        assert b"Settings" in resp.data

    def test_save_settings(self, client):
        _register(client)
        resp = client.post("/settings", data={
            "name": "Updated Name",
            "timezone": "US/Eastern",
            "max_commute_minutes": "45",
            "seniority_tier": "IC3",
            "blocked_companies": "BadCo",
        }, follow_redirects=True)
        assert resp.status_code == 200
        assert b"Settings saved" in resp.data


class TestAlerts:
    def test_create_alert(self, client):
        _register(client)
        resp = client.post("/alerts", data={
            "query": "Python Developer",
            "location": "Remote",
            "frequency": "daily",
        }, follow_redirects=True)
        assert resp.status_code == 200
        assert b"Alert created" in resp.data

    def test_delete_alert(self, client):
        _register(client)
        # Create an alert first
        client.post("/alerts", data={
            "query": "React Developer",
            "location": "",
            "frequency": "weekly",
        }, follow_redirects=True)
        # Delete it (alert id = 1 since it's a fresh db)
        resp = client.post("/alerts/1/delete", follow_redirects=True)
        assert resp.status_code == 200
        assert b"Alert deleted" in resp.data
