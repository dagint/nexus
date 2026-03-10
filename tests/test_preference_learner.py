"""Tests for the preference learning system."""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class TestBuildPreferenceProfile:
    """Tests for build_preference_profile()."""

    def test_empty_profile_no_data(self, fresh_db):
        """With no bookmarks/applied/dismissed jobs, returns empty dict."""
        from database import create_user
        from services.preference_learner import build_preference_profile

        user_id = create_user("pref@test.com", "testpass123", "Pref User")
        profile = build_preference_profile(user_id)
        assert profile == {}

    def test_profile_from_bookmarked_jobs(self, fresh_db):
        """Builds profile from bookmarked jobs."""
        from database import create_user, bookmark_job
        from services.preference_learner import build_preference_profile

        user_id = create_user("pref2@test.com", "testpass123", "Pref User")

        bookmark_job(user_id, {
            "job_key": "bk1",
            "title": "Senior Software Engineer",
            "company": "TechCorp",
            "location": "Remote",
            "apply_url": "https://example.com/1",
            "salary_min": 150000,
            "salary_max": 200000,
            "remote_status": "remote",
            "source": "JSearch",
            "description": "Python, AWS, React, Docker development",
            "match_score": 85,
        })

        bookmark_job(user_id, {
            "job_key": "bk2",
            "title": "Backend Software Engineer",
            "company": "DataInc",
            "location": "New York",
            "apply_url": "https://example.com/2",
            "salary_min": 140000,
            "salary_max": 180000,
            "remote_status": "remote",
            "source": "JSearch",
            "description": "Python, PostgreSQL, AWS, Kubernetes microservices",
            "match_score": 78,
        })

        profile = build_preference_profile(user_id)

        assert profile != {}
        assert len(profile["preferred_skills"]) > 0
        # Python and AWS should appear in both jobs
        skill_names = [s for s, _ in profile["preferred_skills"]]
        assert "Python" in skill_names
        assert "AWS" in skill_names

        assert "TechCorp" in profile["preferred_companies"]
        assert "DataInc" in profile["preferred_companies"]

        # Both are remote
        assert profile["preferred_remote"] == 1.0

        # Salary range
        assert profile["salary_range"]["min"] == 140000
        assert profile["salary_range"]["max"] == 200000

        # Title keywords
        assert "software" in profile["preferred_titles"]
        assert "engineer" in profile["preferred_titles"]

    def test_profile_from_applied_jobs(self, fresh_db):
        """Builds profile from applied jobs."""
        from database import create_user, mark_applied
        from services.preference_learner import build_preference_profile

        user_id = create_user("pref3@test.com", "testpass123", "Pref User")

        mark_applied(user_id, "ap1", "Frontend Developer", "WebCo", location="SF", apply_url="https://example.com")
        mark_applied(user_id, "ap2", "Full Stack Developer", "AppCo", location="NYC", apply_url="https://example.com")

        profile = build_preference_profile(user_id)

        assert "WebCo" in profile["preferred_companies"]
        assert "AppCo" in profile["preferred_companies"]
        assert "developer" in profile["preferred_titles"]

    def test_profile_combines_bookmarks_and_applied(self, fresh_db):
        """Profile combines data from both bookmarked and applied jobs."""
        from database import create_user, bookmark_job, mark_applied
        from services.preference_learner import build_preference_profile

        user_id = create_user("pref4@test.com", "testpass123", "Pref User")

        bookmark_job(user_id, {
            "job_key": "bk1",
            "title": "Data Engineer",
            "company": "DataCorp",
            "description": "Python, Spark, AWS",
            "remote_status": "remote",
        })

        mark_applied(user_id, "ap1", "Data Scientist", "MLCo")

        profile = build_preference_profile(user_id)

        assert "DataCorp" in profile["preferred_companies"]
        assert "MLCo" in profile["preferred_companies"]

    def test_dismissed_jobs_negative_signals(self, fresh_db):
        """Dismissed jobs create negative signals in profile."""
        from database import create_user, bookmark_job, dismiss_job
        from services.preference_learner import build_preference_profile

        user_id = create_user("pref5@test.com", "testpass123", "Pref User")

        # Bookmark a good job
        bookmark_job(user_id, {
            "job_key": "bk1",
            "title": "Software Engineer",
            "company": "GoodCo",
            "description": "Python, React",
            "remote_status": "remote",
        })

        # Dismiss some bad jobs
        dismiss_job(user_id, "d1", "Sales Representative", "BadCorp")
        dismiss_job(user_id, "d2", "Sales Manager", "WorseInc")

        profile = build_preference_profile(user_id)

        assert "BadCorp" in profile["avoided_companies"]
        assert "WorseInc" in profile["avoided_companies"]
        assert profile["avoided_title_keywords"]["sales"] == 2

    def test_remote_preference_ratio(self, fresh_db):
        """Remote preference reflects actual ratio of remote vs onsite jobs."""
        from database import create_user, bookmark_job
        from services.preference_learner import build_preference_profile

        user_id = create_user("pref6@test.com", "testpass123", "Pref User")

        # 2 remote, 1 onsite, 1 hybrid = 2/4 = 0.5
        for i, status in enumerate(["remote", "remote", "onsite", "hybrid"]):
            bookmark_job(user_id, {
                "job_key": f"r{i}",
                "title": "Engineer",
                "company": f"Co{i}",
                "description": "coding",
                "remote_status": status,
            })

        profile = build_preference_profile(user_id)
        assert profile["preferred_remote"] == 0.5


class TestComputePreferenceBoost:
    """Tests for compute_preference_boost()."""

    def test_empty_profile_returns_zero(self):
        """Empty profile gives no boost."""
        from services.preference_learner import compute_preference_boost

        job = {"title": "Software Engineer", "company": "TestCo", "description": "Python"}
        points, reasons = compute_preference_boost(job, {})
        assert points == 0
        assert reasons == []

    def test_none_profile_returns_zero(self):
        """None profile gives no boost."""
        from services.preference_learner import compute_preference_boost

        job = {"title": "Software Engineer", "company": "TestCo", "description": "Python"}
        points, reasons = compute_preference_boost(job, None)
        assert points == 0
        assert reasons == []

    def test_skill_boost(self):
        """Jobs with preferred skills get +3."""
        from collections import Counter
        from services.preference_learner import compute_preference_boost

        profile = {
            "preferred_skills": [("Python", 5), ("AWS", 3), ("React", 2)],
            "title_keywords": Counter(),
            "preferred_titles": [],
            "preferred_companies": set(),
            "preferred_remote": 0.5,
            "salary_range": {},
            "avoided_companies": set(),
            "avoided_title_keywords": Counter(),
        }

        job = {"title": "Backend Developer", "company": "NewCo", "description": "Python and AWS services"}
        points, reasons = compute_preference_boost(job, profile)
        assert points >= 3
        assert any("Preferred skills" in r for r in reasons)

    def test_title_keyword_boost(self):
        """Jobs with matching title keywords get +3."""
        from collections import Counter
        from services.preference_learner import compute_preference_boost

        profile = {
            "preferred_skills": [],
            "title_keywords": Counter({"software": 4, "engineer": 4, "senior": 3}),
            "preferred_titles": ["software", "engineer", "senior"],
            "preferred_companies": set(),
            "preferred_remote": 0.5,
            "salary_range": {},
            "avoided_companies": set(),
            "avoided_title_keywords": Counter(),
        }

        job = {"title": "Senior Software Engineer", "company": "NewCo", "description": "Building things"}
        points, reasons = compute_preference_boost(job, profile)
        assert points >= 3
        assert any("Similar role" in r for r in reasons)

    def test_company_boost(self):
        """Jobs from previously saved companies get +3."""
        from collections import Counter
        from services.preference_learner import compute_preference_boost

        profile = {
            "preferred_skills": [],
            "title_keywords": Counter(),
            "preferred_titles": [],
            "preferred_companies": {"Google", "Meta", "Apple"},
            "preferred_remote": 0.5,
            "salary_range": {},
            "avoided_companies": set(),
            "avoided_title_keywords": Counter(),
        }

        job = {"title": "Engineer", "company": "Google", "description": "Coding"}
        points, reasons = compute_preference_boost(job, profile)
        assert points >= 3
        assert any("Previously saved company" in r for r in reasons)

    def test_remote_boost(self):
        """Remote jobs get +3 when user prefers remote (>= 0.7)."""
        from collections import Counter
        from services.preference_learner import compute_preference_boost

        profile = {
            "preferred_skills": [],
            "title_keywords": Counter(),
            "preferred_titles": [],
            "preferred_companies": set(),
            "preferred_remote": 0.9,
            "salary_range": {},
            "avoided_companies": set(),
            "avoided_title_keywords": Counter(),
        }

        job = {"title": "Engineer", "company": "Co", "description": "Coding", "remote_status": "remote"}
        points, reasons = compute_preference_boost(job, profile)
        assert points >= 3
        assert any("remote preference" in r.lower() for r in reasons)

    def test_salary_boost(self):
        """Jobs in preferred salary range get +3."""
        from collections import Counter
        from services.preference_learner import compute_preference_boost

        profile = {
            "preferred_skills": [],
            "title_keywords": Counter(),
            "preferred_titles": [],
            "preferred_companies": set(),
            "preferred_remote": 0.5,
            "salary_range": {"min": 120000, "max": 200000},
            "avoided_companies": set(),
            "avoided_title_keywords": Counter(),
        }

        job = {"title": "Engineer", "company": "Co", "description": "Coding",
               "salary_min": 150000, "salary_max": 180000}
        points, reasons = compute_preference_boost(job, profile)
        assert points >= 3
        assert any("Salary" in r for r in reasons)

    def test_boost_capped_at_15(self):
        """Total boost cannot exceed 15 points."""
        from collections import Counter
        from services.preference_learner import compute_preference_boost

        # Profile that would trigger all 5 bonuses = 15 points
        profile = {
            "preferred_skills": [("Python", 5), ("AWS", 3)],
            "title_keywords": Counter({"software": 4, "engineer": 4}),
            "preferred_titles": ["software", "engineer"],
            "preferred_companies": {"GreatCo"},
            "preferred_remote": 0.9,
            "salary_range": {"min": 100000, "max": 200000},
            "avoided_companies": set(),
            "avoided_title_keywords": Counter(),
        }

        job = {
            "title": "Software Engineer",
            "company": "GreatCo",
            "description": "Python and AWS development",
            "remote_status": "remote",
            "salary_min": 150000,
            "salary_max": 180000,
        }
        points, reasons = compute_preference_boost(job, profile)
        assert points <= 15

    def test_dismissed_company_penalty(self):
        """Jobs from dismissed companies get -5 penalty."""
        from collections import Counter
        from services.preference_learner import compute_preference_boost

        profile = {
            "preferred_skills": [],
            "title_keywords": Counter(),
            "preferred_titles": [],
            "preferred_companies": set(),
            "preferred_remote": 0.5,
            "salary_range": {},
            "avoided_companies": {"BadCorp", "WorseInc"},
            "avoided_title_keywords": Counter(),
        }

        job = {"title": "Engineer", "company": "BadCorp", "description": "Coding"}
        points, reasons = compute_preference_boost(job, profile)
        assert points < 0
        assert any("dismissed company" in r.lower() for r in reasons)

    def test_dismissed_title_penalty(self):
        """Jobs with titles similar to dismissed jobs get -5 penalty."""
        from collections import Counter
        from services.preference_learner import compute_preference_boost

        profile = {
            "preferred_skills": [],
            "title_keywords": Counter(),
            "preferred_titles": [],
            "preferred_companies": set(),
            "preferred_remote": 0.5,
            "salary_range": {},
            "avoided_companies": set(),
            "avoided_title_keywords": Counter({"sales": 3, "representative": 2}),
        }

        job = {"title": "Sales Representative", "company": "NewCo", "description": "Sell things"}
        points, reasons = compute_preference_boost(job, profile)
        assert points < 0
        assert any("dismissed" in r.lower() for r in reasons)

    def test_penalty_applied_with_positive_boosts(self):
        """Penalty stacks with positive boosts correctly."""
        from collections import Counter
        from services.preference_learner import compute_preference_boost

        profile = {
            "preferred_skills": [("Python", 5)],
            "title_keywords": Counter(),
            "preferred_titles": [],
            "preferred_companies": set(),
            "preferred_remote": 0.5,
            "salary_range": {},
            "avoided_companies": {"BadCorp"},
            "avoided_title_keywords": Counter(),
        }

        # Job has preferred skill (+3) but is from avoided company (-5)
        job = {"title": "Engineer", "company": "BadCorp", "description": "Python development"}
        points, reasons = compute_preference_boost(job, profile)
        assert points == -2  # 3 - 5 = -2


class TestIntegrationWithScorer:
    """Test preference profile integration with job_matcher scoring."""

    def test_preference_boost_increases_score(self, fresh_db):
        """Preference profile boosts scores in score_job."""
        from collections import Counter
        from services.job_matcher import score_job

        resume_data = {
            "skills": [{"skill": "Python", "weight": 0.8}, {"skill": "AWS", "weight": 0.6}],
            "job_titles": ["Data Analyst"],
            "seniority_tier": "IC2",
        }

        job_base = {
            "title": "Backend Developer",
            "company": "TestCo",
            "description": "Python and AWS development for microservices",
            "remote_status": "hybrid",
            "salary_min": 150000,
            "salary_max": 200000,
            "job_key": "int1",
        }

        # Score without preference
        import copy
        job_no_pref = copy.deepcopy(job_base)
        score_job(job_no_pref, resume_data)
        score_without = job_no_pref["match_score"]

        # Score with preference that matches
        job_with_pref = copy.deepcopy(job_base)
        profile = {
            "preferred_skills": [("Python", 5), ("AWS", 3)],
            "title_keywords": Counter({"software": 4, "engineer": 4}),
            "preferred_titles": ["software", "engineer"],
            "preferred_companies": set(),
            "preferred_remote": 0.9,
            "salary_range": {"min": 120000, "max": 200000},
            "avoided_companies": set(),
            "avoided_title_keywords": Counter(),
        }
        score_job(job_with_pref, resume_data, preference_profile=profile)
        score_with = job_with_pref["match_score"]

        assert score_with > score_without

    def test_score_capped_at_100(self, fresh_db):
        """Score never exceeds 100 even with preference boost."""
        from collections import Counter
        from services.job_matcher import score_job

        resume_data = {
            "skills": [{"skill": "Python", "weight": 0.9}, {"skill": "AWS", "weight": 0.8},
                        {"skill": "React", "weight": 0.7}],
            "job_titles": ["Senior Software Engineer"],
            "seniority_tier": "IC3",
        }

        job = {
            "title": "Senior Software Engineer",
            "company": "FavCo",
            "description": "Python, AWS, React development. 5+ years experience required.",
            "remote_status": "remote",
            "salary_min": 150000,
            "salary_max": 200000,
            "job_key": "cap1",
        }

        profile = {
            "preferred_skills": [("Python", 10), ("AWS", 8), ("React", 6)],
            "title_keywords": Counter({"senior": 5, "software": 5, "engineer": 5}),
            "preferred_titles": ["senior", "software", "engineer"],
            "preferred_companies": {"FavCo"},
            "preferred_remote": 1.0,
            "salary_range": {"min": 100000, "max": 250000},
            "avoided_companies": set(),
            "avoided_title_keywords": Counter(),
        }

        score_job(job, resume_data, preference_profile=profile)
        assert job["match_score"] <= 100
