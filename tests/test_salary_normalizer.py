from services.salary_normalizer import normalize_salary, _extract_salary_from_text


def test_normalize_hourly():
    result = normalize_salary(salary_min=25, salary_max=35, description="$25-$35 per hour")
    assert result["salary_period"] == "hourly"
    assert result["salary_annual_min"] == 52000
    assert result["salary_annual_max"] == 72800


def test_normalize_annual_passthrough():
    result = normalize_salary(salary_min=80000, salary_max=120000)
    assert result["salary_period"] == "annual"
    assert result["salary_annual_min"] == 80000
    assert result["salary_annual_max"] == 120000


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


def test_heuristic_detection_low_value():
    """Values under 200 are likely hourly."""
    result = normalize_salary(salary_min=50, salary_max=75)
    assert result["salary_period"] == "hourly"
