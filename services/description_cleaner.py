"""Clean job description text for display: strip HTML, preserve bullets, collapse whitespace."""

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
}
_ENTITY_RE = re.compile(r'&(?:#(?:x[0-9a-fA-F]+|\d+)|[a-zA-Z]+);')
# Multiple blank lines
_MULTI_BLANK = re.compile(r'\n{3,}')
# Multiple spaces (but not newlines)
_MULTI_SPACE = re.compile(r'[^\S\n]{2,}')


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

    - Converts block-level HTML tags to newlines
    - Converts <li> items to bullet points
    - Strips all remaining HTML tags
    - Decodes HTML entities
    - Collapses excessive whitespace while preserving paragraph breaks
    """
    if not text:
        return ""

    # Convert <li> to bullet points before stripping tags
    result = re.sub(r'<\s*li\b[^>]*>', '\n\u2022 ', text, flags=re.IGNORECASE)

    # Convert block tags to newlines
    result = _BLOCK_TAGS.sub('\n', result)

    # Strip remaining HTML tags
    result = _ALL_TAGS.sub('', result)

    # Decode HTML entities
    result = _ENTITY_RE.sub(_decode_entity, result)

    # Normalize whitespace
    result = _MULTI_SPACE.sub(' ', result)
    result = _MULTI_BLANK.sub('\n\n', result)

    # Clean up lines
    lines = result.split('\n')
    lines = [line.strip() for line in lines]
    result = '\n'.join(lines)

    return result.strip()
