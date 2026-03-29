import requests
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from config import Config
from services.apis.base import JobAPIProvider


class USAJobsProvider(JobAPIProvider):
    name = "USAJobs"

    def is_available(self):
        return bool(Config.USAJOBS_API_KEY and Config.USAJOBS_EMAIL)

    DATE_RANGE_MAP = {
        "today": 1,
        "3days": 3,
        "week": 7,
        "month": 30,
        "": 30,
    }

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10),
           retry=retry_if_exception_type((requests.exceptions.ConnectionError, requests.exceptions.Timeout)))
    def search(self, query, location, remote_only, date_posted, page, employment_type=""):
        params = {
            "Keyword": query,
            "Page": page,
            "ResultsPerPage": 20,
        }

        if location:
            params["LocationName"] = location

        if remote_only:
            params["RemoteIndicator"] = "True"

        days = self.DATE_RANGE_MAP.get(date_posted, 30)
        params["DatePosted"] = days

        headers = {
            "Authorization-Key": Config.USAJOBS_API_KEY,
            "User-Agent": Config.USAJOBS_EMAIL,
            "Host": "data.usajobs.gov",
        }

        resp = requests.get(
            "https://data.usajobs.gov/api/search",
            headers=headers,
            params=params,
            timeout=10,
        )
        self._track_response(resp)
        resp.raise_for_status()
        data = resp.json()

        results = []
        search_result = data.get("SearchResult", {})
        for item in search_result.get("SearchResultItems", []):
            pos = item.get("MatchedObjectDescriptor", {})

            title = pos.get("PositionTitle", "")
            org = pos.get("OrganizationName", "")
            description = pos.get("QualificationSummary", "") or pos.get("UserArea", {}).get("Details", {}).get("MajorDuties", "")

            # Location
            locations = pos.get("PositionLocation", [])
            location_str = ", ".join(
                loc.get("LocationName", "") for loc in locations[:3]
            ) if locations else ""

            # Remote status
            remote_indicator = pos.get("PositionRemoteIndicator", False)
            is_remote = remote_indicator is True or str(remote_indicator).lower() == "true"

            # Salary
            salary_min = None
            salary_max = None
            remuneration = pos.get("PositionRemuneration", [])
            if remuneration:
                try:
                    salary_min = float(remuneration[0].get("MinimumRange", 0))
                    salary_max = float(remuneration[0].get("MaximumRange", 0))
                except (ValueError, TypeError, IndexError):
                    pass

            # Apply URL
            apply_url = pos.get("ApplyURI", [""])[0] if pos.get("ApplyURI") else pos.get("PositionURI", "")

            # Posted date
            pub_date = pos.get("PublicationStartDate", "")

            results.append(self.normalize({
                "title": title,
                "company": org,
                "location": location_str,
                "remote_status": "remote" if is_remote else "onsite",
                "description": description,
                "apply_url": apply_url,
                "salary_min": salary_min if salary_min else None,
                "salary_max": salary_max if salary_max else None,
                "posted_date": pub_date,
            }))

        return results
