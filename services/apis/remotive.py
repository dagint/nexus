import requests
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from services.apis.base import JobAPIProvider


class RemotiveProvider(JobAPIProvider):
    name = "Remotive"

    def is_available(self):
        return True  # Public API, no key needed

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10),
           retry=retry_if_exception_type((requests.exceptions.ConnectionError, requests.exceptions.Timeout)))
    def search(self, query, location, remote_only, date_posted, page, employment_type=""):
        resp = requests.get(
            "https://remotive.com/api/remote-jobs",
            params={"search": query, "limit": 20},
            timeout=15,
        )
        resp.raise_for_status()

        results = []
        for item in resp.json().get("jobs", []):
            results.append(self.normalize({
                "title": item.get("title", ""),
                "company": item.get("company_name", ""),
                "location": item.get("candidate_required_location", "Anywhere"),
                "remote_status": "remote",
                "description": item.get("description", ""),
                "apply_url": item.get("url", ""),
                "salary_min": None,
                "salary_max": None,
                "posted_date": item.get("publication_date", ""),
            }))
        return results
