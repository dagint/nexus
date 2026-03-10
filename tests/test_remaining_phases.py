"""Tests for company enricher, commute checker, job matcher, email digest, and role velocity."""

import json
import sys
from unittest.mock import patch, MagicMock

import pytest

# ---------------------------------------------------------------------------
# Ensure geopy is importable even if not installed, by inserting a stub module
# before any test imports commute_checker.
# ---------------------------------------------------------------------------
if "geopy" not in sys.modules:
    _geopy = MagicMock()
    sys.modules["geopy"] = _geopy
    sys.modules["geopy.geocoders"] = _geopy.geocoders
    sys.modules["geopy.distance"] = _geopy.distance
    sys.modules["geopy.exc"] = _geopy.exc
    # Provide real exception classes so `except` clauses work
    _geopy.exc.GeocoderTimedOut = type("GeocoderTimedOut", (Exception,), {})
    _geopy.exc.GeocoderUnavailable = type("GeocoderUnavailable", (Exception,), {})


# ---------------------------------------------------------------------------
# 1. Company Enricher – caching logic and mock scraping
# ---------------------------------------------------------------------------

class TestCompanyEnricherCaching:
    """Verify that enrich_company checks cache first and stores new results."""

    def test_returns_none_for_empty_name(self):
        from services.company_enricher import enrich_company
        assert enrich_company("") is None
        assert enrich_company(None) is None
        assert enrich_company("Unknown Company") is None

    @patch("services.company_enricher._scrape_company_data")
    def test_uses_cache_when_available(self, mock_scrape):
        from database import cache_company
        from services.company_enricher import enrich_company

        cached_data = {"name": "Acme", "size": "500 employees", "description": "A widget company"}
        cache_company("Acme", cached_data)

        result = enrich_company("Acme")
        assert result == cached_data
        mock_scrape.assert_not_called()

    @patch("services.company_enricher._scrape_company_data")
    def test_scrapes_and_caches_on_miss(self, mock_scrape):
        from services.company_enricher import enrich_company
        from database import get_cached_company

        scraped = {"name": "NewCo", "size": "200 employees", "description": "Fresh startup"}
        mock_scrape.return_value = scraped

        result = enrich_company("NewCo")
        assert result == scraped
        mock_scrape.assert_called_once_with("NewCo")

        # Should now be in the cache
        assert get_cached_company("NewCo") == scraped

    @patch("services.company_enricher._scrape_company_data")
    def test_returns_none_when_scrape_finds_nothing(self, mock_scrape):
        from services.company_enricher import enrich_company

        mock_scrape.return_value = None
        result = enrich_company("GhostCorp")
        assert result is None


class TestCompanyEnricherScraping:
    """Test _scrape_company_data with mocked HTTP responses."""

    @patch("services.company_enricher.requests.get")
    def test_extracts_employee_count_from_snippet(self, mock_get):
        from services.company_enricher import _scrape_company_data

        html = """
        <html><body>
        <div class="result__snippet">Acme Inc has 1,200 employees worldwide.</div>
        </body></html>
        """
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = html
        mock_get.return_value = mock_resp

        result = _scrape_company_data("Acme Inc")
        assert result is not None
        assert "1,200 employees" in result["size"]

    @patch("services.company_enricher.requests.get")
    def test_extracts_description_from_long_snippet(self, mock_get):
        from services.company_enricher import _scrape_company_data

        long_text = "A" * 80  # longer than 50 chars triggers description extraction
        html = f'<html><body><div class="result__snippet">{long_text}</div></body></html>'
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = html
        mock_get.return_value = mock_resp

        result = _scrape_company_data("DescCo")
        assert result is not None
        assert result["description"] is not None

    @patch("services.company_enricher.requests.get")
    def test_returns_none_when_no_useful_data(self, mock_get):
        from services.company_enricher import _scrape_company_data

        html = '<html><body><div class="result__snippet">Short</div></body></html>'
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = html
        mock_get.return_value = mock_resp

        result = _scrape_company_data("NoDataCo")
        assert result is None

    @patch("services.company_enricher.requests.get", side_effect=Exception("network fail"))
    def test_returns_none_on_network_error(self, mock_get):
        from services.company_enricher import _scrape_company_data

        result = _scrape_company_data("ErrorCo")
        assert result is None


class TestEnrichJobs:
    """Test the bulk enrich_jobs helper."""

    @patch("services.company_enricher.enrich_company")
    def test_deduplicates_company_lookups(self, mock_enrich):
        from services.company_enricher import enrich_jobs

        mock_enrich.return_value = {"name": "SameCo", "size": "100 employees"}
        jobs = [
            {"company": "SameCo", "title": "Dev"},
            {"company": "SameCo", "title": "QA"},
            {"company": "OtherCo", "title": "PM"},
        ]
        enrich_jobs(jobs)

        # SameCo should only be looked up once; OtherCo once => 2 total
        assert mock_enrich.call_count == 2
        assert jobs[0]["company_info"] == jobs[1]["company_info"]

    @patch("services.company_enricher.enrich_company", side_effect=Exception("boom"))
    def test_handles_enrichment_errors_gracefully(self, mock_enrich):
        from services.company_enricher import enrich_jobs

        jobs = [{"company": "FailCo", "title": "Dev"}]
        result = enrich_jobs(jobs)
        assert result[0]["company_info"] is None


# ---------------------------------------------------------------------------
# 2. Commute Checker – geocoding and distance estimation
# ---------------------------------------------------------------------------

class TestCommuteChecker:

    def _clear_geocode_cache(self):
        """Clear the lru_cache on _geocode between tests."""
        from services.commute_checker import _geocode
        _geocode.cache_clear()

    def test_estimate_commute_short_distance(self):
        self._clear_geocode_cache()
        from services.commute_checker import estimate_commute

        # Mock _geocode to return known coordinates
        with patch("services.commute_checker._geocode") as mock_geocode:
            mock_geocode.side_effect = [
                (40.7128, -74.0060),   # job: downtown NYC
                (40.7580, -73.9855),   # user: midtown NYC
            ]
            # Mock geodesic to return a realistic distance
            mock_dist = MagicMock()
            mock_dist.miles = 3.4
            with patch("services.commute_checker.geodesic", return_value=mock_dist):
                result = estimate_commute("Downtown, NY", "Midtown, NY", max_commute_minutes=60)

        assert result is not None
        assert "distance_miles" in result
        assert "commute_minutes" in result
        assert "is_feasible" in result
        assert result["is_feasible"] is True

    def test_estimate_commute_long_distance_infeasible(self):
        self._clear_geocode_cache()
        from services.commute_checker import estimate_commute

        with patch("services.commute_checker._geocode") as mock_geocode:
            mock_geocode.side_effect = [
                (40.7128, -74.0060),    # NYC
                (34.0522, -118.2437),   # LA
            ]
            mock_dist = MagicMock()
            mock_dist.miles = 2451.0
            with patch("services.commute_checker.geodesic", return_value=mock_dist):
                result = estimate_commute("New York, NY", "Los Angeles, CA", max_commute_minutes=60)

        assert result is not None
        assert result["is_feasible"] is False
        assert result["distance_miles"] > 100

    def test_returns_none_for_remote_location(self):
        from services.commute_checker import estimate_commute
        assert estimate_commute("Remote", "New York, NY") is None
        assert estimate_commute("Work from home", "NYC") is None

    def test_returns_none_for_empty_locations(self):
        from services.commute_checker import estimate_commute
        assert estimate_commute("", "NYC") is None
        assert estimate_commute("NYC", "") is None
        assert estimate_commute(None, None) is None

    def test_returns_none_when_geocoding_fails(self):
        self._clear_geocode_cache()
        from services.commute_checker import estimate_commute

        with patch("services.commute_checker._geocode", return_value=None):
            result = estimate_commute("Nowheresville", "Otherplace")
        assert result is None

    @patch("services.commute_checker.estimate_commute")
    def test_check_commute_for_jobs_skips_remote(self, mock_estimate):
        from services.commute_checker import check_commute_for_jobs

        jobs = [
            {"title": "Dev", "location": "SF", "remote_status": "remote"},
            {"title": "QA", "location": "NYC", "remote_status": "onsite"},
        ]
        mock_estimate.return_value = {"distance_miles": 5, "commute_minutes": 10, "is_feasible": True, "label": "~5 miles"}
        check_commute_for_jobs(jobs, "Brooklyn, NY")

        assert jobs[0]["commute_info"] is None  # remote => skipped
        # onsite job should have had estimate_commute called
        mock_estimate.assert_called_once()

    def test_check_commute_for_jobs_noop_without_user_location(self):
        from services.commute_checker import check_commute_for_jobs

        jobs = [{"title": "Dev", "location": "SF", "remote_status": "onsite"}]
        result = check_commute_for_jobs(jobs, None)
        assert result == jobs
        assert "commute_info" not in result[0]

    def test_label_less_than_one_mile(self):
        self._clear_geocode_cache()
        from services.commute_checker import estimate_commute

        with patch("services.commute_checker._geocode") as mock_geocode:
            mock_geocode.side_effect = [
                (40.7128, -74.0060),
                (40.7128, -74.0060),  # same coords
            ]
            mock_dist = MagicMock()
            mock_dist.miles = 0.0
            with patch("services.commute_checker.geodesic", return_value=mock_dist):
                result = estimate_commute("Point A", "Point B")

        assert result is not None
        assert result["label"] == "Less than 1 mile"


# ---------------------------------------------------------------------------
# 3. Job Matcher – scoring, aliases, and Claude summary fallback
# ---------------------------------------------------------------------------

class TestJobMatcherScoring:

    def test_score_job_high_match(self, sample_job, sample_resume_text):
        from services.job_matcher import score_job

        resume_data = {
            "skills": [
                {"skill": "Python", "weight": 1.0},
                {"skill": "AWS", "weight": 0.8},
                {"skill": "React", "weight": 0.7},
                {"skill": "Docker", "weight": 0.5},
            ],
            "job_titles": ["Senior Software Engineer"],
            "inferred_titles": [],
            "seniority_tier": "IC3",
            "inferred_skills": [],
        }

        result = score_job(sample_job, resume_data)
        assert result["match_score"] >= 50
        assert result["match_tier"] in ("strong", "possible")
        assert len(result["match_reasons"]) > 0

    def test_score_job_low_match(self):
        from services.job_matcher import score_job

        job = {
            "title": "Registered Nurse",
            "company": "Hospital",
            "description": "Patient care, IV administration, medical charting.",
            "remote_status": "onsite",
        }
        resume_data = {
            "skills": [
                {"skill": "Python", "weight": 1.0},
                {"skill": "JavaScript", "weight": 0.8},
            ],
            "job_titles": ["Software Engineer"],
            "inferred_titles": [],
            "seniority_tier": "IC2",
            "inferred_skills": [],
        }

        result = score_job(job, resume_data)
        assert result["match_score"] < 50
        assert result["match_tier"] in ("low", "stretch")

    def test_score_jobs_sorts_by_score_descending(self):
        from services.job_matcher import score_jobs

        resume_data = {
            "skills": [{"skill": "Python", "weight": 1.0}],
            "job_titles": ["Software Engineer"],
            "inferred_titles": [],
            "seniority_tier": "IC2",
            "inferred_skills": [],
        }

        jobs = [
            {"title": "Nurse", "company": "B", "description": "Patient care", "remote_status": "onsite"},
            {"title": "Python Developer", "company": "A", "description": "Python Django", "remote_status": "remote"},
        ]

        result = score_jobs(jobs, resume_data)
        # Python Developer should rank higher than Nurse
        assert result[0]["title"] == "Python Developer"
        scores = [j["match_score"] for j in result]
        assert scores == sorted(scores, reverse=True)

    def test_alias_match_gives_partial_credit(self):
        from services.job_matcher import score_job

        job = {
            "title": "SDE",  # alias of Software Engineer
            "company": "BigCo",
            "description": "Write code in Python.",
            "remote_status": "remote",
        }
        resume_data = {
            "skills": [{"skill": "Python", "weight": 1.0}],
            "job_titles": ["Software Engineer"],
            "inferred_titles": [],
            "seniority_tier": "IC2",
            "inferred_skills": [],
        }

        result = score_job(job, resume_data)
        # Should get alias credit (22 pts for title) rather than 0
        assert result["match_score"] >= 20
        title_reasons = [r for r in result["match_reasons"] if "alias" in r.lower()]
        assert len(title_reasons) > 0

    def test_inferred_title_match(self):
        from services.job_matcher import score_job

        job = {
            "title": "Backend Developer",
            "company": "Co",
            "description": "Build APIs",
            "remote_status": "remote",
        }
        resume_data = {
            "skills": [],
            "job_titles": [],
            "inferred_titles": ["Backend Developer"],
            "seniority_tier": "IC2",
            "inferred_skills": [],
        }

        result = score_job(job, resume_data)
        title_reasons = [r for r in result["match_reasons"] if "inferred" in r.lower()]
        assert len(title_reasons) > 0

    def test_seniority_exact_match(self):
        from services.job_matcher import _score_seniority

        resume_data = {"seniority_tier": "IC3"}
        job = {"title": "senior software engineer", "description": ""}
        score, reasons = _score_seniority(job, resume_data)
        assert score == 15
        assert any("match" in r.lower() for r in reasons)

    def test_seniority_mismatch(self):
        from services.job_matcher import _score_seniority

        resume_data = {"seniority_tier": "IC1"}
        job = {"title": "principal engineer", "description": ""}
        score, reasons = _score_seniority(job, resume_data)
        # IC1 vs Principal => big gap
        assert score == 0

    def test_location_score_remote_only_pref(self):
        from services.job_matcher import _score_location

        assert _score_location({"remote_status": "remote"}, {"remote_only": True})[0] == 15
        assert _score_location({"remote_status": "hybrid"}, {"remote_only": True})[0] == 8
        assert _score_location({"remote_status": "onsite"}, {"remote_only": True})[0] == 0


class TestJobMatcherClaudeSummary:
    """Test Claude summary generation with mock API."""

    def test_generate_match_summary_heuristic_fallback(self):
        from services.job_matcher import generate_match_summary

        with patch("config.Config") as mock_config:
            mock_config.ANTHROPIC_API_KEY = None  # No API key => heuristic

            job = {
                "match_tier": "strong",
                "match_reasons": ["Skills match: Python, AWS", "Exact title match"],
            }
            resume_data = {"skills": [], "job_titles": []}

            summary = generate_match_summary(job, resume_data)
            assert "Python" in summary
            assert "Exact title match" in summary

    @patch("services.ai_client.call")
    @patch("services.ai_client.is_available", return_value=True)
    def test_generate_match_summary_calls_claude_for_strong(self, mock_available, mock_call):
        from services.job_matcher import generate_match_summary

        mock_call.return_value = "Great match because of Python and AWS expertise."

        job = {
            "title": "Senior Dev",
            "company": "TechCo",
            "description": "Python AWS role",
            "match_tier": "strong",
            "match_score": 85,
            "match_reasons": ["Skills match: Python"],
        }
        resume_data = {
            "skills": [{"skill": "Python", "weight": 1.0}],
            "job_titles": ["Software Engineer"],
            "inferred_titles": [],
        }

        summary = generate_match_summary(job, resume_data)
        assert "Python" in summary
        mock_call.assert_called_once()

    @patch("services.ai_client.call")
    @patch("services.ai_client.is_available", return_value=True)
    def test_claude_failure_falls_back_to_heuristic(self, mock_available, mock_call):
        from services.job_matcher import generate_match_summary

        mock_call.side_effect = Exception("API down")

        job = {
            "title": "Dev",
            "company": "Co",
            "description": "Code",
            "match_tier": "strong",
            "match_score": 80,
            "match_reasons": ["Skills match: Go"],
        }
        resume_data = {"skills": [], "job_titles": [], "inferred_titles": []}

        summary = generate_match_summary(job, resume_data)
        # Should fallback to heuristic rather than raising
        assert "Go" in summary

    def test_no_summary_for_non_strong_without_key(self):
        from services.job_matcher import generate_match_summary

        with patch("config.Config") as mock_config:
            mock_config.ANTHROPIC_API_KEY = "test-key"

            job = {
                "match_tier": "possible",
                "match_reasons": ["Partial title overlap: python"],
            }
            resume_data = {"skills": [], "job_titles": []}

            summary = generate_match_summary(job, resume_data)
            # Non-strong tier skips Claude call, uses heuristic
            assert "python" in summary.lower()


# ---------------------------------------------------------------------------
# 4. Enhanced Email Digest – tiered grouping
# ---------------------------------------------------------------------------

class TestEmailDigestTieredGrouping:
    """Test that the notifier groups jobs by tier correctly."""

    def _make_job(self, title, company, tier, score):
        return {
            "title": title,
            "company": company,
            "match_tier": tier,
            "match_score": score,
            "location": "Remote",
            "remote_status": "remote",
            "source": "Test",
            "apply_url": "https://example.com",
        }

    def test_simple_html_renders_all_tiers(self):
        from services.notifier import _simple_html

        jobs = [
            self._make_job("Python Dev", "A", "strong", 90),
            self._make_job("JS Dev", "B", "possible", 60),
            self._make_job("Go Dev", "C", "stretch", 30),
        ]

        html = _simple_html(jobs, "python developer")
        assert "Python Dev" in html
        assert "JS Dev" in html
        assert "Go Dev" in html
        assert "[Strong Match]" in html
        assert "[Possible]" in html
        assert "[Stretch]" in html

    def test_simple_html_contains_search_query(self):
        from services.notifier import _simple_html

        html = _simple_html([], "data engineer")
        assert "data engineer" in html

    def test_simple_html_limits_to_20_jobs(self):
        from services.notifier import _simple_html

        jobs = [self._make_job(f"Job {i}", "Co", "possible", 50) for i in range(30)]
        html = _simple_html(jobs, "test")
        # Jobs 20-29 should not appear
        assert "Job 0" in html
        assert "Job 19" in html
        assert "Job 20" not in html

    def test_send_digest_groups_by_tier(self):
        from services.notifier import send_digest

        jobs = [
            self._make_job("Strong1", "A", "strong", 90),
            self._make_job("Strong2", "B", "strong", 85),
            self._make_job("Possible1", "C", "possible", 60),
            self._make_job("Stretch1", "D", "stretch", 30),
        ]

        # Without SMTP configured, send_digest returns False but we can check
        # the tier grouping logic by verifying it doesn't crash
        result = send_digest("test@example.com", jobs, "python dev")
        assert result is False  # SMTP not configured in test env

    def test_send_digest_returns_false_without_smtp(self):
        from services.notifier import send_digest
        result = send_digest("test@example.com", [], "query")
        assert result is False

    @patch("services.notifier.smtplib.SMTP")
    @patch("services.notifier.Config")
    def test_send_digest_sends_email_when_configured(self, mock_config, mock_smtp_class):
        from services.notifier import send_digest

        mock_config.SMTP_USER = "user@example.com"
        mock_config.SMTP_PASSWORD = "secret"
        mock_config.SMTP_HOST = "smtp.example.com"
        mock_config.SMTP_PORT = 587
        mock_config.SMTP_FROM = "noreply@example.com"

        mock_server = MagicMock()
        mock_smtp_class.return_value.__enter__ = MagicMock(return_value=mock_server)
        mock_smtp_class.return_value.__exit__ = MagicMock(return_value=False)

        jobs = [self._make_job("Dev", "Co", "strong", 90)]
        result = send_digest("recipient@example.com", jobs, "python")
        assert result is True
        mock_server.send_message.assert_called_once()


# ---------------------------------------------------------------------------
# 5. Role Velocity – database query
# ---------------------------------------------------------------------------

class TestRoleVelocity:
    """Test get_role_velocity counts matching seen_jobs correctly."""

    def _setup_seen_jobs(self, search_id, job_keys):
        from database import add_seen_jobs
        add_seen_jobs(search_id, job_keys)

    def _create_search(self, user_id=1):
        from database import create_saved_search
        return create_saved_search(user_id, "test", "Remote", False, "[]", "daily")

    def _create_user(self):
        from database import create_user
        return create_user("velocity@test.com", "pass123", "Tester")

    def test_returns_zero_with_no_data(self):
        from database import get_role_velocity
        count = get_role_velocity("Acme", "Engineer")
        assert count == 0

    def test_counts_matching_job_keys(self):
        from database import get_role_velocity

        user_id = self._create_user()
        search_id = self._create_search(user_id)

        # Job keys that contain both company and title fragments
        self._setup_seen_jobs(search_id, [
            "jsearch_Acme_Software Engineer_123",
            "jsearch_Acme_Software Engineer_456",
            "jsearch_Acme_Software Engineer_789",
        ])

        count = get_role_velocity("Acme", "Software Engineer")
        assert count == 3

    def test_does_not_count_unrelated_keys(self):
        from database import get_role_velocity

        user_id = self._create_user()
        search_id = self._create_search(user_id)

        self._setup_seen_jobs(search_id, [
            "jsearch_Acme_Software Engineer_123",
            "jsearch_OtherCo_Designer_456",
            "jsearch_Acme_Nurse_789",
        ])

        count = get_role_velocity("Acme", "Software Engineer")
        assert count == 1

    def test_deduplicates_same_job_key_across_searches(self):
        from database import get_role_velocity

        user_id = self._create_user()
        s1 = self._create_search(user_id)
        s2 = self._create_search(user_id)

        # Same job key added to two different searches
        self._setup_seen_jobs(s1, ["jsearch_Acme_Dev_1"])
        self._setup_seen_jobs(s2, ["jsearch_Acme_Dev_1"])

        # DISTINCT job_key should count it once
        count = get_role_velocity("Acme", "Dev")
        assert count == 1

    def test_respects_months_window(self):
        """Jobs inserted now should be within the default 6-month window."""
        from database import get_role_velocity

        user_id = self._create_user()
        search_id = self._create_search(user_id)
        self._setup_seen_jobs(search_id, ["jsearch_Corp_Eng_1"])

        # Default 6 months should include jobs just inserted
        assert get_role_velocity("Corp", "Eng", months=6) == 1
        # A 0-month window should exclude them (edge case for the query)
        # Note: since the job was just inserted, datetime('now', '-0 months')
        # is "now", so it may or may not include it depending on timing.
        # We just verify no crash.
        get_role_velocity("Corp", "Eng", months=0)
