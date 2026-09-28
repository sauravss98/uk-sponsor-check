"""Salary checks.

Expected figures are read from the shipped thresholds file rather than written into the
tests, so a refresh of the Immigration Rules data changes one file and not the test suite.
What the tests pin down is the logic: which rule applies, where the boundary sits, and
that every answer carries its date and its caveat.
"""

import pytest

from sponsor_check.salary import CAVEAT, check_salary, occupation_code, thresholds

DATA = thresholds()
GENERAL = DATA["general_thresholds"]

# A higher skilled code whose going rate sits below the general threshold, and one above it.
RATE_BELOW_THRESHOLD = "2136"  # IT quality and testing professionals
RATE_ABOVE_THRESHOLD = "1111"  # Chief executives and senior officials


def rate(code: str, key: str = "going_rate") -> int:
    value = DATA["occupations"][code][key]
    assert value, f"fixture assumption broken: {code} has no {key}"
    return value


def test_fixture_codes_still_bracket_the_general_threshold():
    assert rate(RATE_BELOW_THRESHOLD) < GENERAL["standard"] < rate(RATE_ABOVE_THRESHOLD)


def test_requirement_is_the_general_threshold_when_the_going_rate_is_lower():
    result = check_salary(GENERAL["standard"], RATE_BELOW_THRESHOLD)
    assert result["verdict"] == "meets"
    assert result["required_salary"] == GENERAL["standard"]


def test_requirement_is_the_going_rate_when_it_is_higher():
    result = check_salary(GENERAL["standard"], RATE_ABOVE_THRESHOLD)
    assert result["verdict"] == "below"
    assert result["required_salary"] == rate(RATE_ABOVE_THRESHOLD)
    assert result["shortfall"] == rate(RATE_ABOVE_THRESHOLD) - GENERAL["standard"]


@pytest.mark.parametrize("delta, verdict", [(0, "meets"), (1, "meets"), (-1, "below")])
def test_boundary(delta, verdict):
    required = check_salary(0, RATE_ABOVE_THRESHOLD)["required_salary"]
    assert check_salary(required + delta, RATE_ABOVE_THRESHOLD)["verdict"] == verdict


def test_new_entrant_rate_is_lower_and_is_reported_as_the_rule():
    standard = check_salary(0, RATE_ABOVE_THRESHOLD)
    new_entrant = check_salary(0, RATE_ABOVE_THRESHOLD, new_entrant=True)
    assert new_entrant["required_salary"] < standard["required_salary"]
    assert new_entrant["basis"] == "new_entrant"
    assert "new entrant" in new_entrant["rule"].lower()


def test_a_salary_that_fails_as_standard_can_pass_as_a_new_entrant():
    salary = rate(RATE_ABOVE_THRESHOLD, "new_entrant_rate")
    result = check_salary(salary, RATE_ABOVE_THRESHOLD)
    assert result["verdict"] == "below"
    as_new_entrant = next(o for o in result["other_options"] if o["option"] == "new_entrant")
    assert as_new_entrant["meets"]


def test_no_discount_floor_is_ever_undercut():
    """A 70% rate never drops the requirement below the published floor."""
    cheap = check_salary(0, RATE_BELOW_THRESHOLD, new_entrant=True)
    assert cheap["required_salary"] >= GENERAL["discounted_floor"]


def test_ineligible_occupation_is_not_a_salary_question():
    result = check_salary(500_000, "1112")  # elected officers and representatives
    assert result["verdict"] == "occupation_ineligible"
    assert result["required_salary"] is None


def test_occupation_without_a_published_standard_rate():
    result = check_salary(60_000, "2211")  # generalist medical practitioners: national pay scale
    assert result["verdict"] == "going_rate_unavailable"
    assert "national pay scale" in result["rule"]


def test_occupation_excluded_from_standard_rate_applications_quotes_the_guidance():
    result = check_salary(60_000, "6116")  # nannies and au pairs
    assert result["verdict"] == "going_rate_unavailable"
    assert "Not eligible for standard rate applications" in result["rule"]


def test_medium_skilled_job_is_flagged_with_its_condition():
    result = check_salary(60_000, "3111")  # laboratory technicians
    assert result["skill_level"].startswith("Medium")
    assert any("immigration salary list" in n for n in result["notes"])


def test_unknown_code():
    result = check_salary(50_000, "9999")
    assert result["verdict"] == "unknown_occupation"
    assert result["required_salary"] is None


@pytest.mark.parametrize("raw, expected", [
    ("2136", "2136"),
    (" soc 2136 ", "2136"),
    ("2136 - IT quality and testing professionals", "2136"),
    ("programmer", ""),
])
def test_occupation_code_extraction(raw, expected):
    assert occupation_code(raw) == expected


@pytest.mark.parametrize("args", [
    (50_000, RATE_ABOVE_THRESHOLD), (50_000, RATE_BELOW_THRESHOLD), (50_000, "1112"),
    (50_000, "2211"), (50_000, "9999"),
])
def test_every_verdict_carries_its_date_and_caveat(args):
    result = check_salary(*args)
    assert result["thresholds"]["effective_date"] == DATA["effective_date"]
    assert CAVEAT in result["notes"]


def test_thresholds_file_is_sourced_and_dated():
    assert DATA["source_url"].startswith("https://www.gov.uk/")
    assert len(DATA["effective_date"]) == 10
    for name, source in DATA["sources"].items():
        assert source["url"].startswith("https://www.gov.uk/"), name
        assert len(source["published"]) == 10, name


def test_every_occupation_entry_is_well_formed():
    money_keys = ("going_rate", "lower_going_rate", "new_entrant_rate", "phd_stem_rate",
                  "phd_non_stem_rate")
    for code, occ in DATA["occupations"].items():
        assert len(code) == 4 and code.isdigit()
        assert occ["job_type"]
        assert occ["skill_level"]
        for key in money_keys:
            value = occ.get(key)
            assert value is None or isinstance(value, int), f"{code}.{key}"
