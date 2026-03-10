from services.skills_extractor import extract_keywords


def test_extract_skills(sample_resume_text):
    result = extract_keywords(sample_resume_text)
    assert "Python" in result["skills"]
    assert "JavaScript" in result["skills"]
    assert "React" in result["skills"]
    assert "AWS" in result["skills"]
    assert "Docker" in result["skills"]


def test_extract_job_titles(sample_resume_text):
    result = extract_keywords(sample_resume_text)
    assert "Software Engineer" in result["job_titles"]


def test_extract_experience_years(sample_resume_text):
    result = extract_keywords(sample_resume_text)
    assert result["experience_years"] == 8


def test_short_word_boundary():
    # "Go" should match as word boundary, not inside "Google"
    result = extract_keywords("I work with Go and C for systems programming")
    assert "Go" in result["skills"]
    assert "C" in result["skills"]


def test_short_word_no_false_positive():
    # "R" inside "React" should not match as the language R
    # unless R also appears separately
    result = extract_keywords("I use React for frontend development")
    assert "React" in result["skills"]


def test_no_skills():
    result = extract_keywords("I like cats and dogs")
    assert len(result["skills"]) == 0 or all(
        s not in ["Python", "JavaScript"] for s in result["skills"]
    )


def test_experience_patterns():
    texts = [
        ("10+ years of experience in software", 10),
        ("5 years of professional experience", 5),
        ("3 years in software development", 3),
    ]
    for text, expected in texts:
        result = extract_keywords(text)
        assert result["experience_years"] == expected, f"Failed for: {text}"
