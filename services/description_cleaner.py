"""Clean job description text for display: strip HTML, fix encoding, preserve structure."""

import re

# Tags that imply a line break
_BLOCK_TAGS = re.compile(
    r'<\s*/?\s*(?:p|div|br|li|ul|ol|h[1-6]|tr|td|th|section|article|header|footer|blockquote)\b[^>]*>',
    re.IGNORECASE
)
# All remaining HTML tags
_ALL_TAGS = re.compile(r'<[^>]+>')
# HTML entities
_ENTITIES = {
    '&amp;': '&', '&lt;': '<', '&gt;': '>', '&quot;': '"',
    '&apos;': "'", '&nbsp;': ' ', '&#39;': "'", '&#x27;': "'",
    '&ndash;': '\u2013', '&mdash;': '\u2014', '&bull;': '\u2022',
    '&rsquo;': '\u2019', '&lsquo;': '\u2018',
    '&rdquo;': '\u201d', '&ldquo;': '\u201c',
    '&hellip;': '\u2026', '&trade;': '\u2122',
    '&copy;': '\u00a9', '&reg;': '\u00ae',
}
_ENTITY_RE = re.compile(r'&(?:#(?:x[0-9a-fA-F]+|\d+)|[a-zA-Z]+);')
# Multiple blank lines
_MULTI_BLANK = re.compile(r'\n{3,}')
# Multiple spaces (but not newlines)
_MULTI_SPACE = re.compile(r'[^\S\n]{2,}')

# Common mojibake patterns (UTF-8 bytes decoded as Latin-1/CP1252)
_MOJIBAKE_MAP = {
    '\u00e2\u0080\u0099': '\u2019',  # '  (right single quote)
    '\u00e2\u0080\u009c': '\u201c',  # "  (left double quote)
    '\u00e2\u0080\u009d': '\u201d',  # "  (right double quote)
    '\u00e2\u0080\u0093': '\u2013',  # –  (en dash)
    '\u00e2\u0080\u0094': '\u2014',  # —  (em dash)
    '\u00e2\u0080\u00a6': '\u2026',  # …  (ellipsis)
    '\u00e2\u0080\u0098': '\u2018',  # '  (left single quote)
    '\u00e2\u0080\u00a2': '\u2022',  # •  (bullet)
    '\u00e2\u0080\u201c': '\u201c',  # alternate encoding
    '\u00c2\u00a0': ' ',              # non-breaking space
}
# Regex to catch â€™ â€" â€" â€˜ â€œ â€ â€¦ â€¢ patterns
_MOJIBAKE_RE = re.compile(r'\u00e2\u0080[\u0093-\u00a6]|\u00c2\u00a0')


def _fix_mojibake(text):
    """Fix common UTF-8 mojibake (text decoded as Latin-1 instead of UTF-8)."""
    # First try the brute-force approach: re-encode as Latin-1 and decode as UTF-8
    try:
        fixed = text.encode('latin-1').decode('utf-8')
        # If it worked without errors, it was mojibake
        if fixed != text:
            return fixed
    except (UnicodeDecodeError, UnicodeEncodeError):
        pass

    # Fall back to known pattern replacement
    for bad, good in _MOJIBAKE_MAP.items():
        text = text.replace(bad, good)
    return text


def _decode_entity(match):
    text = match.group(0)
    if text in _ENTITIES:
        return _ENTITIES[text]
    if text.startswith('&#x'):
        try:
            return chr(int(text[3:-1], 16))
        except (ValueError, OverflowError):
            return text
    if text.startswith('&#'):
        try:
            return chr(int(text[2:-1]))
        except (ValueError, OverflowError):
            return text
    return text


def clean_description(text):
    """Clean a job description for display.

    - Fixes mojibake encoding issues (UTF-8 as Latin-1)
    - Converts block-level HTML tags to newlines
    - Converts <li> items to bullet points
    - Strips all remaining HTML tags
    - Decodes HTML entities
    - Preserves paragraph structure
    - Collapses excessive whitespace
    """
    if not text:
        return ""

    # Fix mojibake encoding first
    result = _fix_mojibake(text)

    # Convert <li> to bullet points before stripping tags
    result = re.sub(r'<\s*li\b[^>]*>', '\n\u2022 ', result, flags=re.IGNORECASE)

    # Convert heading tags to bold-style markers
    result = re.sub(r'<\s*h[1-6]\b[^>]*>(.*?)</\s*h[1-6]\s*>',
                    r'\n\n\1\n', result, flags=re.IGNORECASE | re.DOTALL)

    # Convert <p> to double newline (paragraph break)
    result = re.sub(r'<\s*/?\s*p\b[^>]*>', '\n\n', result, flags=re.IGNORECASE)

    # Convert <br> to single newline
    result = re.sub(r'<\s*br\s*/?\s*>', '\n', result, flags=re.IGNORECASE)

    # Convert remaining block tags to newlines
    result = _BLOCK_TAGS.sub('\n', result)

    # Strip remaining HTML tags
    result = _ALL_TAGS.sub('', result)

    # Decode HTML entities
    result = _ENTITY_RE.sub(_decode_entity, result)

    # Normalize whitespace per line (collapse spaces but keep newlines)
    result = _MULTI_SPACE.sub(' ', result)

    # Clean up lines: strip each, collapse excessive blank lines to max 2
    lines = result.split('\n')
    lines = [line.strip() for line in lines]

    # Collapse runs of blank lines to at most one blank line (paragraph separator)
    cleaned = []
    prev_blank = False
    for line in lines:
        if not line:
            if not prev_blank:
                cleaned.append('')
            prev_blank = True
        else:
            cleaned.append(line)
            prev_blank = False

    result = '\n'.join(cleaned)
    return result.strip()
