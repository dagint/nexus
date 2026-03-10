"""Preference learning system that analyzes bookmarked/applied/dismissed jobs
to learn user preferences and boost job match scores."""

import json
import logging
import os
import re
from collections import Counter

logger = logging.getLogger(__name__)

_skills_data = None


def _load_skills():
    """Load skills from skills.json for matching."""
    global _skills_data
    if _skills_data is None:
        path = os.path.join(os.path.dirname(__file__), "..", "data", "skills.json")
        with open(path) as f:
            _skills_data = json.load(f)
    return _skills_data


def _extract_skills_from_text(text):
    """Extract known skills from text using skills.json."""
    if not text:
        return []
    skills_data = _load_skills()
    text_lower = text.lower()
    found = []
    for category, skill_list in skills_data.items():
        if category == "job_titles":
            continue
        for skill in skill_list:
            if skill.lower() in text_lower:
                found.append(skill)
    return found


def _extract_title_keywords(title):
    """Extract significant words from a job title."""
    if not title:
        return []
    stop_words = {
        "a", "an", "the", "and", "or", "of", "in", "at", "to", "for", "with",
        "is", "are", "was", "were", "be", "been", "being",
        "i", "ii", "iii", "iv", "v", "vi",
        "-", "/", "&", "|",
    }
    words = re.findall(r'[a-zA-Z]+', title.lower())
    return [w for w in words if w not in stop_words and len(w) > 1]


def build_preference_profile(user_id):
    """Analyze bookmarked + applied + dismissed jobs to extract preference profile.

    Returns a dict with:
      - preferred_skills: list of (skill, count) tuples
      - preferred_titles: list of title keywords
      - preferred_companies: set of companies
      - preferred_remote: float ratio (0.0 to 1.0) of remote jobs
      - salary_range: dict with min/max
      - title_keywords: Counter of significant title words
      - avoided_companies: set of companies from dismissed jobs
      - avoided_title_keywords: Counter of title words from dismissed jobs
    """
    from database import get_bookmarked_jobs, get_applied_jobs, get_dismissed_jobs

    bookmarked = get_bookmarked_jobs(user_id)
    applied = get_applied_jobs(user_id)
    try:
        dismissed = get_dismissed_jobs(user_id)
    except Exception:
        dismissed = []

    # Convert to dicts
    liked_jobs = [dict(row) for row in bookmarked] + [dict(row) for row in applied]
    dismissed_jobs = [dict(row) for row in dismissed]

    if not liked_jobs and not dismissed_jobs:
        return {}

    profile = {}

    # --- Positive signals from liked jobs ---
    if liked_jobs:
        # Skills extraction
        skill_counter = Counter()
        for job in liked_jobs:
            text = (job.get("title", "") or "") + " " + (job.get("description", "") or "")
            skills = _extract_skills_from_text(text)
            skill_counter.update(skills)

        profile["preferred_skills"] = skill_counter.most_common(20)

        # Title keywords
        title_counter = Counter()
        for job in liked_jobs:
            keywords = _extract_title_keywords(job.get("title", ""))
            title_counter.update(keywords)
        profile["title_keywords"] = title_counter
        profile["preferred_titles"] = [kw for kw, _ in title_counter.most_common(10)]

        # Companies
        companies = set()
        for job in liked_jobs:
            company = (job.get("company") or "").strip()
            if company:
                companies.add(company)
        profile["preferred_companies"] = companies

        # Remote preference
        remote_count = 0
        total_with_status = 0
        for job in liked_jobs:
            status = job.get("remote_status", "")
            if status:
                total_with_status += 1
                if status == "remote":
                    remote_count += 1
        profile["preferred_remote"] = (
            remote_count / total_with_status if total_with_status > 0 else 0.5
        )

        # Salary range
        salary_mins = []
        salary_maxs = []
        for job in liked_jobs:
            s_min = job.get("salary_min")
            s_max = job.get("salary_max")
            if s_min and s_min > 0:
                salary_mins.append(s_min)
            if s_max and s_max > 0:
                salary_maxs.append(s_max)

        if salary_mins or salary_maxs:
            profile["salary_range"] = {
                "min": min(salary_mins) if salary_mins else None,
                "max": max(salary_maxs) if salary_maxs else None,
            }
        else:
            profile["salary_range"] = {}

    # --- Negative signals from dismissed jobs ---
    if dismissed_jobs:
        avoided_companies = set()
        avoided_title_counter = Counter()
        for job in dismissed_jobs:
            company = (job.get("company") or "").strip()
            if company:
                avoided_companies.add(company)
            keywords = _extract_title_keywords(job.get("title", ""))
            avoided_title_counter.update(keywords)

        profile["avoided_companies"] = avoided_companies
        profile["avoided_title_keywords"] = avoided_title_counter
    else:
        profile["avoided_companies"] = set()
        profile["avoided_title_keywords"] = Counter()

    return profile


def compute_preference_boost(job, preference_profile):
    """Compute bonus/penalty points based on learned preferences.

    Returns (points, reasons) where points is -5 to +15 and reasons
    is a list of human-readable explanation strings.
    """
    if not preference_profile:
        return 0, []

    bonus = 0
    penalty = 0
    reasons = []

    # +3 if job has skills that appear frequently in liked jobs
    preferred_skills = preference_profile.get("preferred_skills", [])
    if preferred_skills:
        job_text = (
            (job.get("title", "") or "") + " " + (job.get("description", "") or "")
        ).lower()
        # Check top skills (those with count >= 2 or top 10)
        top_skills = [skill for skill, count in preferred_skills[:10]]
        matched_skills = [s for s in top_skills if s.lower() in job_text]
        if matched_skills:
            bonus += 3
            reasons.append(f"Preferred skills: {', '.join(matched_skills[:3])}")

    # +3 if job title contains keywords from liked job titles
    title_keywords = preference_profile.get("title_keywords", Counter())
    if title_keywords:
        job_title_words = set(_extract_title_keywords(job.get("title", "")))
        # Use the most common title keywords (count >= 2)
        frequent_keywords = {kw for kw, count in title_keywords.items() if count >= 2}
        if not frequent_keywords:
            frequent_keywords = {kw for kw, _ in title_keywords.most_common(5)}
        overlap = job_title_words & frequent_keywords
        if overlap:
            bonus += 3
            reasons.append(f"Similar role: {', '.join(list(overlap)[:3])}")

    # +3 if company was previously bookmarked/applied to
    preferred_companies = preference_profile.get("preferred_companies", set())
    job_company = (job.get("company") or "").strip()
    if job_company and job_company in preferred_companies:
        bonus += 3
        reasons.append(f"Previously saved company: {job_company}")

    # +3 if remote status matches user's behavioral preference
    preferred_remote = preference_profile.get("preferred_remote")
    if preferred_remote is not None:
        job_remote = job.get("remote_status", "")
        if preferred_remote >= 0.7 and job_remote == "remote":
            bonus += 3
            reasons.append("Matches remote preference")
        elif preferred_remote <= 0.3 and job_remote in ("onsite", ""):
            bonus += 3
            reasons.append("Matches onsite preference")
        elif 0.3 < preferred_remote < 0.7 and job_remote == "hybrid":
            bonus += 3
            reasons.append("Matches hybrid preference")

    # +3 if salary is within their preferred range
    salary_range = preference_profile.get("salary_range", {})
    if salary_range:
        pref_min = salary_range.get("min")
        pref_max = salary_range.get("max")
        job_min = job.get("salary_min") or job.get("salary_annual_min")
        job_max = job.get("salary_max") or job.get("salary_annual_max")

        if (pref_min or pref_max) and (job_min or job_max):
            in_range = True
            if pref_min and job_max and job_max < pref_min * 0.8:
                in_range = False
            if pref_max and job_min and job_min > pref_max * 1.2:
                in_range = False
            if in_range:
                bonus += 3
                reasons.append("Salary in preferred range")

    # Cap bonus at 15
    bonus = min(bonus, 15)

    # --- Negative signals: -5 if job matches dismissed patterns ---
    avoided_companies = preference_profile.get("avoided_companies", set())
    avoided_keywords = preference_profile.get("avoided_title_keywords", Counter())

    has_negative = False
    if job_company and job_company in avoided_companies:
        has_negative = True
        reasons.append(f"Previously dismissed company: {job_company}")

    if avoided_keywords and not has_negative:
        job_title_words = set(_extract_title_keywords(job.get("title", "")))
        frequent_avoided = {kw for kw, count in avoided_keywords.items() if count >= 2}
        if frequent_avoided and job_title_words & frequent_avoided:
            has_negative = True
            reasons.append("Similar to dismissed jobs")

    if has_negative:
        penalty = -5

    return bonus + penalty, reasons
