"""Rebuild ``src/sponsor_check/data/thresholds.json`` from the current GOV.UK guidance.

    python scripts/refresh_thresholds.py

Salary thresholds and going rates change with the Immigration Rules, so they are never
written by hand: this script scrapes them from the published guidance through the GOV.UK
Content API and records the source URL and publication date of every table it used.
Run it after a rules change, check the diff, then commit the JSON. It needs internet;
nothing at runtime does, and the tests never call it.

If GOV.UK restructures a page, the script raises instead of writing a half-empty file.
"""

from __future__ import annotations

import json
import re
import sys
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

import httpx

API = "https://www.gov.uk/api/content"
HEADERS = {"User-Agent": "sponsor-check refresh_thresholds (+https://github.com/sauravss98)"}
OUT = Path(__file__).resolve().parents[1] / "src" / "sponsor_check" / "data" / "thresholds.json"

GUIDE = "/skilled-worker-visa"
TABLE_PAGES = {
    "eligible_occupations": "/government/publications/skilled-worker-visa-eligible-occupations"
                            "/skilled-worker-visa-eligible-occupations-and-codes",
    "going_rates": "/government/publications/skilled-worker-visa-going-rates-for-eligible-"
                   "occupations/skilled-worker-visa-going-rates-for-eligible-occupation-codes",
    "new_entrant": "/government/publications/skilled-worker-visa-eligible-salary-if-youre-under-"
                   "26-studying-training-or-in-a-postdoctoral-role/skilled-worker-visa-minimum-"
                   "salary-if-youre-under-26-studying-training-or-in-a-postdoctoral-role",
    "phd_discount": "/government/publications/skilled-worker-visa-jobs-that-qualify-for-a-phd-"
                    "salary-discount/skilled-worker-visa-jobs-that-qualify-for-a-phd-salary-"
                    "discount",
    "immigration_salary_list": "/government/publications/skilled-worker-visa-immigration-salary-"
                               "list/skilled-worker-visa-immigration-salary-list",
    "temporary_shortage_list": "/government/publications/skilled-worker-visa-temporary-shortage-"
                               "list/skilled-worker-visa-temporary-shortage-list",
}

# Each general threshold is pulled out of the prose by an anchored pattern. If the wording
# changes the match fails loudly, which is the point: a silently missing threshold would be
# worse than no data file at all.
GENERAL_THRESHOLDS = {
    "standard": ("your-job", r"standard[^<]{0,30}salary rate of at least .([\d,]+)"),
    "discounted_floor": (
        "when-you-can-be-paid-less",
        r"at least .([\d,]+) per year and you meet one of the following",
    ),
    "non_stem_phd_floor": (
        "when-you-can-be-paid-less",
        r"non-STEM qualification[\s\S]{0,300}?at least .([\d,]+) a year",
    ),
}

SOC_CODE = re.compile(r"^\d{4}$")
MONEY = re.compile(r"£\s*([\d,]+)")


class _TableParser(HTMLParser):
    """Collect every table on a page as a list of rows of plain-text cells."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tables: list[list[list[str]]] = []
        self._row: list[str] | None = None
        self._cell: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "table":
            self.tables.append([])
        elif tag == "tr" and self.tables:
            self._row = []
        elif tag in ("td", "th") and self._row is not None:
            self._cell = []
        elif tag == "br" and self._cell is not None:
            self._cell.append(" / ")

    def handle_endtag(self, tag: str) -> None:
        if tag in ("td", "th") and self._cell is not None:
            self._row.append(re.sub(r"\s+", " ", "".join(self._cell)).strip(" /").strip())
            self._cell = None
        elif tag == "tr" and self._row is not None:
            self.tables[-1].append(self._row)
            self._row = None

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell.append(data)


def fetch(client: httpx.Client, path: str) -> dict:
    resp = client.get(API + path)
    resp.raise_for_status()
    return resp.json()


def money(cell: str) -> int | None:
    """First pound amount in a cell, e.g. '£88,100 (£45.18 per hour)' -> 88100."""
    m = MONEY.search(cell)
    return int(m.group(1).replace(",", "")) if m else None


def rate(occ: dict[str, Any], key: str, cell: str) -> None:
    """Store a rate, keeping the published wording when the cell holds words, not money.

    A few rows say "Not eligible for standard rate applications" instead of an amount.
    That sentence is the answer for those occupations, so it is kept verbatim.
    """
    occ[key] = money(cell)
    if occ[key] is None and cell:
        occ[f"{key}_note"] = cell


def rows_of(page: dict, table: int = 0) -> list[list[str]]:
    """Data rows (those keyed by a 4-digit occupation code) of one table on a page."""
    parser = _TableParser()
    parser.feed(page["details"]["body"])
    if len(parser.tables) <= table:
        raise SystemExit(f"expected at least {table + 1} tables on {page['base_path']}")
    return [r for r in parser.tables[table] if r and SOC_CODE.match(r[0])]


def guide_thresholds(guide: dict) -> dict[str, int]:
    parts = {p["slug"]: p["body"] for p in guide["details"]["parts"]}
    out: dict[str, int] = {}
    for key, (slug, pattern) in GENERAL_THRESHOLDS.items():
        m = re.search(pattern, parts.get(slug, ""))
        if not m:
            raise SystemExit(f"could not find the {key} threshold in {GUIDE}/{slug} - "
                             "the guidance wording changed, update the pattern by hand")
        out[key] = int(m.group(1).replace(",", ""))
    return out


def pay_scale_urls(going_rates: dict) -> list[str]:
    """Where healthcare and education jobs get their going rate instead of the table."""
    found = re.findall(r'href="(https://www\.gov\.uk/[^"]*national-pay-scales[^"]*)"',
                       going_rates["details"]["body"])
    return sorted(set(found))


def hours_basis(going_rates: dict) -> float:
    """The working week the published annual rates assume, for the pro-rata caveat."""
    m = re.search(r"based on a ([\d.]+)[- ]hour working week", going_rates["details"]["body"])
    if not m:
        raise SystemExit("could not find the working-week basis on the going rates page")
    return float(m.group(1))


def main() -> int:
    with httpx.Client(headers=HEADERS, timeout=60.0, follow_redirects=True) as client:
        guide = fetch(client, GUIDE)
        pages = {name: fetch(client, path) for name, path in TABLE_PAGES.items()}

    occupations: dict[str, dict[str, Any]] = {}

    def entry(code: str) -> dict[str, Any]:
        return occupations.setdefault(code, {})

    for code, job_type, _titles, skill in (r[:4] for r in rows_of(pages["eligible_occupations"])):
        entry(code).update(job_type=job_type, skill_level=skill)

    for code, job_type, _titles, standard, lower in (
        r[:5] for r in rows_of(pages["going_rates"])
    ):
        occ = entry(code)
        occ.setdefault("job_type", job_type)
        rate(occ, "going_rate", standard)
        rate(occ, "lower_going_rate", lower)

    # Table 0 has 70% of both the standard and the lower going rate; table 1 covers the
    # occupations that only have a lower going rate.
    for code, _job, _titles, standard, lower in (r[:5] for r in rows_of(pages["new_entrant"])):
        occ = entry(code)
        rate(occ, "new_entrant_rate", standard)
        occ["new_entrant_lower_rate"] = money(lower)
    for code, _job, _titles, lower in (r[:4] for r in rows_of(pages["new_entrant"], table=1)):
        entry(code).setdefault("new_entrant_lower_rate", money(lower))

    for code, _job, _titles, non_stem, stem, non_stem_low, stem_low in (
        r[:7] for r in rows_of(pages["phd_discount"])
    ):
        entry(code).update(
            phd_non_stem_rate=money(non_stem), phd_stem_rate=money(stem),
            phd_non_stem_lower_rate=money(non_stem_low), phd_stem_lower_rate=money(stem_low),
        )

    for code, jobs, areas, standard, lower in (
        r[:5] for r in rows_of(pages["immigration_salary_list"])
    ):
        entry(code)["immigration_salary_list"] = {
            "job_types": jobs, "areas": areas, "rate": money(standard), "lower_rate": money(lower),
        }

    for code, jobs, standard, lower in (r[:4] for r in rows_of(pages["temporary_shortage_list"])):
        entry(code)["temporary_shortage_list"] = {
            "job_types": jobs, "rate": money(standard), "lower_rate": money(lower),
        }

    sources = {
        name: {
            "url": "https://www.gov.uk" + page["base_path"],
            "published": (page.get("public_updated_at") or "")[:10],
        }
        for name, page in pages.items()
    }
    sources["salary_requirements"] = {
        "url": "https://www.gov.uk/skilled-worker-visa/your-job",
        "published": (guide.get("public_updated_at") or "")[:10],
    }

    data = {
        "route": "Skilled Worker",
        "effective_date": max(s["published"] for s in sources.values()),
        "source_url": "https://www.gov.uk/skilled-worker-visa/your-job",
        "sources": dict(sorted(sources.items())),
        "general_thresholds": guide_thresholds(guide),
        "hours_per_week_basis": hours_basis(pages["going_rates"]),
        "national_pay_scale_urls": pay_scale_urls(pages["going_rates"]),
        "occupations": dict(sorted(occupations.items())),
    }

    with_rate = sum(1 for o in data["occupations"].values() if o.get("going_rate"))
    if with_rate < 100:
        raise SystemExit(f"only {with_rate} occupations had a going rate - parsing looks broken")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    tmp = OUT.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(OUT)
    print(f"wrote {OUT} - {len(data['occupations'])} occupations, {with_rate} with a going rate, "
          f"effective {data['effective_date']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
