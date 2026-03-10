"""Base class for job search API providers.

To add a new API:
1. Create a new file in services/apis/ (e.g., myapi.py)
2. Subclass JobAPIProvider
3. Implement name, is_available(), and search()
4. Add it to PROVIDER_CLASSES in services/apis/registry.py

That's it - the rest is handled automatically.
"""

import hashlib
import logging
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)


class JobAPIProvider(ABC):
    """Base class all job API providers must implement."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Display name for this API source (e.g., 'JSearch', 'Remotive')."""
        ...

    @abstractmethod
    def is_available(self) -> bool:
        """Return True if this provider is configured and ready to use.
        Check for required API keys, etc."""
        ...

    @abstractmethod
    def search(self, query: str, location: str, remote_only: bool,
               date_posted: str, page: int, employment_type: str = "") -> list[dict]:
        """Search for jobs. Return a list of normalized job dicts.
        Use self.normalize() to convert raw API data into the standard schema.
        employment_type: '', 'fulltime', 'parttime', 'contract', 'internship'"""
        ...

    def normalize(self, raw: dict) -> dict:
        """Convert raw API data into the standard job schema."""
        title = raw.get("title", "Unknown Title")
        company = raw.get("company", "Unknown Company")
        return {
            "title": title,
            "company": company,
            "location": raw.get("location", ""),
            "remote_status": raw.get("remote_status", "unknown"),
            "description": raw.get("description", ""),
            "apply_url": raw.get("apply_url", ""),
            "salary_min": raw.get("salary_min"),
            "salary_max": raw.get("salary_max"),
            "posted_date": raw.get("posted_date", ""),
            "employment_type": raw.get("employment_type", ""),
            "source": self.name,
            "job_key": self._make_key(title, company),
        }

    def _make_key(self, title: str, company: str) -> str:
        normalized = f"{title.lower().strip()}|{company.lower().strip()}|{self.name}"
        return hashlib.md5(normalized.encode()).hexdigest()[:16]
