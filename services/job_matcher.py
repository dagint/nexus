import json
import logging
import os
import re

logger = logging.getLogger(__name__)

_role_aliases = None


def _load_role_aliases():
    global _role_aliases
    if _role_aliases is None:
        path = os.path.join(os.path.dirname(__file__), "..", "data", "role_aliases.json")
        with open(path) as f:
            _role_aliases = json.load(f)
    return _role_aliases


def score_job(job, resume_data, user_prefs=None, preference_profile=None):
    """Score a job 0-100 based on match with resume data.

    resume_data: output from skills_extractor (smart or heuristic)
    user_prefs: dict with timezone, seniority preferences, etc.
    preference_profile: dict from preference_learner.build_preference_profile()
    """
    score = 0
    reasons = []

    # --- Skill overlap (40 points max) ---
    skill_score, skill_reasons = _score_skills(job, resume_data)
    score += skill_score
    reasons.extend(skill_reasons)

    # --- Title/role relevance (30 points max) ---
    title_score, title_reasons = _score_title(job, resume_data)
    score += title_score
    reasons.extend(title_reasons)

    # --- Seniority fit (15 points max) ---
    seniority_score, seniority_reasons = _score_seniority(job, resume_data)
    score += seniority_score
    reasons.extend(seniority_reasons)

    # --- Location/remote preference (15 points max) ---
    location_score, location_reasons = _score_location(job, user_prefs)
    score += location_score
    reasons.extend(location_reasons)

    # --- Preference boost (up to +15, or -5 penalty) ---
    if preference_profile:
        from services.preference_learner import compute_preference_boost
        pref_boost, pref_reasons = compute_preference_boost(job, preference_profile)
        score += pref_boost
        reasons.extend(pref_reasons)

    # Cap score at 100
    score = min(score, 100)

    # Determine tier
    if score >= 75:
        tier = "strong"
    elif score >= 50:
        tier = "possible"
    elif score >= 25:
        tier = "stretch"
    else:
        tier = "low"

    job["match_score"] = round(score)
    job["match_tier"] = tier
    job["match_reasons"] = reasons

    return job


def score_jobs(jobs, resume_data, user_prefs=None, preference_profile=None):
    """Score and tier all jobs, filtering out low matches."""
    scored = [score_job(job, resume_data, user_prefs, preference_profile) for job in jobs]
    # Filter out low matches
    scored = [j for j in scored if j["match_tier"] != "low"]
    # Sort by score descending
    scored.sort(key=lambda j: j["match_score"], reverse=True)
    return scored


def generate_match_summary(job, resume_data):
    """Generate a summary of why this job matches. Uses Claude for strong matches."""
    from config import Config

    if Config.ANTHROPIC_API_KEY and job.get("match_tier") == "strong":
        try:
            return _claude_summary(job, resume_data)
        except Exception as e:
            logger.warning("Claude summary failed: %s", e)

    # Heuristic summary
    reasons = job.get("match_reasons", [])
    if reasons:
        return "This role matches your profile because: " + "; ".join(reasons[:3]) + "."
    return ""


def _claude_summary(job, resume_data):
    import anthropic
    from config import Config

    client = anthropic.Anthropic(api_key=Config.ANTHROPIC_API_KEY)

    skills_list = _get_skill_names(resume_data)
    titles_list = resume_data.get("job_titles", []) + resume_data.get("inferred_titles", [])

    prompt = f"""Write a concise 2-3 sentence paragraph explaining why this job is a strong match for this candidate. Be specific about skill overlaps and role fit.

Job Title: {job['title']}
Company: {job['company']}
Job Description (first 500 chars): {job.get('description', '')[:500]}

Candidate Skills: {', '.join(skills_list[:20])}
Candidate Titles: {', '.join(titles_list[:10])}
Match Score: {job.get('match_score', 0)}/100

Return ONLY the paragraph, no preamble."""

    message = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=200,
        messages=[{"role": "user", "content": prompt}],
    )
    return message.content[0].text.strip()


def _get_skill_names(resume_data):
    """Extract flat skill name list from either format."""
    skills = resume_data.get("skills", [])
    if skills and isinstance(skills[0], dict):
        return [s["skill"] for s in skills]
    return skills


def _score_skills(job, resume_data):
    """Score based on skill overlap. Max 40 points."""
    desc_lower = (job.get("description", "") + " " + job.get("title", "")).lower()
    skills = resume_data.get("skills", [])
    inferred = resume_data.get("inferred_skills", [])

    matched = []
    total_weight = 0

    for skill in skills:
        if isinstance(skill, dict):
            name = skill["skill"]
            weight = skill.get("weight", 0.5)
        else:
            name = skill
            weight = 0.5

        if name.lower() in desc_lower:
            matched.append(name)
            total_weight += weight

    # Check inferred skills too (lower weight)
    for skill in inferred:
        if isinstance(skill, str) and skill.lower() in desc_lower:
            matched.append(f"{skill} (inferred)")
            total_weight += 0.2

    if not skills:
        return 20, []  # Neutral if no skills extracted

    max_possible = sum(
        s.get("weight", 0.5) if isinstance(s, dict) else 0.5
        for s in skills
    )
    ratio = min(total_weight / max(max_possible, 1), 1.0)
    score = round(ratio * 40)

    reasons = []
    if matched:
        reasons.append(f"Skills match: {', '.join(matched[:5])}")

    return score, reasons


def _score_title(job, resume_data):
    """Score based on title relevance. Max 30 points."""
    job_title = job.get("title", "").lower()
    aliases = _load_role_aliases()

    resume_titles = resume_data.get("job_titles", [])
    inferred_titles = resume_data.get("inferred_titles", [])

    # Check exact match
    for title in resume_titles:
        if title.lower() in job_title:
            return 30, [f"Exact title match: {title}"]

    # Check alias match
    for base_title, alias_list in aliases.items():
        all_titles = [base_title] + alias_list
        all_lower = [t.lower() for t in all_titles]

        resume_has = any(t.lower() in " ".join(all_lower) for t in resume_titles)
        job_has = any(t in job_title for t in all_lower)

        if resume_has and job_has:
            return 22, [f"Role alias match: {base_title}"]

    # Check inferred title match
    for title in inferred_titles:
        if title.lower() in job_title:
            return 15, [f"Inferred title match: {title}"]

    # Partial keyword overlap
    resume_words = set()
    for t in resume_titles:
        resume_words.update(t.lower().split())
    job_words = set(job_title.split())
    overlap = resume_words & job_words - {"engineer", "developer", "senior", "junior", "lead", "sr", "jr"}
    if overlap:
        return 10, [f"Partial title overlap: {', '.join(overlap)}"]

    # Claude-enhanced ambiguous title matching (only if no match found above)
    if resume_titles:
        claude_score = _claude_title_match(job_title, resume_titles)
        if claude_score:
            return claude_score

    return 0, []


def _claude_title_match(job_title, resume_titles):
    """Use Claude to assess title relevance for ambiguous cases."""
    from config import Config

    if not Config.ANTHROPIC_API_KEY:
        return None

    try:
        import anthropic

        client = anthropic.Anthropic(api_key=Config.ANTHROPIC_API_KEY)
        prompt = f"""Rate the relevance of this job title to a candidate with these titles on a scale of 0-30.
Return ONLY a JSON object: {{"score": <number>, "reason": "<brief reason>"}}

Job title: {job_title}
Candidate titles: {', '.join(resume_titles[:5])}"""

        message = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=100,
            messages=[{"role": "user", "content": prompt}],
        )
        response_text = message.content[0].text
        json_match = re.search(r"\{[\s\S]*\}", response_text)
        if json_match:
            result = json.loads(json_match.group())
            score = min(int(result.get("score", 0)), 30)
            reason = result.get("reason", "AI-assessed title match")
            if score >= 10:
                return score, [reason]
    except Exception as e:
        logger.warning("Claude title match failed: %s", e)

    return None


def _score_seniority(job, resume_data):
    """Score based on seniority fit. Max 15 points."""
    user_tier = resume_data.get("seniority_tier", "IC2")
    job_title = job.get("title", "").lower()
    job_desc = job.get("description", "").lower()

    tier_order = ["IC1", "IC2", "IC3", "IC4", "IC5", "IC6", "Staff", "Principal", "Director+"]

    # Detect job seniority
    job_tier = _detect_job_seniority(job_title, job_desc)

    try:
        user_idx = tier_order.index(user_tier)
        job_idx = tier_order.index(job_tier)
        diff = abs(user_idx - job_idx)

        if diff == 0:
            return 15, [f"Seniority match: {user_tier}"]
        elif diff == 1:
            return 10, [f"Close seniority: you={user_tier}, job={job_tier}"]
        elif diff == 2:
            return 5, []
        else:
            return 0, [f"Seniority mismatch: you={user_tier}, job={job_tier}"]
    except ValueError:
        return 8, []  # Unknown tier, neutral score


def _detect_job_seniority(title, desc):
    """Infer job seniority from title and description."""
    if any(w in title for w in ["principal", "distinguished", "fellow"]):
        return "Principal"
    if "staff" in title:
        return "Staff"
    if any(w in title for w in ["director", "vp ", "vice president", "head of"]):
        return "Director+"
    if any(w in title for w in ["senior", "sr.", "sr "]):
        return "IC3"
    if any(w in title for w in ["lead", "tech lead"]):
        return "IC4"
    if any(w in title for w in ["junior", "jr.", "jr ", "entry"]):
        return "IC1"
    if any(w in title for w in ["intern", "internship", "co-op"]):
        return "IC1"

    # Check description for years requirement
    match = re.search(r"(\d+)\+?\s*years?", desc)
    if match:
        years = int(match.group(1))
        if years >= 10:
            return "IC5"
        if years >= 7:
            return "IC4"
        if years >= 4:
            return "IC3"
        if years >= 2:
            return "IC2"
        return "IC1"

    return "IC2"


def _score_location(job, user_prefs):
    """Score based on location/remote preference. Max 15 points."""
    remote_status = job.get("remote_status", "onsite")

    if user_prefs and user_prefs.get("remote_only"):
        if remote_status == "remote":
            return 15, ["Remote position"]
        elif remote_status == "hybrid":
            return 8, ["Hybrid - not fully remote"]
        return 0, ["On-site only"]

    # Default: slight preference for remote
    if remote_status == "remote":
        return 15, ["Remote position"]
    elif remote_status == "hybrid":
        return 12, ["Hybrid position"]
    return 10, []
