"""Parse LinkedIn PDF profile exports into structured resume data."""
import re
import logging

logger = logging.getLogger(__name__)


def parse_linkedin_pdf(file):
    """Parse a LinkedIn PDF export and return structured data."""
    try:
        import pdfplumber
    except ImportError:
        logger.error("pdfplumber not installed")
        return None

    text = ""
    try:
        with pdfplumber.open(file) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text()
                if page_text:
                    text += page_text + "\n"
    except Exception as e:
        logger.error("Failed to parse LinkedIn PDF: %s", e)
        return None

    if not text.strip():
        return None

    result = {
        "raw_text": text.strip(),
        "name": "",
        "headline": "",
        "experience": [],
        "education": [],
        "skills": [],
        "summary": "",
    }

    lines = text.strip().split("\n")

    for line in lines:
        if line.strip():
            result["name"] = line.strip()
            break

    current_section = None
    section_content = []

    section_headers = {
        "experience": re.compile(r"^experience$", re.IGNORECASE),
        "education": re.compile(r"^education$", re.IGNORECASE),
        "skills": re.compile(r"^skills$", re.IGNORECASE),
        "summary": re.compile(r"^(summary|about)$", re.IGNORECASE),
        "certifications": re.compile(r"^(certifications|licenses & certifications|licenses)$", re.IGNORECASE),
    }

    for line in lines[1:]:
        stripped = line.strip()
        if not stripped:
            continue

        matched_section = None
        for section_name, pattern in section_headers.items():
            if pattern.match(stripped):
                matched_section = section_name
                break

        if matched_section:
            if current_section and section_content:
                _save_section(result, current_section, section_content)
            current_section = matched_section
            section_content = []
        else:
            if current_section:
                section_content.append(stripped)
            elif not result["headline"]:
                result["headline"] = stripped

    if current_section and section_content:
        _save_section(result, current_section, section_content)

    # Flatten skills
    if isinstance(result["skills"], list) and result["skills"]:
        flat_skills = []
        for item in result["skills"]:
            parts = re.split(r"[,\u00b7\u2022\|]", item)
            for part in parts:
                skill = part.strip()
                if skill and len(skill) > 1:
                    flat_skills.append(skill)
        result["skills"] = flat_skills

    return result


def _save_section(result, section_name, content):
    if section_name == "summary":
        result["summary"] = " ".join(content)
    elif section_name == "skills":
        result["skills"] = content
    else:
        if section_name not in result:
            result[section_name] = []
        result[section_name] = content


def linkedin_to_resume_text(parsed):
    """Convert parsed LinkedIn data to a clean resume text string."""
    if not parsed:
        return ""

    parts = []
    if parsed.get("name"):
        parts.append(parsed["name"])
    if parsed.get("headline"):
        parts.append(parsed["headline"])
    if parsed.get("summary"):
        parts.append(f"\nSummary\n{parsed['summary']}")
    if parsed.get("experience"):
        parts.append("\nExperience")
        for item in parsed["experience"]:
            parts.append(f"  {item}")
    if parsed.get("education"):
        parts.append("\nEducation")
        for item in parsed["education"]:
            parts.append(f"  {item}")
    if parsed.get("skills"):
        parts.append("\nSkills")
        parts.append(", ".join(parsed["skills"]))
    return "\n".join(parts)
