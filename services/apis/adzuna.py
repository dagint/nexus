import requests
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from config import Config
from services.apis.base import JobAPIProvider


class APIError(Exception):
    pass


class AdzunaProvider(JobAPIProvider):
    name = "Adzuna"

    def is_available(self):
        return bool(Config.ADZUNA_APP_ID and Config.ADZUNA_APP_KEY)

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10),
           retry=retry_if_exception_type((requests.exceptions.ConnectionError, requests.exceptions.Timeout, APIError)))
    def search(self, query, location, remote_only, date_posted, page, employment_type=""):
        search_query = query
        if remote_only:
            search_query += " remote"

        params = {
            "app_id": Config.ADZUNA_APP_ID,
            "app_key": Config.ADZUNA_APP_KEY,
            "what": search_query,
            "results_per_page": 20,
        }
        if location:
            params["where"] = location

        resp = requests.get(
            f"https://api.adzuna.com/v1/api/jobs/us/search/{page}",
            params=params, timeout=15,
        )
        self._track_response(resp)
        if resp.status_code in (429, 500, 503):
            raise APIError(f"Adzuna returned {resp.status_code}")
        resp.raise_for_status()

        results = []
        for item in resp.json().get("results", []):
            loc = item.get("location", {})
            location_str = ", ".join(loc.get("area", [])) if isinstance(loc, dict) else str(loc)
            title = item.get("title", "")
            desc = item.get("description", "")

            remote_status = "onsite"
            if any(kw in (title + " " + desc).lower() for kw in ["remote", "work from home", "wfh"]):
                remote_status = "remote"

            results.append(self.normalize({
                "title": title,
                "company": item.get("company", {}).get("display_name", "Unknown"),
                "location": location_str,
                "remote_status": remote_status,
                "description": desc,
                "apply_url": item.get("redirect_url", ""),
                "salary_min": item.get("salary_min"),
                "salary_max": item.get("salary_max"),
                "posted_date": item.get("created", ""),
            }))
        return results
