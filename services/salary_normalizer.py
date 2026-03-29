import re
import logging

logger = logging.getLogger(__name__)

# Multipliers to convert to annual
PERIOD_MULTIPLIERS = {
    "annual": 1,
    "yearly": 1,
    "monthly": 12,
    "weekly": 52,
    "hourly": 2080,
    "daily": 260,
}


def normalize_salary(salary_min=None, salary_max=None, description=""):
    """Normalize salary values to annual. Extract from description if not provided."""
    result = {
        "salary_min": salary_min,
        "salary_max": salary_max,
        "salary_raw": "",
        "salary_period": "annual",
        "salary_annual_min": None,
        "salary_annual_max": None,
        "salary_uncertain": False,
    }

    # If we have values, try to detect period and normalize
    if salary_min or salary_max:
        period = _detect_period_from_values(salary_min, salary_max, description)
        if period == "uncertain":
            result["salary_uncertain"] = True
            result["salary_period"] = "annual"
            return result
        result["salary_period"] = period
        multiplier = PERIOD_MULTIPLIERS.get(period, 1)
        if salary_min:
            result["salary_annual_min"] = round(salary_min * multiplier)
        if salary_max:
            result["salary_annual_max"] = round(salary_max * multiplier)
        # Sanity check: flag obviously wrong annualized values
        result["salary_uncertain"] = _is_salary_suspect(
            result["salary_annual_min"], result["salary_annual_max"]
        )
        return result

    # Try to extract from description
    extracted = _extract_salary_from_text(description)
    if extracted:
        result.update(extracted)
        if "salary_uncertain" not in extracted:
            result["salary_uncertain"] = _is_salary_suspect(
                result.get("salary_annual_min"), result.get("salary_annual_max")
            )

    return result


def _detect_period_from_values(salary_min, salary_max, description=""):
    """Guess salary period from the values and context."""
    val = salary_max or salary_min or 0

    # Check description for explicit period hints (these override the heuristic)
    desc_lower = description.lower()
    if any(p in desc_lower for p in ["/hr", "/hour", "per hour", "hourly rate"]):
        return "hourly"
    if any(p in desc_lower for p in ["/yr", "/year", "per year", "per annum",
                                      "annual", "annually"]):
        return "annual"
    if any(p in desc_lower for p in ["/month", "per month", "monthly"]):
        return "monthly"
    if any(p in desc_lower for p in ["/week", "per week", "weekly"]):
        return "weekly"
    if any(p in desc_lower for p in ["/day", "per day", "daily rate"]):
        return "daily"

    # Heuristic from value ranges
    if val < 200:  # Likely hourly
        return "hourly"
    if 200 <= val < 500:  # Ambiguous range without description context
        return "uncertain"
    if 500 <= val < 1000:  # Likely daily
        return "daily"
    if 1000 <= val < 10000:  # Likely monthly or bi-weekly
        return "monthly"
    # >= 10000 assume annual
    return "annual"


def _is_salary_suspect(annual_min, annual_max):
    """Flag annualized values that look obviously wrong."""
    for val in [annual_min, annual_max]:
        if val is not None:
            if val > 1_000_000 or (val > 0 and val < 15_000):
                return True
    return False


def _extract_salary_from_text(text):
    """Extract salary range from job description text."""
    if not text:
        return None

    # Pattern: $XX,XXX - $XX,XXX or $XXk - $XXk
    patterns = [
        # $120,000 - $150,000 /yr
        r'\$\s*([\d,]+(?:\.\d+)?)\s*[kK]?\s*[-\u2013to]+\s*\$?\s*([\d,]+(?:\.\d+)?)\s*[kK]?\s*(?:per\s+)?(year|yr|annual|hour|hr|month|mo|week|wk|day)?',
        # $120k-$150k
        r'\$\s*(\d+(?:\.\d+)?)\s*[kK]\s*[-\u2013to]+\s*\$?\s*(\d+(?:\.\d+)?)\s*[kK]\s*(?:per\s+)?(year|yr|annual|hour|hr|month|mo|week|wk|day)?',
        # $120,000/yr (single value)
        r'\$\s*([\d,]+(?:\.\d+)?)\s*[kK]?\s*(?:per\s+|/)?(year|yr|annual|annually|hour|hr|hourly|month|monthly|mo|week|weekly|wk|day|daily)',
    ]

    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            groups = match.groups()
            # Check if 'k' appears in the matched text (e.g., "$80k")
            has_k = bool(re.search(r'[kK]', match.group(0)))
            val1 = _parse_salary_value(groups[0], assume_thousands=has_k)
            val2 = _parse_salary_value(groups[1], assume_thousands=has_k) if len(groups) > 2 and groups[1] else None
            period_hint = groups[-1] if groups[-1] else ""

            period = _period_from_hint(period_hint)
            multiplier = PERIOD_MULTIPLIERS.get(period, 1)

            if val2 and val2 > val1:
                return {
                    "salary_min": val1,
                    "salary_max": val2,
                    "salary_raw": match.group(0),
                    "salary_period": period,
                    "salary_annual_min": round(val1 * multiplier),
                    "salary_annual_max": round(val2 * multiplier),
                }
            else:
                return {
                    "salary_min": val1,
                    "salary_max": val2 or val1,
                    "salary_raw": match.group(0),
                    "salary_period": period,
                    "salary_annual_min": round(val1 * multiplier),
                    "salary_annual_max": round((val2 or val1) * multiplier),
                }

    return None


def _parse_salary_value(val_str, assume_thousands=False):
    """Parse a salary string like '120,000' or '45' into a number."""
    if not val_str:
        return None
    clean = val_str.replace(",", "").strip()
    try:
        num = float(clean)
        # Only multiply by 1000 when explicitly told (e.g., k-format pattern)
        if assume_thousands and num < 1000 and "," not in val_str:
            num *= 1000
        return num
    except ValueError:
        return None


def _period_from_hint(hint):
    """Convert period hint string to normalized period."""
    if not hint:
        return "annual"
    h = hint.lower().strip()
    if h in ("hour", "hr", "hourly"):
        return "hourly"
    if h in ("month", "mo", "monthly"):
        return "monthly"
    if h in ("week", "wk", "weekly"):
        return "weekly"
    if h in ("day", "daily"):
        return "daily"
    return "annual"
