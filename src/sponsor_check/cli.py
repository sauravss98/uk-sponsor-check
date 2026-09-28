"""Command-line interface.

    sponsor-check update                 # download the latest register
    sponsor-check check "Octopus Energy" # verdict for the Skilled Worker route
    sponsor-check search "octopus" -n 10 # ranked candidates
    sponsor-check salary 45000 2136      # salary against the threshold and going rate
"""

from __future__ import annotations

import argparse
import json
import sys

from .register import DEFAULT_ROUTE, Register, ensure_database
from .salary import check_salary, gbp

_ICONS = {"licensed": "YES", "licensed_other_routes": "OTHER ROUTES ONLY",
          "possible_match": "MAYBE", "not_found": "NOT FOUND"}

_SALARY_ICONS = {"meets": "YES", "below": "TOO LOW", "occupation_ineligible": "NOT ELIGIBLE",
                 "going_rate_unavailable": "NO PUBLISHED RATE",
                 "unknown_occupation": "UNKNOWN CODE"}


def _print_match(m: dict) -> None:
    where = ", ".join(x for x in (m["town"], m["county"]) if x)
    print(f"  {m['name']}  ({where})  score {m['score']}")
    for r in m["routes"]:
        print(f"      - {r['route']}  [{r['rating']}]")


def _print_salary(r: dict) -> None:
    where = f" ({r['occupation']})" if r.get("occupation") else ""
    print(f"{_SALARY_ICONS[r['verdict']]}: {gbp(r['salary'])} for occupation code "
          f"{r['soc_code']}{where}")
    if r.get("required_salary"):
        print(f"  required: {gbp(r['required_salary'])}"
              + (f", short by {gbp(r['shortfall'])}" if r.get("shortfall") else ""))
    if r.get("rule"):
        print(f"  rule: {r['rule']}")
    for o in r.get("other_options", []):
        mark = "ok " if o["meets"] else "no "
        print(f"      {mark} {o['label']}: {gbp(o['required_salary'])} - {o['condition']}")
    for n in r["notes"]:
        print(f"  * {n}")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="sponsor-check", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("update", help="download the latest register from GOV.UK")
    c = sub.add_parser("check", help="can this employer sponsor me?")
    c.add_argument("company")
    c.add_argument("--route", default=DEFAULT_ROUTE)
    c.add_argument("--json", action="store_true")
    s = sub.add_parser("search", help="list the closest register entries")
    s.add_argument("query")
    s.add_argument("-n", "--limit", type=int, default=5)
    s.add_argument("--json", action="store_true")
    sal = sub.add_parser("salary", help="does this salary meet the Skilled Worker requirement?")
    sal.add_argument("salary", type=float, help="gross annual salary offered")
    sal.add_argument("soc_code", help="4-digit SOC 2020 occupation code, e.g. 2136")
    sal.add_argument("--new-entrant", action="store_true",
                     help="apply the new entrant rate (under 26, recent graduate, postdoc)")
    sal.add_argument("--json", action="store_true")
    args = p.parse_args(argv)

    if args.cmd == "salary":
        result = check_salary(args.salary, args.soc_code, args.new_entrant)
        if args.json:
            print(json.dumps(result, indent=2))
        else:
            _print_salary(result)
        return 0 if result["verdict"] == "meets" else 1

    db = ensure_database(force=args.cmd == "update")
    reg = Register(db)

    if args.cmd == "update":
        meta = reg.meta()
        print(f"Register {meta.get('register_date') or '(date unknown)'}: "
              f"{meta['organisations']} organisations from {meta['rows']} rows.")
        return 0

    if args.cmd == "check":
        result = reg.check(args.company, args.route)
        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print(f"{_ICONS[result['verdict']]}: {args.company} / {args.route} "
                  f"(register {result['register_date']})")
            for m in result["matches"]:
                _print_match(m)
            for n in result["notes"]:
                print(f"  * {n}")
        return 0 if result["verdict"] == "licensed" else 1

    matches = [m.to_dict() for m in reg.search(args.query, args.limit)]
    if args.json:
        print(json.dumps(matches, indent=2))
    else:
        for m in matches:
            _print_match(m)
        if not matches:
            print("No matches.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
