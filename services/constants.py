"""Shared constants used across multiple services."""

# Base English stop words — shared foundation for text processing.
# Services may extend this set with domain-specific words.
STOP_WORDS = {
    "the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "by", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "shall", "can", "need", "must", "not", "no",
    "we", "you", "he", "she", "it", "they", "i", "me", "my", "our",
    "your", "his", "her", "its", "their", "this", "that", "these", "those",
    "from", "up", "about", "into", "through", "during", "before", "after",
    "above", "below", "between", "out", "off", "over", "under", "again",
    "further", "then", "once", "here", "there", "when", "where", "why",
    "how", "all", "each", "every", "both", "few", "more", "most", "other",
    "some", "such", "only", "own", "same", "so", "than", "too", "very",
    "just", "because", "as", "if", "while", "also", "new", "one", "two",
    "three", "first", "last", "long", "great", "little", "right", "big",
    "high", "old", "small", "large", "next", "early", "young", "important",
    "public", "bad", "good", "best", "well", "way", "who", "what",
    "which", "much", "many", "any",
}

# Job-title filler words to exclude from analytics keyword extraction
JOB_TITLE_STOP_WORDS = STOP_WORDS | {
    "senior", "junior", "lead", "principal", "staff", "engineer", "developer",
    "manager", "director", "analyst", "specialist", "coordinator", "associate",
    "intern", "consultant", "architect", "administrator", "officer",
    "remote", "hybrid", "onsite", "full-time", "part-time", "contract",
}

# Pipeline / Kanban stage names
PIPELINE_STAGES = ["saved", "applied", "screen", "interview", "offer", "rejected", "withdrawn"]

RESULTS_PER_PAGE = 20


def safe_int(value, default=0):
    """Safely convert a value to int, returning default on failure."""
    try:
        return int(value)
    except (ValueError, TypeError):
        return default
