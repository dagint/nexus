"""API usage tracking and cost estimation."""
import logging

logger = logging.getLogger(__name__)

# Pricing per million tokens (USD)
ANTHROPIC_PRICING = {
    "claude-haiku-4-5-20251001": {"input": 0.80, "output": 4.00},
    "claude-sonnet-4-20250514": {"input": 3.00, "output": 15.00},
}

# Per-search pricing estimates (USD)
SEARCH_PRICING = {
    "SerpApi": 0.01,
    "JSearch": 0.005,
    "Adzuna": 0.0,
    "Remotive": 0.0,
    "WeWorkRemotely": 0.0,
}


def estimate_anthropic_cost(model, input_tokens, output_tokens):
    """Estimate cost in USD for an Anthropic API call."""
    pricing = ANTHROPIC_PRICING.get(model, {"input": 3.00, "output": 15.00})
    cost = (input_tokens * pricing["input"] + output_tokens * pricing["output"]) / 1_000_000
    return round(cost, 6)


def estimate_search_cost(provider):
    """Estimate cost for a job search API call."""
    return SEARCH_PRICING.get(provider, 0.0)


def _log_to_db(user_id, provider, endpoint, model=None,
               tokens_input=0, tokens_output=0, estimated_cost_usd=0.0,
               response_time_ms=0, success=True, error_message=None,
               status_code=None, results_count=None):
    """Log an API call to the database, swallowing errors."""
    try:
        from database import log_api_usage
        log_api_usage(
            user_id=user_id, provider=provider, endpoint=endpoint,
            model=model, tokens_input=tokens_input, tokens_output=tokens_output,
            estimated_cost_usd=estimated_cost_usd, response_time_ms=response_time_ms,
            success=1 if success else 0, error_message=error_message,
            status_code=status_code, results_count=results_count,
        )
    except Exception as e:
        logger.warning("Failed to log API usage: %s", e)


def log_ai_call(endpoint, model, input_tokens, output_tokens, response_time_ms,
                success=True, error_message=None, user_id=None):
    """Log an AI API call with cost estimation."""
    provider = "ollama" if model and model not in ANTHROPIC_PRICING else "anthropic"
    cost = 0.0 if provider == "ollama" else estimate_anthropic_cost(model, input_tokens, output_tokens)
    _log_to_db(
        user_id=user_id, provider=provider, endpoint=endpoint,
        model=model, tokens_input=input_tokens, tokens_output=output_tokens,
        estimated_cost_usd=cost, response_time_ms=response_time_ms,
        success=success, error_message=error_message,
    )


def log_search_call(provider, response_time_ms, success=True, error_message=None,
                    user_id=None, status_code=None, results_count=None):
    """Log a job search API call."""
    cost = estimate_search_cost(provider)
    _log_to_db(
        user_id=user_id, provider=provider, endpoint="search",
        estimated_cost_usd=cost, response_time_ms=response_time_ms,
        success=success, error_message=error_message,
        status_code=status_code, results_count=results_count,
    )
