import logging
from functools import lru_cache

from geopy.geocoders import Nominatim
from geopy.distance import geodesic
from geopy.exc import GeocoderTimedOut, GeocoderUnavailable

logger = logging.getLogger(__name__)

_geocoder = None

# Minutes per mile by commute mode
SPEED_FACTORS = {
    "drive": 2,     # ~30 mph average in metro
    "transit": 4,   # ~15 mph average with stops/transfers
}


def _get_geocoder():
    global _geocoder
    if _geocoder is None:
        _geocoder = Nominatim(user_agent="nexus-job-search", timeout=5)
    return _geocoder


@lru_cache(maxsize=500)
def _geocode(location_str):
    """Geocode a location string to (lat, lon). Cached."""
    if not location_str or location_str.lower() in ("remote", "anywhere", ""):
        return None
    try:
        geo = _get_geocoder()
        result = geo.geocode(location_str)
        if result:
            return (result.latitude, result.longitude)
    except (GeocoderTimedOut, GeocoderUnavailable) as e:
        logger.warning("Geocoding failed for '%s': %s", location_str, e)
    except Exception as e:
        logger.warning("Geocoding error for '%s': %s", location_str, e)
    return None


def estimate_commute(job_location, user_location, max_commute_minutes=60, commute_mode="drive"):
    """Estimate commute feasibility between job and user locations.

    Returns dict with:
        - distance_miles: float or None
        - commute_minutes: estimated time based on commute_mode
        - is_feasible: bool (within max_commute_minutes)
        - exceeds_distance: bool (for use by distance-based post-filtering)
        - label: human-readable string
    """
    if not job_location or not user_location:
        return None

    # Skip for remote jobs
    job_loc_lower = job_location.lower()
    if any(w in job_loc_lower for w in ["remote", "anywhere", "work from home"]):
        return None

    job_coords = _geocode(job_location)
    user_coords = _geocode(user_location)

    if not job_coords or not user_coords:
        return None

    try:
        distance = geodesic(user_coords, job_coords).miles
        speed_factor = SPEED_FACTORS.get(commute_mode, 2)
        commute_minutes = round(distance * speed_factor)
        is_feasible = commute_minutes <= max_commute_minutes
        mode_label = "drive" if commute_mode == "drive" else "transit"

        if distance < 1:
            label = "Less than 1 mile"
        elif distance < 50:
            label = f"~{round(distance)} miles (~{commute_minutes} min {mode_label})"
        else:
            label = f"~{round(distance)} miles away"

        return {
            "distance_miles": round(distance, 1),
            "commute_minutes": commute_minutes,
            "is_feasible": is_feasible,
            "exceeds_distance": False,  # Set by check_commute_for_jobs
            "label": label,
        }
    except Exception as e:
        logger.warning("Distance calculation failed: %s", e)
        return None


def check_commute_for_jobs(jobs, user_location, max_commute_minutes=60,
                           commute_mode="drive", max_distance_miles=50,
                           max_geocode=25):
    """Add commute info to a list of jobs. Limits geocoding to avoid timeouts.

    Sets commute_info.exceeds_distance=True for non-remote jobs beyond max_distance_miles.
    """
    if not user_location:
        return jobs

    # Pre-geocode user location once
    user_coords = _geocode(user_location)
    if not user_coords:
        return jobs

    geocoded_count = 0

    for job in jobs:
        if job.get("remote_status") == "remote":
            job["commute_info"] = None
            continue

        job_location = job.get("location", "")
        if not job_location or job_location.lower() in ("remote", "anywhere"):
            job["commute_info"] = None
            continue

        if geocoded_count >= max_geocode:
            job["commute_info"] = None
            continue

        geocoded_count += 1
        commute = estimate_commute(job_location, user_location,
                                   max_commute_minutes, commute_mode)
        if commute and commute["distance_miles"] > max_distance_miles:
            commute["exceeds_distance"] = True
        job["commute_info"] = commute

    return jobs
