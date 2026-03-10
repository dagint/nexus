from services.job_analyzer import analyze_job


def test_remote_detection(sample_job):
    result = analyze_job(sample_job)
    assert result["remote_status"] == "remote"


def test_hybrid_detection():
    job = {
        "title": "Engineer",
        "description": "This is a hybrid role, 2-3 days in office required.",
        "remote_status": "unknown",
    }
    result = analyze_job(job)
    assert result["remote_status"] == "hybrid"


def test_travel_percentage(sample_job):
    result = analyze_job(sample_job)
    assert result["travel_info"] == "10% travel"


def test_travel_required():
    job = {
        "title": "Consultant",
        "description": "Travel is required for client meetings. Domestic travel expected.",
        "remote_status": "onsite",
    }
    result = analyze_job(job)
    assert result["travel_info"] is not None


def test_no_travel():
    job = {
        "title": "Developer",
        "description": "Work from your desk writing code all day.",
        "remote_status": "remote",
    }
    result = analyze_job(job)
    assert result["travel_info"] is None


def test_timezone_detection():
    job = {
        "title": "Engineer",
        "description": "Must be available during EST business hours.",
        "remote_status": "remote",
    }
    result = analyze_job(job)
    assert result["timezone_req"] is not None
    assert "est" in result["timezone_req"].lower()


def test_easy_apply():
    job = {
        "title": "Developer",
        "description": "Easy Apply available. Click to apply now.",
        "remote_status": "remote",
    }
    result = analyze_job(job)
    assert result["easy_apply"] is True


def test_fully_remote_granular(sample_job):
    result = analyze_job(sample_job)
    assert result["remote_detail"] in ["fully_remote", "remote_quarterly_onsite", None]


def test_onsite_default():
    job = {
        "title": "Developer",
        "description": "Join our team in the downtown office.",
        "remote_status": "unknown",
    }
    result = analyze_job(job)
    assert result["remote_status"] == "onsite"
