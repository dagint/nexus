import io
import pytest
from services.resume_parser import parse_resume


def test_parse_text():
    result = parse_resume(text="Senior Python Developer with 10 years experience")
    assert "Senior Python Developer" in result
    assert "10 years" in result


def test_parse_empty_text():
    result = parse_resume(text="")
    assert result == ""


def test_parse_none():
    result = parse_resume()
    assert result == ""


def test_parse_text_strips_whitespace():
    result = parse_resume(text="  hello world  ")
    assert result == "hello world"


def test_parse_bad_extension():
    class FakeFile:
        filename = "resume.txt"
        def read(self):
            return b"content"

    with pytest.raises(ValueError, match="Unsupported file type"):
        parse_resume(file=FakeFile())


def test_text_takes_priority_over_empty_file():
    result = parse_resume(text="My resume text")
    assert result == "My resume text"
