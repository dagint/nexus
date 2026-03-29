from services.salary_normalizer import normalize_salary, _extract_salary_from_text


def test_normalize_hourly():
    result = normalize_salary(salary_min=25, salary_max=35, description="$25-$35 per hour")
    assert result["salary_period"] == "hourly"
    assert result["salary_annual_min"] == 52000
    assert result["salary_annual_max"] == 72800
    assert result["salary_uncertain"] is False


def test_normalize_annual_passthrough():
    result = normalize_salary(salary_min=80000, salary_max=120000)
    assert result["salary_period"] == "annual"
    assert result["salary_annual_min"] == 80000
    assert result["salary_annual_max"] == 120000
    assert result["salary_uncertain"] is False


def test_extract_range_from_text():
    result = _extract_salary_from_text("We offer $120,000 - $150,000 per year plus benefits")
    assert result is not None
    assert result["salary_min"] == 120000
    assert result["salary_max"] == 150000


def test_extract_k_format():
    result = _extract_salary_from_text("Salary: $80k-$100k")
    assert result is not None
    assert result["salary_min"] == 80000
    assert result["salary_max"] == 100000


def test_extract_hourly_from_text():
    result = _extract_salary_from_text("Pay rate: $45/hr")
    assert result is not None
    assert result["salary_period"] == "hourly"
    assert result["salary_annual_min"] == 93600


def test_no_salary():
    result = normalize_salary()
    assert result["salary_annual_min"] is None
    assert result["salary_annual_max"] is None
    assert result["salary_uncertain"] is False


def test_heuristic_detection_low_value():
    """Values under 200 are likely hourly."""
    result = normalize_salary(salary_min=50, salary_max=75)
    assert result["salary_period"] == "hourly"
    assert result["salary_uncertain"] is False


# --- New edge case tests ---


def test_annual_keyword_overrides_heuristic():
    """Description says 'per year' so $5000 should be annual, not monthly."""
    result = normalize_salary(salary_min=5000, salary_max=8000,
                              description="Stipend of $5,000-$8,000 per year")
    assert result["salary_period"] == "annual"
    assert result["salary_annual_min"] == 5000
    assert result["salary_annual_max"] == 8000


def test_annual_yr_keyword():
    """The /yr hint should force annual classification."""
    result = normalize_salary(salary_min=3000, salary_max=5000,
                              description="Pays $3,000-$5,000/yr")
    assert result["salary_period"] == "annual"
    assert result["salary_annual_min"] == 3000


def test_ambiguous_range_flagged_uncertain():
    """Values 200-500 without description context should be uncertain."""
    result = normalize_salary(salary_min=300, salary_max=400)
    assert result["salary_uncertain"] is True
    assert result["salary_annual_min"] is None  # uncertain period = no annualized value


def test_ambiguous_range_with_daily_hint():
    """Values 200-500 with daily hint should be classified as daily."""
    result = normalize_salary(salary_min=300, salary_max=400,
                              description="$300-$400 daily rate")
    assert result["salary_period"] == "daily"
    assert result["salary_uncertain"] is False


def test_sanity_check_flags_absurd_annual():
    """A monthly salary of $80000 would annualize to $960K — not flagged (under $1M).
    But $100000 monthly would annualize to $1.2M — should be flagged."""
    result = normalize_salary(salary_min=100000, salary_max=120000,
                              description="$100,000 per month")
    assert result["salary_period"] == "monthly"
    assert result["salary_uncertain"] is True  # $1.2M annual is suspect


def test_sanity_check_flags_too_low_annual():
    """Annual salary of $10,000 is below $15K threshold."""
    result = normalize_salary(salary_min=10000, salary_max=12000)
    assert result["salary_period"] == "annual"
    assert result["salary_uncertain"] is True


def test_sanity_check_normal_salary_ok():
    """$120K-$150K annual is perfectly normal."""
    result = normalize_salary(salary_min=120000, salary_max=150000)
    assert result["salary_uncertain"] is False


def test_high_daily_rate_correctly_classified():
    """$500-$800 range should be daily (above the ambiguous 200-500 range)."""
    result = normalize_salary(salary_min=500, salary_max=800)
    assert result["salary_period"] == "daily"
    assert result["salary_uncertain"] is False


def test_monthly_salary_correctly_classified():
    """$5000/month should be monthly."""
    result = normalize_salary(salary_min=5000, salary_max=7000,
                              description="$5,000-$7,000 per month")
    assert result["salary_period"] == "monthly"
    assert result["salary_annual_min"] == 60000
    assert result["salary_annual_max"] == 84000
    assert result["salary_uncertain"] is False
