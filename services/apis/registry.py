"""Job API provider registry.

To add a new API source:
1. Create a new file in services/apis/ with a class that extends JobAPIProvider
2. Add it to PROVIDER_CLASSES below

To disable an API source:
- Remove or comment out its line from PROVIDER_CLASSES
- Or just don't set its API keys (is_available() will return False)
"""

import logging

from services.apis.base import JobAPIProvider
from services.apis.jsearch import JSearchProvider
from services.apis.remotive import RemotiveProvider
from services.apis.weworkremotely import WeWorkRemotelyProvider
from services.apis.adzuna import AdzunaProvider
from services.apis.serpapi import SerpApiProvider

logger = logging.getLogger(__name__)

# === ADD OR REMOVE PROVIDERS HERE ===
PROVIDER_CLASSES: list[type[JobAPIProvider]] = [
    JSearchProvider,
    RemotiveProvider,
    WeWorkRemotelyProvider,
    AdzunaProvider,
    SerpApiProvider,
]


_provider_cache: dict[type, JobAPIProvider] = {}


def _get_instance(cls: type[JobAPIProvider]) -> JobAPIProvider:
    """Return a cached provider instance."""
    if cls not in _provider_cache:
        _provider_cache[cls] = cls()
    return _provider_cache[cls]


def get_active_providers() -> list[JobAPIProvider]:
    """Return instantiated providers that are configured and available."""
    active = []
    for cls in PROVIDER_CLASSES:
        provider = _get_instance(cls)
        if provider.is_available():
            active.append(provider)
        else:
            logger.info("Provider %s is not available (missing config)", provider.name)
    return active


def get_all_providers() -> list[JobAPIProvider]:
    """Return all registered providers regardless of availability."""
    return [_get_instance(cls) for cls in PROVIDER_CLASSES]
