import json
import logging
import os
import re

logger = logging.getLogger(__name__)

_skills_data = None


def _load_skills():
    global _skills_data
    if _skills_data is None:
        path = os.path.join(os.path.dirname(__file__), "..", "data", "skills.json")
        with open(path) as f:
            _skills_data = json.load(f)
    return _skills_data


def extract_keywords(text):
    """Heuristic keyword extraction from resume text."""
    skills_db = _load_skills()
    text_lower = text.lower()

    found_skills = []
    found_titles = []

    for category, terms in skills_db.items():
        for term in terms:
            if len(term) <= 3:
                # Short terms need word boundary matching
                pattern = r"\b" + re.escape(term) + r"\b"
                if re.search(pattern, text, re.IGNORECASE):
                    if category == "job_titles":
                        found_titles.append(term)
                    else:
                        found_skills.append(term)
            else:
                if term.lower() in text_lower:
                    if category == "job_titles":
                        found_titles.append(term)
                    else:
                        found_skills.append(term)

    # Deduplicate preserving order
    found_skills = list(dict.fromkeys(found_skills))
    found_titles = list(dict.fromkeys(found_titles))

    experience_years = _extract_experience(text)

    return {
        "skills": found_skills,
        "job_titles": found_titles,
        "experience_years": experience_years,
    }


def extract_keywords_smart(text):
    """Try Claude API first, fall back to heuristic."""
    from services.ai_client import is_available

    if is_available():
        try:
            return _claude_extract(text)
        except Exception as e:
            logger.warning("Claude extraction failed, falling back to heuristic: %s", e)

    return _heuristic_with_weights(text)


def _claude_extract(text):
    """Use Claude API to extract a rich skill graph from resume text."""
    from services.ai_client import call

    prompt = f"""Analyze this resume and extract structured information. Return ONLY valid JSON with this schema:

{{
  "skills": [
    {{"skill": "skill name", "weight": 0.0-1.0, "category": "category", "depth": "beginner|intermediate|advanced|expert"}}
  ],
  "job_titles": ["title1", "title2"],
  "experience_years": number or null,
  "seniority_tier": "IC1|IC2|IC3|IC4|IC5|IC6|Staff|Principal|Director+",
  "inferred_titles": ["related titles not in resume but matching the profile"],
  "inferred_skills": ["related skills not explicitly mentioned but likely known"]
}}

Weight reflects how central the skill is to the candidate's profile (1.0 = core expertise, 0.1 = mentioned once).
Seniority tiers: IC1=junior/new grad, IC2=mid, IC3=senior, IC4=staff, IC5=principal, IC6=distinguished, Director+=management.

Resume:
{text[:8000]}"""

    response_text = call(prompt, model="claude-haiku-4-5-20251001", max_tokens=1500)
    if not response_text:
        raise RuntimeError("Claude API unavailable")
    # Extract JSON from response
    json_match = re.search(r"\{[\s\S]*\}", response_text)
    if json_match:
        result = json.loads(json_match.group())
        logger.info("Claude extracted %d skills, seniority: %s",
                     len(result.get("skills", [])), result.get("seniority_tier"))
        return result

    raise ValueError("Could not parse Claude response as JSON")


def _heuristic_with_weights(text):
    """Enhanced heuristic extraction with weights based on frequency and section."""
    base = extract_keywords(text)
    text_lower = text.lower()

    # Weight skills by frequency
    weighted_skills = []
    for skill in base["skills"]:
        count = len(re.findall(re.escape(skill.lower()), text_lower))
        # Higher weight if in a "skills" section
        in_skills_section = bool(re.search(
            r"(skills|technologies|technical)\s*[:\-].*?" + re.escape(skill.lower()),
            text_lower,
        ))
        weight = min(1.0, 0.3 + (count * 0.15) + (0.2 if in_skills_section else 0))
        weighted_skills.append({
            "skill": skill,
            "weight": round(weight, 2),
            "category": _get_skill_category(skill),
            "depth": _infer_depth(count, in_skills_section),
        })

    # Sort by weight descending
    weighted_skills.sort(key=lambda x: x["weight"], reverse=True)

    # Infer seniority
    years = base["experience_years"]
    seniority = _infer_seniority(years, text)

    return {
        "skills": weighted_skills,
        "job_titles": base["job_titles"],
        "experience_years": years,
        "seniority_tier": seniority,
        "inferred_titles": [],
        "inferred_skills": [],
    }


def _extract_experience(text):
    patterns = [
        r"(\d+)\+?\s*years?\s*(?:of\s*)?(?:experience|exp|professional)",
        r"(\d+)\+?\s*years?\s*(?:in\s+(?:software|development|engineering))",
    ]
    max_years = None
    for pattern in patterns:
        matches = re.findall(pattern, text, re.IGNORECASE)
        for m in matches:
            y = int(m)
            if max_years is None or y > max_years:
                max_years = y
    return max_years


def _get_skill_category(skill):
    skills_db = _load_skills()
    for category, terms in skills_db.items():
        if skill in terms:
            return category
    return "other"


def _infer_depth(count, in_skills_section):
    if count >= 5 or (count >= 3 and in_skills_section):
        return "expert"
    elif count >= 3 or (count >= 2 and in_skills_section):
        return "advanced"
    elif count >= 2:
        return "intermediate"
    return "beginner"


def _infer_seniority(years, text):
    text_lower = text.lower()
    if any(t in text_lower for t in ["director", "vp ", "vice president", "head of"]):
        return "Director+"
    if any(t in text_lower for t in ["principal", "distinguished", "fellow"]):
        return "Principal"
    if any(t in text_lower for t in ["staff engineer", "staff software"]):
        return "Staff"
    if years is not None:
        if years >= 12:
            return "IC5"
        if years >= 8:
            return "IC4"
        if years >= 5:
            return "IC3"
        if years >= 2:
            return "IC2"
        return "IC1"
    if "senior" in text_lower:
        return "IC3"
    if "junior" in text_lower or "entry level" in text_lower:
        return "IC1"
    return "IC2"
