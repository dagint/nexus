import hashlib
import json
import logging
import threading
import time
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor, as_completed

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
_executor = ThreadPoolExecutor(max_workers=10)


class APIError(Exception):
    pass


def search_all(query, location, remote_only=False, date_posted="month", page=1, employment_type=""):
    """Search all configured job APIs and return unified results."""
    cache_key = _cache_key(query, location, remote_only, date_posted, page, employment_type)
    cached = _cache.get(cache_key)
    if cached is not None:
        logger.info("Cache hit for query=%s (cache size: %d)", query, _cache.size)
        return cached

    providers = get_active_providers()
    logger.info("Searching %d active providers: %s",
                len(providers), [p.name for p in providers])

    all_results = []
    submit_time = time.time()
    futures = {}
    for provider in providers:
        future = _executor.submit(
            provider.search, query, location, remote_only, date_posted, page, employment_type,
        )
        futures[future] = provider.name

    from services.usage_tracker import log_search_call

    for future in as_completed(futures):
        source = futures[future]
        try:
            results = future.result()
            elapsed_ms = int((time.time() - submit_time) * 1000)
            logger.info("API %s returned %d results in %dms", source, len(results), elapsed_ms)
            all_results.extend(results)
            try:
                log_search_call(source, elapsed_ms, success=True)
            except Exception:
                pass
        except Exception as e:
            elapsed_ms = int((time.time() - submit_time) * 1000)
            logger.error("API %s failed: %s", source, e)
            try:
                log_search_call(source, elapsed_ms, success=False, error_message=str(e)[:200])
            except Exception:
                pass

    # Lightweight dedup by job_key only; full similarity dedup happens in deduplicator.py
    seen_keys = set()
    unique_results = []
    for job in all_results:
        if job["job_key"] not in seen_keys:
            seen_keys.add(job["job_key"])
            unique_results.append(job)
    all_results = unique_results

    # Post-filter by employment type for providers that don't support native filtering
    if employment_type:
        filtered = [j for j in all_results if not j.get("employment_type") or j["employment_type"] == employment_type]
        logger.info("Employment type filter '%s': %d -> %d results", employment_type, len(all_results), len(filtered))
        all_results = filtered

    _cache.set(cache_key, all_results)
    logger.info("Total results after dedup: %d (cache size: %d)", len(all_results), _cache.size)
    return all_results


_processed_cache = _LRUCache()


def search_and_process(query, location, remote_only=False, date_posted="month", page=1, employment_type=""):
    """Search all APIs and run shared processing (analyze, normalize, dedup, enrich).

    Returns processed jobs ready for per-user scoring. Results are cached
    separately from raw API results so the expensive processing pipeline
    (analysis, salary normalization, deduplication, enrichment) is skipped
    on repeat searches.
    """
    import copy

    cache_key = _cache_key("processed", query, location, remote_only, date_posted, page, employment_type)
    cached = _processed_cache.get(cache_key)
    if cached is not None:
        logger.info("Processed cache hit for query=%s", query)
        return copy.deepcopy(cached)

    from services.job_analyzer import analyze_jobs
    from services.deduplicator import deduplicate_cross_source, flag_staleness, flag_staffing_agencies
    from services.salary_normalizer import normalize_salary
    from services.company_enricher import enrich_jobs

    jobs = search_all(query, location, remote_only, date_posted, page, employment_type)

    jobs = analyze_jobs(jobs)

    for job in jobs:
        salary_info = normalize_salary(
            job.get("salary_min"), job.get("salary_max"), job.get("description", "")
        )
        job["salary_annual_min"] = salary_info.get("salary_annual_min")
        job["salary_annual_max"] = salary_info.get("salary_annual_max")
        job["salary_period"] = salary_info.get("salary_period", "annual")
        if not job.get("salary_min") and salary_info.get("salary_min"):
            job["salary_min"] = salary_info["salary_min"]
            job["salary_max"] = salary_info.get("salary_max")

    jobs = deduplicate_cross_source(jobs)
    jobs = flag_staleness(jobs)
    jobs = flag_staffing_agencies(jobs)

    try:
        jobs = enrich_jobs(jobs)
    except Exception as e:
        logger.warning("Company enrichment failed: %s", e)

    _processed_cache.set(cache_key, jobs)
    logger.info("Processed and cached %d jobs for query=%s", len(jobs), query)
    return copy.deepcopy(jobs)


def get_unavailable_sources():
    """Return names of providers that aren't configured."""
    all_p = get_all_providers()
    return [p.name for p in all_p if not p.is_available()]


def _cache_key(*args):
    return hashlib.md5(json.dumps(args, sort_keys=True).encode()).hexdigest()
