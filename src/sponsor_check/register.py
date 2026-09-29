"""Load the register into SQLite and search it.

Design notes
------------
* The CSV has one row per (organisation, route). We group rows into organisations
  keyed on canonical name + town, so "Octopus Energy" with three routes is one result.
* Every organisation is indexed under several aliases: its full canonical name plus
  each legal/trading part (see ``normalize.aliases``).
* Lookup is exact-alias first (instant, confidence 100), then fuzzy (RapidFuzz WRatio)
  over the alias list, which is held in memory after first use.
"""

from __future__ import annotations

import csv
import os
import re
import sqlite3
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

from rapidfuzz import fuzz, process

from .normalize import aliases, canonical

DEFAULT_ROUTE = "Skilled Worker"
EXACT, STRONG, WEAK = 100, 90, 75  # score bands

_RATING = re.compile(r"\(([AB]) rating\)", re.IGNORECASE)
_DATE_IN_URL = re.compile(r"(\d{4}-\d{2}-\d{2})")

SCHEMA = """
CREATE TABLE organisations (id INTEGER PRIMARY KEY, name TEXT NOT NULL, town TEXT, county TEXT);
CREATE TABLE licences (org_id INTEGER NOT NULL REFERENCES organisations(id),
                       type_rating TEXT, route TEXT);
CREATE TABLE aliases (alias TEXT NOT NULL, org_id INTEGER NOT NULL REFERENCES organisations(id));
CREATE INDEX idx_alias ON aliases(alias);
CREATE INDEX idx_licence_org ON licences(org_id);
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
"""


def data_dir() -> Path:
    return Path(os.environ.get("SPONSOR_CHECK_HOME", Path.home() / ".cache" / "sponsor-check"))


def database_path() -> Path:
    return data_dir() / "register.sqlite3"


def _clean(value: str | None) -> str:
    value = (value or "").strip().strip(",").strip()
    return "" if value.lower() == "not set" else value


_KNOWN_HEADERS = {"organisation name": "Organisation Name", "town/city": "Town/City",
                  "county": "County", "type & rating": "Type & Rating", "route": "Route"}


def _header(h: str) -> str:
    key = h.replace("\ufeff", "").strip().lower()
    return _KNOWN_HEADERS.get(key, h.strip())


def rating_of(type_rating: str) -> str:
    if "provisional" in type_rating.lower():
        return "Provisional"
    m = _RATING.search(type_rating)
    return m.group(1).upper() if m else "Unknown"


# --------------------------------------------------------------------------- build


def build_database(csv_path: Path, db_path: Path, source_url: str = "") -> dict:
    """Parse the register CSV into a fresh SQLite database. Returns summary stats."""
    tmp = db_path.with_suffix(".building")
    tmp.unlink(missing_ok=True)
    conn = sqlite3.connect(tmp)
    conn.executescript(SCHEMA)

    org_ids: dict[tuple[str, str], int] = {}
    rows = 0
    # utf-8-sig strips the BOM GOV.UK sometimes prepends; errors="replace" survives stray bytes.
    with csv_path.open(encoding="utf-8-sig", errors="replace", newline="") as fh:
        reader = csv.DictReader(fh)
        # Tolerate header drift: stray BOMs, whitespace, case changes.
        reader.fieldnames = [_header(h) for h in (reader.fieldnames or [])]
        for rec in reader:
            name = (rec.get("Organisation Name") or "").strip()
            if not name:
                continue
            rows += 1
            town = _clean(rec.get("Town/City"))
            key = (canonical(name), canonical(town))
            org_id = org_ids.get(key)
            if org_id is None:
                cur = conn.execute(
                    "INSERT INTO organisations(name, town, county) VALUES (?,?,?)",
                    (name, town, _clean(rec.get("County"))),
                )
                org_id = org_ids[key] = cur.lastrowid
                conn.executemany(
                    "INSERT INTO aliases(alias, org_id) VALUES (?,?)",
                    [(a, org_id) for a in aliases(name)],
                )
            conn.execute(
                "INSERT INTO licences(org_id, type_rating, route) VALUES (?,?,?)",
                (org_id, (rec.get("Type & Rating") or "").strip(), (rec.get("Route") or "").strip()),
            )

    m = _DATE_IN_URL.search(source_url) or _DATE_IN_URL.search(csv_path.name)
    meta = {
        "source_url": source_url,
        "register_date": m.group(1) if m else "",
        "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "rows": str(rows),
        "organisations": str(len(org_ids)),
    }
    conn.executemany("INSERT INTO meta(key, value) VALUES (?,?)", meta.items())
    conn.commit()
    conn.close()
    tmp.replace(db_path)
    return meta


def ensure_database(max_age: timedelta = timedelta(hours=24), force: bool = False) -> Path:
    """Return a usable database path, downloading a fresh register if needed.

    If the download fails but an older database exists, the old one is kept and used.
    """
    from .fetch import download_register  # imported lazily so offline use never needs httpx

    root = data_dir()
    db_path = database_path()
    fresh = (
        db_path.exists()
        and time.time() - db_path.stat().st_mtime < max_age.total_seconds()
    )
    if fresh and not force:
        return db_path
    try:
        csv_path = root / "register.csv"
        url = download_register(csv_path)
        build_database(csv_path, db_path, source_url=url)
    except Exception:
        if not db_path.exists():
            raise
    return db_path


# --------------------------------------------------------------------------- search


@dataclass
class Match:
    name: str
    town: str
    county: str
    routes: list[dict] = field(default_factory=list)  # [{"route":..., "rating":..., "type":...}]
    score: float = 0.0
    matched_alias: str = ""

    def has_route(self, route: str) -> bool:
        return any(r["route"].lower() == route.lower() for r in self.routes)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "town": self.town,
            "county": self.county,
            "routes": self.routes,
            "score": round(self.score, 1),
        }


class Register:
    def __init__(self, db_path: Path):
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._alias_keys: list[str] | None = None
        self._alias_orgs: list[list[int]] | None = None

    # -- metadata
    def meta(self) -> dict:
        return {r["key"]: r["value"] for r in self.conn.execute("SELECT key, value FROM meta")}

    # -- internals
    def _load_aliases(self) -> None:
        index: dict[str, list[int]] = {}
        for row in self.conn.execute("SELECT alias, org_id FROM aliases"):
            index.setdefault(row["alias"], []).append(row["org_id"])
        self._alias_keys = list(index)
        self._alias_orgs = list(index.values())

    def _org(self, org_id: int, score: float, alias: str) -> Match:
        o = self.conn.execute("SELECT * FROM organisations WHERE id=?", (org_id,)).fetchone()
        routes = [
            {"route": r["route"], "rating": rating_of(r["type_rating"]), "type": r["type_rating"]}
            for r in self.conn.execute(
                "SELECT route, type_rating FROM licences WHERE org_id=? ORDER BY route", (org_id,)
            )
        ]
        return Match(o["name"], o["town"] or "", o["county"] or "", routes, score, alias)

    # -- public API
    def search(self, query: str, limit: int = 5, stop_on_exact: bool = False) -> list[Match]:
        q = canonical(query)
        if not q:
            return []
        best: dict[int, tuple[float, str]] = {}

        for row in self.conn.execute("SELECT org_id FROM aliases WHERE alias=?", (q,)):
            best[row["org_id"]] = (EXACT, q)

        if len(best) < limit and not (stop_on_exact and best):
            if self._alias_keys is None:
                self._load_aliases()
            hits = process.extract(
                q, self._alias_keys, scorer=fuzz.WRatio, processor=None,
                limit=limit * 4, score_cutoff=WEAK,
            )
            for alias, score, idx in hits:
                # Reward names that start with the query ("octopus" -> "octopus energy").
                if alias.startswith(q + " "):
                    score = max(score, STRONG + 5)
                score = min(score, EXACT - 1)  # only a true alias match earns 100
                for org_id in self._alias_orgs[idx]:
                    if org_id not in best or best[org_id][0] < score:
                        best[org_id] = (score, alias)

        ranked = sorted(best.items(), key=lambda kv: (-kv[1][0], len(kv[1][1])))[:limit]
        return [self._org(org_id, score, alias) for org_id, (score, alias) in ranked]

    def check(self, company: str, route: str = DEFAULT_ROUTE) -> dict:
        """Answer "can this company sponsor me on <route>?" with a verdict and evidence."""
        matches = self.search(company, limit=5, stop_on_exact=True)
        meta = self.meta()
        base = {"query": company, "route": route, "register_date": meta.get("register_date", "")}

        exact = [m for m in matches if m.score >= EXACT]
        strong = [m for m in matches if STRONG <= m.score < EXACT]

        if exact:
            on_route = [m for m in exact if m.has_route(route)]
            if on_route:
                verdict = "licensed"
                notes = _rating_notes(on_route, route)
            else:
                verdict = "licensed_other_routes"
                notes = [f"Licensed, but not for the {route} route."]
            candidates = on_route or exact
        elif strong:
            verdict, candidates = "possible_match", strong
            notes = [("No exact name match. Check which (if any) of these is the employer's "
                      "legal entity, e.g. on Companies House or the job ad's footer.")]
        else:
            verdict, candidates = "not_found", matches[:3]
            notes = [("Not on the register under this name. The employer may use a different "
                      "legal name, so check the job ad or Companies House before ruling it out.")]

        notes.append("Being on the register means the employer *can* sponsor, not that it will "
                     "sponsor this particular role.")
        return {**base, "verdict": verdict, "matches": [m.to_dict() for m in candidates],
                "notes": notes}


def _rating_notes(matches: list[Match], route: str) -> list[str]:
    ratings = {r["rating"] for m in matches for r in m.routes if r["route"].lower() == route.lower()}
    notes = []
    if "B" in ratings:
        notes.append("B-rated sponsor: the Home Office has downgraded this licence. B-rated "
                     "sponsors generally cannot assign new certificates of sponsorship until "
                     "they are upgraded, so ask the employer directly.")
    if "Provisional" in ratings:
        notes.append("Provisional licence (e.g. a new UK expansion). Confirm scope with the employer.")
    return notes
