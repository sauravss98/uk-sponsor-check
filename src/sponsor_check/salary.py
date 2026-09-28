"""Skilled Worker salary checks.

A job offer has to clear two salary bars at once: a flat general threshold and the
occupation's "going rate". Which pair applies depends on the applicant, so the same
salary can pass as a new entrant and fail as a standard applicant.

Every number comes from ``data/thresholds.json``, which is scraped from the published
GOV.UK guidance by ``scripts/refresh_thresholds.py`` and carries the date it was published.
Nothing here is hardcoded from memory and nothing here touches the network: the Immigration
Rules move, so the answer is only ever as good as that file's ``effective_date``, which is
returned with every result.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

DATA_FILE = Path(__file__).parent / "data" / "thresholds.json"

_SOC = re.compile(r"\d{4}")

# Each way of qualifying pays the higher of a floor and a discounted going rate.
# rate_key/floor_key index the occupation entry and the general thresholds in the data file.
OPTIONS: dict[str, dict[str, str]] = {
    "standard": {
        "label": "Standard rate",
        "rate_key": "going_rate",
        "rate_name": "going rate",
        "floor_key": "standard",
        "condition": "the usual requirement",
    },
    "new_entrant": {
        "label": "New entrant rate (70% of the going rate)",
        "rate_key": "new_entrant_rate",
        "rate_name": "new entrant rate",
        "floor_key": "discounted_floor",
        "condition": "if you are under 26, a recent student or graduate, in professional "
                     "training, or in an eligible postdoctoral role",
    },
    "phd_stem": {
        "label": "STEM PhD rate (80% of the going rate)",
        "rate_key": "phd_stem_rate",
        "rate_name": "STEM PhD rate",
        "floor_key": "discounted_floor",
        "condition": "if you hold a PhD in a STEM subject relevant to the job",
    },
    "phd_non_stem": {
        "label": "Non-STEM PhD rate (90% of the going rate)",
        "rate_key": "phd_non_stem_rate",
        "rate_name": "non-STEM PhD rate",
        "floor_key": "non_stem_phd_floor",
        "condition": "if you hold a PhD in a non-STEM subject relevant to the job",
    },
    "immigration_salary_list": {
        "label": "Immigration salary list rate",
        "rate_key": "immigration_salary_list",
        "rate_name": "immigration salary list rate",
        "floor_key": "discounted_floor",
        "condition": "if the job is on the immigration salary list for the part of the UK "
                     "you will work in",
    },
    "temporary_shortage_list": {
        "label": "Temporary shortage list rate",
        "rate_key": "temporary_shortage_list",
        "rate_name": "temporary shortage list rate",
        "floor_key": "discounted_floor",
        "condition": "if the job is on the temporary shortage list",
    },
}

FLOOR_LABELS = {
    "standard": "general salary threshold",
    "discounted_floor": "floor that applies to every discounted rate",
    "non_stem_phd_floor": "floor that applies to the non-STEM PhD discount",
}

UNKNOWN_CODE = ("No such occupation code in the published tables. Occupation codes are the "
                "4-digit SOC 2020 codes: look one up in the CASCOT tool, or ask the employer "
                "which code the job will be sponsored under.")

CAVEAT = ("Salary is only one requirement. The job must also be an eligible occupation, the "
          "employer must hold a sponsor licence, and the employer decides whether to sponsor. "
          "Confirm the figures with the employer. This is not immigration advice.")


@lru_cache(maxsize=1)
def thresholds() -> dict[str, Any]:
    """The published thresholds, loaded once."""
    return json.loads(DATA_FILE.read_text(encoding="utf-8"))


def gbp(amount: float | None) -> str:
    return "unpublished" if amount is None else f"£{round(amount):,}"


def occupation_code(raw: str) -> str:
    """Pull the 4-digit code out of user input such as '2136', 'SOC 2136' or '2136 - dev'."""
    m = _SOC.search(str(raw))
    return m.group(0) if m else ""


def _rate_for(occ: dict, option: str) -> int | None:
    """The going rate an option uses, or None when nothing is published for it."""
    value = occ.get(OPTIONS[option]["rate_key"])
    if isinstance(value, dict):  # the list tables publish their own required rate
        return value.get("rate")
    return value


def _required(occ: dict, option: str) -> int | None:
    rate = _rate_for(occ, option)
    if rate is None:
        return None
    return max(thresholds()["general_thresholds"][OPTIONS[option]["floor_key"]], rate)


def _source() -> dict[str, str]:
    data = thresholds()
    return {"effective_date": data["effective_date"], "source_url": data["source_url"]}


def _skill_notes(occ: dict) -> list[str]:
    notes: list[str] = []
    skill = occ.get("skill_level", "")
    if skill.startswith("Medium"):
        notes.append(f"Occupation skill level: \"{skill}\". Medium skilled jobs are only "
                     "eligible if they are on the immigration salary list or the temporary "
                     "shortage list, or you are extending in the same occupation.")
    for key, label in (("immigration_salary_list", "immigration salary list"),
                       ("temporary_shortage_list", "temporary shortage list")):
        listed = occ.get(key)
        if listed:
            where = f" ({listed['areas']})" if listed.get("areas") else ""
            notes.append(f"On the {label}{where}: {listed['job_types']}")
    return notes


def check_salary(salary: float, soc_code: str, new_entrant: bool = False) -> dict:
    """Compare a salary with the Skilled Worker requirement for an occupation code.

    ``salary`` is the gross annual salary offered, ``soc_code`` the 4-digit SOC 2020
    occupation code. Set ``new_entrant`` for an applicant on the new entrant rate.
    """
    code = occupation_code(soc_code)
    data = thresholds()
    option = "new_entrant" if new_entrant else "standard"
    result: dict[str, Any] = {
        "salary": salary,
        "soc_code": code or str(soc_code).strip(),
        "route": data["route"],
        "basis": option,
        "thresholds": _source(),
    }

    occ = data["occupations"].get(code)
    if occ is None:
        return {**result, "verdict": "unknown_occupation", "required_salary": None,
                "rule": "", "notes": [UNKNOWN_CODE, *_closing_notes(data)]}

    result |= {
        "occupation": occ.get("job_type", ""),
        "skill_level": occ.get("skill_level", ""),
        "general_threshold": data["general_thresholds"][OPTIONS[option]["floor_key"]],
        "going_rate": _rate_for(occ, option),
    }
    notes = _skill_notes(occ)

    if occ.get("skill_level") == "Ineligible":
        return {**result, "verdict": "occupation_ineligible", "required_salary": None,
                "rule": f"Occupation code {code} is not eligible for the {data['route']} route, "
                        "whatever the salary.",
                "notes": [*notes, *_closing_notes(data)]}

    required = _required(occ, option)
    if required is None:
        published = occ.get(f"{OPTIONS[option]['rate_key']}_note")
        reason = (f'The going rates table says: "{published}".' if published else
                  f"No {OPTIONS[option]['label'].lower()} is published for occupation code "
                  f"{code}. Some healthcare and education jobs take their going rate from a "
                  "national pay scale instead.")
        return {**result, "verdict": "going_rate_unavailable", "required_salary": None,
                "rule": reason,
                "notes": [*notes, *_pay_scale_notes(occ), *_closing_notes(data)]}

    meets = salary >= required
    result |= {
        "verdict": "meets" if meets else "below",
        "required_salary": required,
        "shortfall": 0 if meets else round(required - salary, 2),
        "rule": (f"{OPTIONS[option]['label']}: the higher of the "
                 f"{gbp(result['general_threshold'])} "
                 f"{FLOOR_LABELS[OPTIONS[option]['floor_key']]} and the "
                 f"{gbp(result['going_rate'])} {OPTIONS[option]['rate_name']} for occupation "
                 f"code {code} ({occ.get('job_type', '')})."),
    }
    notes.append(f"Going rates assume a {data['hours_per_week_basis']}-hour working week and "
                 "are pro-rated for other working patterns, so part-time work needs the same "
                 "hourly rate, not the same salary.")
    notes += _closing_notes(data)
    return {**result, "other_options": _other_options(occ, salary, option), "notes": notes}


def _closing_notes(data: dict) -> list[str]:
    """Every answer ends with where the numbers came from and what they do not mean."""
    return [(f"Thresholds published {data['effective_date']} ({data['source_url']}). "
             "They change with the Immigration Rules."), CAVEAT]


def _pay_scale_notes(occ: dict) -> list[str]:
    notes = []
    if "going_rate" not in occ:
        for url in thresholds().get("national_pay_scale_urls", []):
            notes.append(f"National pay scales: {url}")
    if occ.get("lower_going_rate"):
        notes.append(f"A lower going rate of {gbp(occ['lower_going_rate'])} is published for "
                     "this code. It applies to Health and Care Worker visas and to people "
                     "sponsored continuously since before 4 April 2024.")
    return notes


def _other_options(occ: dict, salary: float, chosen: str) -> list[dict]:
    """The other ways this salary could qualify, so a near miss is not reported as a dead end."""
    out = []
    for option, spec in OPTIONS.items():
        if option == chosen:
            continue
        required = _required(occ, option)
        if required is None:
            continue
        out.append({
            "option": option,
            "label": spec["label"],
            "condition": spec["condition"],
            "required_salary": required,
            "meets": salary >= required,
        })
    return out
