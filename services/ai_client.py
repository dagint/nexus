"""Shared AI client with circuit breaker. Supports Claude API and local Ollama models."""
import logging
from config import Config

logger = logging.getLogger(__name__)

_api_available = True
_client = None
_provider = None  # "anthropic" or "ollama"


def _detect_provider():
    """Detect which AI provider to use based on config."""
    global _provider
    if _provider:
        return _provider

    if Config.OLLAMA_MODEL:
        _provider = "ollama"
        logger.info("AI provider: Ollama (model=%s, url=%s)", Config.OLLAMA_MODEL, Config.OLLAMA_URL)
    elif Config.ANTHROPIC_API_KEY:
        _provider = "anthropic"
        logger.info("AI provider: Anthropic Claude API")
    else:
        _provider = "none"
        logger.info("AI provider: none (heuristic fallback only)")

    return _provider


def is_available():
    """Check if any AI provider is currently available."""
    if not _api_available:
        return False
    provider = _detect_provider()
    return provider in ("anthropic", "ollama")


def mark_unavailable():
    """Mark the AI as unavailable for this session (after a fatal error)."""
    global _api_available
    _api_available = False
    logger.warning("AI marked unavailable for this session")


def call(prompt, model=None, max_tokens=1000):
    """Make an AI call with automatic circuit breaker.

    Returns the response text, or None if the call fails.

    For Anthropic: uses the specified model (defaults to Haiku for cost efficiency).
    For Ollama: ignores the model param and uses OLLAMA_MODEL from config.
    """
    if not _api_available:
        return None

    provider = _detect_provider()

    if provider == "ollama":
        return _call_ollama(prompt, max_tokens)
    elif provider == "anthropic":
        return _call_anthropic(prompt, model or "claude-haiku-4-5-20251001", max_tokens)
    else:
        return None


def _call_anthropic(prompt, model, max_tokens):
    """Call the Anthropic Claude API."""
    global _client

    if _client is None:
        try:
            import anthropic
            _client = anthropic.Anthropic(api_key=Config.ANTHROPIC_API_KEY)
        except Exception as e:
            logger.warning("Failed to create Anthropic client: %s", e)
            mark_unavailable()
            return None

    try:
        message = _client.messages.create(
            model=model,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        return message.content[0].text.strip()
    except Exception as e:
        error_str = str(e)
        if "credit balance" in error_str or "invalid_api_key" in error_str or "authentication" in error_str.lower():
            mark_unavailable()
        logger.warning("Anthropic API call failed: %s", e)
        return None


def _call_ollama(prompt, max_tokens):
    """Call a local Ollama instance via its OpenAI-compatible API."""
    import requests

    url = Config.OLLAMA_URL.rstrip("/") + "/api/chat"

    try:
        resp = requests.post(
            url,
            json={
                "model": Config.OLLAMA_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "stream": False,
                "options": {
                    "num_predict": max_tokens,
                },
            },
            timeout=60,
        )
        resp.raise_for_status()
        data = resp.json()
        return data.get("message", {}).get("content", "").strip()
    except requests.exceptions.ConnectionError:
        logger.warning("Ollama not reachable at %s — is it running?", Config.OLLAMA_URL)
        mark_unavailable()
        return None
    except Exception as e:
        logger.warning("Ollama call failed: %s", e)
        return None
