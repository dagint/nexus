from unittest.mock import patch, MagicMock
from services.job_search import _deduplicate
from services.apis.base import JobAPIProvider
from services.apis.jsearch import JSearchProvider
from services.apis.remotive import RemotiveProvider


def test_normalize_job():
    class TestProvider(JobAPIProvider):
        name = "TestSource"
        def is_available(self):
            return True
        def search(self, *args):
            return []

    provider = TestProvider()
    raw = {
        "title": "Engineer",
        "company": "Corp",
        "location": "NYC",
        "remote_status": "remote",
        "description": "Build stuff",
        "apply_url": "https://example.com",
        "salary_min": 100000,
        "salary_max": 150000,
        "posted_date": "2026-03-01",
    }
    result = provider.normalize(raw)
    assert result["title"] == "Engineer"
    assert result["company"] == "Corp"
    assert result["source"] == "TestSource"
    assert result["job_key"]


def test_deduplicate_exact():
    jobs = [
        {"title": "Python Dev", "company": "Acme", "description": "Short", "source": "A"},
        {"title": "Python Dev", "company": "Acme", "description": "Much longer description here", "source": "B"},
    ]
    result = _deduplicate(jobs)
    assert len(result) == 1
    assert result[0]["description"] == "Much longer description here"


def test_deduplicate_different():
    jobs = [
        {"title": "Python Dev", "company": "Acme", "description": "x", "source": "A"},
        {"title": "Java Dev", "company": "Corp", "description": "y", "source": "B"},
    ]
    result = _deduplicate(jobs)
    assert len(result) == 2


@patch("services.apis.jsearch.requests.get")
def test_jsearch_parsing(mock_get, mock_jsearch_response):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = mock_jsearch_response
    mock_get.return_value = mock_resp

    with patch("services.apis.jsearch.Config") as mock_config:
        mock_config.RAPIDAPI_KEY = "test-key"
        provider = JSearchProvider()
        results = provider.search("python", "new york", False, "month", 1)

    assert len(results) == 1
    assert results[0]["title"] == "Python Developer"
    assert results[0]["company"] == "TechCo"
    assert results[0]["source"] == "JSearch"


@patch("services.apis.remotive.requests.get")
def test_remotive_parsing(mock_get, mock_remotive_response):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = mock_remotive_response
    mock_get.return_value = mock_resp

    provider = RemotiveProvider()
    results = provider.search("backend", "", False, "month", 1)
    assert len(results) == 1
    assert results[0]["title"] == "Backend Engineer"
    assert results[0]["remote_status"] == "remote"
