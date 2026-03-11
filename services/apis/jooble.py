import requests
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from config import Config
from services.apis.base import JobAPIProvider


class JoobleProvider(JobAPIProvider):
    name = "Jooble"

    def is_available(self):
        return bool(Config.JOOBLE_API_KEY)

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
        body = {
            "keywords": query,
            "page": page,
            "searchMode": 1,  # 1 = relevance
        }

        if location:
            body["location"] = location

        if remote_only:
            body["remotejob"] = True

        days = self.DATE_RANGE_MAP.get(date_posted, 30)
        body["datecreatedfrom"] = days

        resp = requests.post(
            f"https://jooble.org/api/{Config.JOOBLE_API_KEY}",
            json=body,
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()

        results = []
        for item in data.get("jobs", []):
            title = item.get("title", "")
            company = item.get("company", "")
            location_str = item.get("location", "")
            description = item.get("snippet", "")

            # Detect remote from title/location
            searchable = f"{title} {location_str}".lower()
            is_remote = "remote" in searchable

            # Salary
            salary = item.get("salary", "")
            salary_min = None
            salary_max = None
            if salary:
                import re
                nums = re.findall(r"[\d,]+", str(salary).replace(",", ""))
                if len(nums) >= 2:
                    try:
                        salary_min = float(nums[0])
                        salary_max = float(nums[1])
                    except ValueError:
                        pass
                elif len(nums) == 1:
                    try:
                        salary_min = float(nums[0])
                    except ValueError:
                        pass

            # Employment type
            job_type = item.get("type", "").lower()
            emp_type = ""
            if "full" in job_type:
                emp_type = "fulltime"
            elif "part" in job_type:
                emp_type = "parttime"
            elif "contract" in job_type:
                emp_type = "contract"
            elif "intern" in job_type:
                emp_type = "internship"

            results.append(self.normalize({
                "title": title,
                "company": company,
                "location": location_str,
                "remote_status": "remote" if is_remote else "onsite",
                "description": description,
                "apply_url": item.get("link", ""),
                "salary_min": salary_min,
                "salary_max": salary_max,
                "posted_date": item.get("updated", ""),
                "employment_type": emp_type,
            }))

        return results
