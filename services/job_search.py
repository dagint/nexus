import hashlib
import json
import logging
import threading
import time
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor, as_completed
from difflib import SequenceMatcher

from services.apis.registry import get_active_providers, get_all_providers

logger = logging.getLogger(__name__)

CACHE_TTL = 900  # 15 minutes
CACHE_MAX_SIZE = 100  # Max cached queries


class _LRUCache:
    """Thread-safe LRU cache with TTL and max size."""

    def __init__(self, max_size=CACHE_MAX_SIZE, ttl=CACHE_TTL):
        self._data = OrderedDict()
        self._lock = threading.Lock()
        self.max_size = max_size
        self.ttl = ttl

    def get(self, key):
        with self._lock:
            if key not in self._data:
                return None
            value, ts = self._data[key]
            if time.time() - ts > self.ttl:
                del self._data[key]
                return None
            self._data.move_to_end(key)
            return value

    def set(self, key, value):
        with self._lock:
            if key in self._data:
                self._data.move_to_end(key)
            self._data[key] = (value, time.time())
            while len(self._data) > self.max_size:
                evicted_key, _ = self._data.popitem(last=False)
                logger.debug("Cache evicted key %s", evicted_key)

    @property
    def size(self):
        return len(self._data)

    def clear(self):
        with self._lock:
            self._data.clear()


_cache = _LRUCache()


class APIError(Exception):
    pass


def search_all(query, location, remote_only=False, date_posted="month", page=1):
    """Search all configured job APIs and return unified results."""
    cache_key = _cache_key(query, location, remote_only, date_posted, page)
    cached = _cache.get(cache_key)
    if cached is not None:
        logger.info("Cache hit for query=%s (cache size: %d)", query, _cache.size)
        return cached

    providers = get_active_providers()
    logger.info("Searching %d active providers: %s",
                len(providers), [p.name for p in providers])

    all_results = []
    with ThreadPoolExecutor(max_workers=len(providers) or 1) as executor:
        futures = {}
        for provider in providers:
            future = executor.submit(
                provider.search, query, location, remote_only, date_posted, page,
            )
            futures[future] = provider.name

        for future in as_completed(futures):
            source = futures[future]
            try:
                start = time.time()
                results = future.result()
                duration = time.time() - start
                logger.info("API %s returned %d results in %.2fs", source, len(results), duration)
                all_results.extend(results)
            except Exception as e:
                logger.error("API %s failed: %s", source, e)

    all_results = _deduplicate(all_results)

    _cache.set(cache_key, all_results)
    logger.info("Total results after dedup: %d (cache size: %d)", len(all_results), _cache.size)
    return all_results


def get_unavailable_sources():
    """Return names of providers that aren't configured."""
    all_p = get_all_providers()
    return [p.name for p in all_p if not p.is_available()]


def _cache_key(*args):
    return hashlib.md5(json.dumps(args, sort_keys=True).encode()).hexdigest()


def _deduplicate(jobs):
    """Remove duplicate jobs by normalized title + company similarity."""
    seen = []
    result = []

    for job in jobs:
        key = (job["title"].lower().strip(), job["company"].lower().strip())
        is_dup = False
        for seen_key, seen_idx in seen:
            title_sim = SequenceMatcher(None, key[0], seen_key[0]).ratio()
            company_sim = SequenceMatcher(None, key[1], seen_key[1]).ratio()
            if title_sim >= 0.85 and company_sim >= 0.85:
                if len(job.get("description", "")) > len(result[seen_idx].get("description", "")):
                    result[seen_idx] = job
                is_dup = True
                break
        if not is_dup:
            seen.append((key, len(result)))
            result.append(job)

    return result
