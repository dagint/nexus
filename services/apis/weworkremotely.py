import logging

import requests
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from services.apis.base import JobAPIProvider

logger = logging.getLogger(__name__)


class WeWorkRemotelyProvider(JobAPIProvider):
    name = "WeWorkRemotely"

    CATEGORIES = [
        "programming", "design", "devops-sysadmin", "product",
        "customer-support", "finance-legal", "marketing", "sales",
    ]

    def is_available(self):
        return True  # Public API, no key needed

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10),
           retry=retry_if_exception_type((requests.exceptions.ConnectionError, requests.exceptions.Timeout)))
    def search(self, query, location, remote_only, date_posted, page, employment_type=""):
        query_lower = query.lower()
        results = []

        for category in self.CATEGORIES:
            try:
                resp = requests.get(
                    f"https://weworkremotely.com/categories/{category}.json",
                    timeout=10,
                )
                if resp.status_code != 200:
                    continue
                data = resp.json()
                jobs = data if isinstance(data, list) else data.get("jobs", [])
                for item in jobs:
                    title = item.get("title", "")
                    company = item.get("company", {})
                    company_name = company.get("name", "") if isinstance(company, dict) else str(company)
                    if query_lower in title.lower() or query_lower in company_name.lower():
                        results.append(self.normalize({
                            "title": title,
                            "company": company_name,
                            "location": "Remote",
                            "remote_status": "remote",
                            "description": item.get("description", ""),
                            "apply_url": item.get("url", ""),
                            "salary_min": None,
                            "salary_max": None,
                            "posted_date": item.get("published_at", ""),
                        }))
            except Exception as e:
                logger.warning("WWR category %s failed: %s", category, e)

        return results
