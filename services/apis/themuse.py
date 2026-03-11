import requests
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from services.apis.base import JobAPIProvider


class TheMuseProvider(JobAPIProvider):
    name = "TheMuse"

    def is_available(self):
        return True  # Public API, no key needed

    LEVEL_MAP = {
        "": [],
        "internship": ["Internship"],
        "entry": ["Entry Level"],
        "mid": ["Mid Level"],
        "senior": ["Senior Level"],
    }

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10),
           retry=retry_if_exception_type((requests.exceptions.ConnectionError, requests.exceptions.Timeout)))
    def search(self, query, location, remote_only, date_posted, page, employment_type=""):
        params = {
            "page": page,
            "descending": "true",
        }

        # The Muse uses category-based search
        if query:
            params["category"] = query

        if location:
            # The Muse uses "location" parameter, supports city names
            params["location"] = location

        resp = requests.get(
            "https://www.themuse.com/api/public/jobs",
            params=params,
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()

        query_lower = query.lower() if query else ""
        results = []
        for item in data.get("results", []):
            title = item.get("name", "")
            company_obj = item.get("company", {})
            company = company_obj.get("name", "") if isinstance(company_obj, dict) else str(company_obj)

            # Extract locations
            locations = item.get("locations", [])
            location_str = ", ".join(loc.get("name", "") for loc in locations) if locations else ""

            # Check remote status
            is_remote = any("remote" in loc.get("name", "").lower() for loc in locations) if locations else False

            # Filter by query in title/description
            description = item.get("contents", "")
            if query_lower:
                searchable = f"{title} {description}".lower()
                if query_lower not in searchable:
                    continue

            # Build apply URL
            refs = item.get("refs", {})
            apply_url = refs.get("landing_page", "") if isinstance(refs, dict) else ""

            results.append(self.normalize({
                "title": title,
                "company": company,
                "location": location_str,
                "remote_status": "remote" if is_remote else "onsite",
                "description": description,
                "apply_url": apply_url,
                "salary_min": None,
                "salary_max": None,
                "posted_date": item.get("publication_date", ""),
            }))

            if len(results) >= 20:
                break

        return results
