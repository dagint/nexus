import logging
import re

import requests
from bs4 import BeautifulSoup

from database import get_cached_company, cache_company

logger = logging.getLogger(__name__)


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
    """Enrich a list of jobs with company data."""
    seen_companies = {}
    for job in jobs:
        company = job.get("company", "")
        if company in seen_companies:
            job["company_info"] = seen_companies[company]
        else:
            try:
                info = enrich_company(company)
                seen_companies[company] = info
                job["company_info"] = info
            except Exception as e:
                logger.warning("Failed to enrich %s: %s", company, e)
                job["company_info"] = None
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

        resp = requests.get(url, headers=headers, timeout=10)
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
