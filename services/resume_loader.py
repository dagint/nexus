"""Shared helper for loading the user's default resume."""

import json
import logging

from database import get_default_resume

logger = logging.getLogger(__name__)


def require_resume(user_id):
    """Load default resume or return (None, error_tuple).

    Returns:
        (resume_info, None) on success — resume_info has keys: text, data, id
        (None, (json_response, status_code)) on failure
    """
    from flask import jsonify

    default = get_default_resume(user_id)
    if not default:
        return None, (jsonify({"error": "No resume saved. Upload a resume first."}), 400)

    return _parse_resume(default), None


def load_resume_or_empty(user_id):
    """Load default resume, returning empty strings if none exists.

    Returns:
        resume_info dict with keys: text, data, id (id may be None)
    """
    default = get_default_resume(user_id)
    if not default:
        return {"text": "", "data": {}, "id": None}

    return _parse_resume(default)


def _parse_resume(default):
    """Extract text and parsed skills from a resume row."""
    data = {}
    if default.get("skills_json"):
        try:
            data = json.loads(default["skills_json"])
        except (json.JSONDecodeError, TypeError):
            pass

    return {
        "text": default["raw_text"],
        "data": data,
        "id": default.get("id"),
    }
