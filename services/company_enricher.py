import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from bs4 import BeautifulSoup

from database import get_cached_company, cache_company

logger = logging.getLogger(__name__)

_MAX_ENRICHMENT_WORKERS = 5


def enrich_company(company_name):
    """Get enrichment data for a company. Uses cache if available."""
    if not company_name or company_name == "Unknown Company":
        return None

    cached = get_cached_company(company_name)
    if cached:
        return cached

    data = _scrape_company_data(company_name)
    if data:
        cache_company(company_name, data)
    return data


def enrich_jobs(jobs):
    """Enrich a list of jobs with company data (parallel HTTP scrapes)."""
    unique_companies = list({j.get("company", "") for j in jobs})
    company_info = {}

    # Separate cached from uncached
    uncached = []
    for name in unique_companies:
        if not name or name == "Unknown Company":
            company_info[name] = None
            continue
        cached = get_cached_company(name)
        if cached is not None:
            company_info[name] = cached
        else:
            uncached.append(name)

    # Scrape uncached companies in parallel (with circuit breaker)
    if uncached:
        consecutive_failures = 0
        max_consecutive_failures = 2
        workers = min(_MAX_ENRICHMENT_WORKERS, len(uncached))
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {executor.submit(enrich_company, name): name for name in uncached}
            for future in as_completed(futures):
                name = futures[future]
                try:
                    result = future.result()
                    company_info[name] = result
                    if result is not None:
                        consecutive_failures = 0
                    else:
                        consecutive_failures += 1
                except Exception as e:
                    logger.warning("Failed to enrich %s: %s", name, e)
                    company_info[name] = None
                    consecutive_failures += 1

                if consecutive_failures >= max_consecutive_failures:
                    logger.warning("Circuit breaker: %d consecutive enrichment failures, skipping remaining companies", consecutive_failures)
                    for remaining_future in futures:
                        if not remaining_future.done():
                            remaining_future.cancel()
                    # Set remaining companies to None
                    for remaining_name in uncached:
                        if remaining_name not in company_info:
                            company_info[remaining_name] = None
                    break

    for job in jobs:
        job["company_info"] = company_info.get(job.get("company", ""))
    return jobs


def _scrape_company_data(company_name):
    """Scrape basic company data from public sources."""
    data = {
        "name": company_name,
        "size": None,
        "industry": None,
        "description": None,
        "glassdoor_rating": None,
        "news": [],
    }

    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }

        # Search for company info
        query = f"{company_name} company size employees glassdoor rating"
        url = f"https://html.duckduckgo.com/html/?q={requests.utils.quote(query)}"

        resp = requests.get(url, headers=headers, timeout=3)
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, "html.parser")
            snippets = soup.select(".result__snippet")
            for snippet in snippets[:5]:
                text = snippet.get_text()

                # Extract employee count
                emp_match = re.search(r"([\d,]+)\s*(?:employees|staff|workers|people)", text, re.IGNORECASE)
                if emp_match and not data["size"]:
                    data["size"] = emp_match.group(0)

                # Extract Glassdoor rating
                rating_match = re.search(r"(\d\.?\d?)\s*(?:out of 5|/5|stars?|rating)", text, re.IGNORECASE)
                if rating_match and not data["glassdoor_rating"]:
                    try:
                        rating = float(rating_match.group(1))
                        if 1.0 <= rating <= 5.0:
                            data["glassdoor_rating"] = str(rating)
                    except ValueError:
                        pass

                # Extract industry
                industry_match = re.search(r"(?:industry|sector)[:\s]+([A-Za-z\s&]+?)(?:\.|,|$)", text, re.IGNORECASE)
                if industry_match and not data["industry"]:
                    data["industry"] = industry_match.group(1).strip()[:50]

                # Extract description
                if not data["description"] and len(text) > 50:
                    data["description"] = text[:200]

    except Exception as e:
        logger.warning("Scraping failed for %s: %s", company_name, e)

    # Only return if we got something useful
    if data["size"] or data["description"] or data["glassdoor_rating"]:
        return data
    return None


def generate_company_summary(company_name, existing_data=None):
    """Generate an AI-synthesized company research summary.

    Returns a dict with culture, tech_stack, growth_stage, pros, cons, summary.
    Falls back to heuristic if AI is unavailable.
    """
    from services.ai_client import call, is_available

    base_info = ""
    if existing_data:
        if existing_data.get("description"):
            base_info += f"Known info: {existing_data['description']}\n"
        if existing_data.get("size"):
            base_info += f"Size: {existing_data['size']}\n"
        if existing_data.get("industry"):
            base_info += f"Industry: {existing_data['industry']}\n"
        if existing_data.get("glassdoor_rating"):
            base_info += f"Glassdoor rating: {existing_data['glassdoor_rating']}\n"

    if is_available():
        result = _ai_company_summary(company_name, base_info)
        if result:
            return result

    # Heuristic fallback
    return _heuristic_company_summary(company_name, existing_data)


def _ai_company_summary(company_name, base_info=""):
    """Use AI to generate a company research summary."""
    from services.ai_client import call

    prompt = f"""Research summary for the company "{company_name}".
{base_info}

Provide a structured analysis in the following JSON format (respond ONLY with valid JSON):
{{
    "summary": "2-3 sentence overview of the company",
    "culture": "Brief description of company culture and values",
    "tech_stack": ["technology1", "technology2", "technology3"],
    "growth_stage": "startup / growth / mature / enterprise",
    "pros": ["pro1", "pro2", "pro3"],
    "cons": ["con1", "con2"]
}}

If you don't have specific information about the company, provide reasonable inferences based on the company name and any available data. Keep each field concise."""

    import json
    response = call(prompt, max_tokens=600, endpoint="company_research")
    if not response:
        return None

    try:
        # Try to extract JSON from the response
        response = response.strip()
        if response.startswith("```"):
            lines = response.split("\n")
            response = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
        data = json.loads(response)
        # Ensure all expected fields exist
        return {
            "summary": data.get("summary", ""),
            "culture": data.get("culture", ""),
            "tech_stack": data.get("tech_stack", []),
            "growth_stage": data.get("growth_stage", ""),
            "pros": data.get("pros", []),
            "cons": data.get("cons", []),
        }
    except (json.JSONDecodeError, TypeError):
        logger.warning("Failed to parse AI company summary for %s", company_name)
        return None


def _heuristic_company_summary(company_name, existing_data=None):
    """Build a basic company summary from available data."""
    summary = {
        "summary": f"{company_name} is a company in the market.",
        "culture": "",
        "tech_stack": [],
        "growth_stage": "",
        "pros": [],
        "cons": [],
    }

    if existing_data:
        if existing_data.get("description"):
            summary["summary"] = existing_data["description"]
        if existing_data.get("size"):
            size_str = existing_data["size"].lower()
            if any(x in size_str for x in ["10,000", "50,000", "100,000"]):
                summary["growth_stage"] = "enterprise"
            elif any(x in size_str for x in ["1,000", "5,000"]):
                summary["growth_stage"] = "mature"
            elif any(x in size_str for x in ["100", "500"]):
                summary["growth_stage"] = "growth"
            else:
                summary["growth_stage"] = "startup"
            summary["pros"].append(f"Company size: {existing_data['size']}")
        if existing_data.get("glassdoor_rating"):
            try:
                rating = float(existing_data["glassdoor_rating"])
                if rating >= 4.0:
                    summary["pros"].append(f"Strong employee rating ({rating}/5)")
                elif rating >= 3.0:
                    summary["culture"] = f"Average employee satisfaction ({rating}/5)"
                else:
                    summary["cons"].append(f"Low employee rating ({rating}/5)")
            except (ValueError, TypeError):
                pass
        if existing_data.get("industry"):
            summary["culture"] = f"Operates in the {existing_data['industry']} industry"

    return summary
