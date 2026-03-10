import requests
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from config import Config
from services.apis.base import JobAPIProvider


class APIError(Exception):
    pass


class SerpApiProvider(JobAPIProvider):
    name = "SerpApi"

    def is_available(self):
        return bool(Config.SERPAPI_KEY)

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10),
           retry=retry_if_exception_type((requests.exceptions.ConnectionError, requests.exceptions.Timeout, APIError)))
    def search(self, query, location, remote_only, date_posted, page):
        params = {
            "engine": "google_jobs",
            "q": query,
            "api_key": Config.SERPAPI_KEY,
        }
        if location:
            params["location"] = location
        if remote_only:
            params["ltype"] = "1"  # Work from home filter

        # Date posted mapping
        date_map = {"today": "today", "3days": "3days", "week": "week", "month": "month"}
        chips_date = date_map.get(date_posted)
        if chips_date:
            params["chips"] = f"date_posted:{chips_date}"

        # Pagination — SerpApi uses next_page_token, but for simplicity
        # we skip pagination beyond page 1 (API returns ~10 results per page)
        # A next_page_token approach would require caching tokens from prior pages.
        if page > 1:
            return []

        resp = requests.get(
            "https://serpapi.com/search",
            params=params, timeout=15,
        )
        if resp.status_code in (429, 500, 503):
            raise APIError(f"SerpApi returned {resp.status_code}")
        resp.raise_for_status()

        data = resp.json()
        results = []
        for item in data.get("jobs_results", []):
            # Determine remote status
            extensions = item.get("detected_extensions", {})
            if extensions.get("work_from_home") or remote_only:
                remote_status = "remote"
            else:
                location_text = item.get("location", "").lower()
                if "remote" in location_text:
                    remote_status = "remote"
                elif "hybrid" in location_text:
                    remote_status = "hybrid"
                else:
                    remote_status = "onsite"

            # Get the best apply URL
            apply_url = ""
            apply_options = item.get("apply_options", [])
            if apply_options:
                apply_url = apply_options[0].get("link", "")
            if not apply_url:
                apply_url = item.get("share_link", "")

            # Extract salary from extensions if available
            salary_min = None
            salary_max = None
            salary_str = extensions.get("salary", "")
            if salary_str:
                salary_min, salary_max = _parse_salary(salary_str)

            # Build description from highlights + description
            description = item.get("description", "")
            highlights = item.get("job_highlights", [])
            for section in highlights:
                section_title = section.get("title", "")
                items = section.get("items", [])
                if items:
                    description += f"\n\n{section_title}:\n" + "\n".join(f"• {i}" for i in items)

            # Posted date
            posted_date = ""
            posted_at = extensions.get("posted_at", "")
            if posted_at:
                posted_date = posted_at  # e.g., "3 days ago"

            results.append(self.normalize({
                "title": item.get("title", ""),
                "company": item.get("company_name", ""),
                "location": item.get("location", ""),
                "remote_status": remote_status,
                "description": description,
                "apply_url": apply_url,
                "salary_min": salary_min,
                "salary_max": salary_max,
                "posted_date": posted_date,
            }))

        return results


def _parse_salary(salary_str):
    """Parse salary strings like '$80K - $120K', '$100,000 a year', etc."""
    import re

    salary_str = salary_str.replace(",", "").replace("$", "").lower()
    # Match ranges like "80k - 120k" or "80000 - 120000"
    range_match = re.search(r"(\d+\.?\d*)\s*k?\s*[-–]\s*(\d+\.?\d*)\s*k?", salary_str)
    if range_match:
        low = float(range_match.group(1))
        high = float(range_match.group(2))
        # If values look like "80" rather than "80000", multiply by 1000
        if low < 1000:
            low *= 1000
        if high < 1000:
            high *= 1000
        return int(low), int(high)

    # Single value like "100k" or "100000"
    single_match = re.search(r"(\d+\.?\d*)\s*k?", salary_str)
    if single_match:
        val = float(single_match.group(1))
        if val < 1000:
            val *= 1000
        return int(val), None

    return None, None
