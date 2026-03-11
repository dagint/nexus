import requests
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from services.apis.base import JobAPIProvider


class RemoteOKProvider(JobAPIProvider):
    name = "RemoteOK"

    def is_available(self):
        return True  # Public JSON feed, no key needed

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10),
           retry=retry_if_exception_type((requests.exceptions.ConnectionError, requests.exceptions.Timeout)))
    def search(self, query, location, remote_only, date_posted, page, employment_type=""):
        if page > 1:
            return []  # RemoteOK doesn't support pagination

        resp = requests.get(
            "https://remoteok.com/api",
            headers={"User-Agent": "Nexus Job Search"},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()

        # First element is metadata, skip it
        jobs = data[1:] if len(data) > 1 else []

        query_lower = query.lower()
        results = []
        for item in jobs:
            title = item.get("position", "")
            description = item.get("description", "")
            tags = " ".join(item.get("tags", []))

            # Filter by query
            searchable = f"{title} {description} {tags}".lower()
            if query_lower not in searchable:
                continue

            salary_min = None
            salary_max = None
            if item.get("salary_min"):
                try:
                    salary_min = float(item["salary_min"])
                except (ValueError, TypeError):
                    pass
            if item.get("salary_max"):
                try:
                    salary_max = float(item["salary_max"])
                except (ValueError, TypeError):
                    pass

            results.append(self.normalize({
                "title": title,
                "company": item.get("company", ""),
                "location": item.get("location", "Remote"),
                "remote_status": "remote",
                "description": description,
                "apply_url": item.get("url", ""),
                "salary_min": salary_min,
                "salary_max": salary_max,
                "posted_date": item.get("date", ""),
            }))

            if len(results) >= 20:
                break

        return results
