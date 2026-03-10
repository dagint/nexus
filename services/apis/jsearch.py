import requests
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from config import Config
from services.apis.base import JobAPIProvider


class APIError(Exception):
    pass


class JSearchProvider(JobAPIProvider):
    name = "JSearch"

    def is_available(self):
        return bool(Config.RAPIDAPI_KEY)

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10),
           retry=retry_if_exception_type((requests.exceptions.ConnectionError, requests.exceptions.Timeout, APIError)))
    def search(self, query, location, remote_only, date_posted, page):
        params = {
            "query": f"{query} in {location}" if location else query,
            "page": str(page),
            "num_pages": "1",
            "date_posted": date_posted,
        }
        if remote_only:
            params["remote_jobs_only"] = "true"

        headers = {
            "X-RapidAPI-Key": Config.RAPIDAPI_KEY,
            "X-RapidAPI-Host": "jsearch.p.rapidapi.com",
        }

        resp = requests.get(
            "https://jsearch.p.rapidapi.com/search",
            headers=headers, params=params, timeout=15,
        )
        if resp.status_code in (429, 500, 503):
            raise APIError(f"JSearch returned {resp.status_code}")
        resp.raise_for_status()

        results = []
        for item in resp.json().get("data", []):
            results.append(self.normalize({
                "title": item.get("job_title", ""),
                "company": item.get("employer_name", ""),
                "location": item.get("job_city", "") or item.get("job_state", "") or item.get("job_country", ""),
                "remote_status": "remote" if item.get("job_is_remote") else "onsite",
                "description": item.get("job_description", ""),
                "apply_url": item.get("job_apply_link", ""),
                "salary_min": item.get("job_min_salary"),
                "salary_max": item.get("job_max_salary"),
                "posted_date": item.get("job_posted_at_datetime_utc", ""),
            }))
        return results
