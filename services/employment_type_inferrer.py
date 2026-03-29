"""Infer employment type from job title and description when APIs don't provide it."""

import re

# Patterns ordered by specificity; first match wins
_PATTERNS = [
    ("contract", [
        r"\bcontract\b", r"\bc2c\b", r"\bcorp[\s-]to[\s-]corp\b",
        r"\b1099\b", r"\bcontractor\b", r"\bfreelance\b",
        r"\btemp\s+to\s+hire\b", r"\btemp\b(?!late)",
    ]),
    ("parttime", [
        r"\bpart[\s-]time\b", r"\bpart\s*time\b",
        r"\b(?:10|15|20|25|30)\s*(?:hours?\s*/?\s*(?:per\s+)?(?:wk|week))\b",
    ]),
    ("internship", [
        r"\bintern\b", r"\binternship\b", r"\bco[\s-]?op\b",
    ]),
]

_COMPILED = [
    (etype, [re.compile(p, re.IGNORECASE) for p in patterns])
    for etype, patterns in _PATTERNS
]


def infer_employment_type(title: str, description: str) -> str:
    """Infer employment type from title and description text.

    Returns one of: 'contract', 'parttime', 'internship', or '' (unknown).
    Does NOT return 'fulltime' — that requires positive evidence from the API.
    """
    # Check title first (higher signal)
    for etype, patterns in _COMPILED:
        for pattern in patterns:
            if pattern.search(title):
                return etype

    # Then check description (first 2000 chars to avoid false matches deep in text)
    desc_snippet = description[:2000] if description else ""
    for etype, patterns in _COMPILED:
        for pattern in patterns:
            if pattern.search(desc_snippet):
                return etype

    return ""
