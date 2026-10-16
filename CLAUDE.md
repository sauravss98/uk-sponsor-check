# CLAUDE.md

Context for Claude Code working in this repo. Read this before making changes.

## What this is

`sponsor-check` checks whether a UK employer holds a Home Office sponsor licence, using the
official "Register of licensed sponsors: workers" CSV from GOV.UK. It ships as:

- an **MCP server** (`sponsor-check-mcp`, stdio) used from Claude Code / Claude Desktop
- a **CLI** (`sponsor-check update | check | search`)

It is an open-source portfolio project by Saurav Suresh (github.com/sauravss98). Code quality,
tests and a clean README matter as much as features, because recruiters and interviewers read it.

## Commands

```bash
pip install -e ".[dev]"          # set up (use a venv)
pytest -q                        # tests: offline, use tests/fixtures/register_sample.csv
ruff check .                     # lint (must pass; CI runs it)
sponsor-check update             # download today's register (needs internet)
sponsor-check check "Company"    # verdict; exit code 0 only when licensed
sponsor-check search "query" -n 10 --json
sponsor-check salary 45000 2136  # salary vs threshold + going rate; exit 0 only when it meets
python scripts/refresh_thresholds.py   # rebuild thresholds.json from GOV.UK (needs internet)
python scripts/check_deploy.py <url>   # after a deploy: healthz, cached latency, rate-limit spoofing
npx @modelcontextprotocol/inspector sponsor-check-mcp   # poke the MCP tools by hand
sponsor-check-api                # FastAPI backend for the web app, http://127.0.0.1:8000
cd web && npm install && npm run dev   # React frontend, http://localhost:5173 (proxies /api)
docker build -t sponsor-check . && docker run -p 8000:8000 sponsor-check   # prod container
```

Always run `pytest -q` and `ruff check .` after a change. Both must pass before you say you're done.

## Layout

```
src/sponsor_check/
  normalize.py   name canonicalisation + trading-name splitting (pure functions, no I/O)
  fetch.py       discover today's CSV URL (GOV.UK Content API, HTML fallback) and download it
  register.py    CSV -> SQLite build, alias index, fuzzy search, verdict logic
  salary.py      Skilled Worker salary verdicts (pure, reads data/thresholds.json)
  data/thresholds.json   generated: general thresholds, going rates, discounts, per-SOC data
  cli.py         argparse CLI
  server.py      MCP server (4 read-only tools)
  api.py         FastAPI: /api for the web app, /v1 for the extension (thin: JSON over register.py/salary.py)
scripts/
  refresh_thresholds.py   scrapes GOV.UK to regenerate data/thresholds.json (dev only)
tests/
  fixtures/register_sample.csv   real register rows + fictional "... Test" rows
  test_normalize.py, test_register.py, test_salary.py, test_api.py, conftest.py (test DB fixture)
web/                              React (Vite + TS + Tailwind) frontend, calls api.py; see web/README.md
Dockerfile, render.yaml          one container (API + built frontend), deployed to Render free tier
.github/workflows/ci.yml         ruff + pytest on Python 3.10 / 3.12 / 3.13
```

## Data source facts

- Publication page: https://www.gov.uk/government/publications/register-of-licensed-sponsors-workers
- Updated most working days. The CSV URL changes every time (media hash + date in the filename),
  so it must be discovered, never hardcoded.
- Columns: `Organisation Name, Town/City, County, Type & Rating, Route`
- One row per (organisation, route). The same organisation can also appear twice with different
  casing (`2i Limited` / `2I LIMITED`). The build groups rows on canonical name + town.
- `Type & Rating` values look like `Worker (A rating)`, `Worker (B rating)`,
  `Temporary Worker (A rating)`, `Worker (UK Expansion Worker: Provisional )`.
- County is often the literal string `Not set` (treated as empty). Town values can have trailing
  commas. The file may start with a UTF-8 BOM; headers are normalised in `register._header`.
- ~127k organisations. Build takes a few seconds; a fuzzy lookup is ~200 ms.
- Licence: Open Government Licence v3.0. Keep the attribution in the README.

## Salary threshold facts

- `src/sponsor_check/data/thresholds.json` holds every salary figure: the general thresholds,
  each occupation's going rate and lower going rate, the discounted rates (new entrant, STEM
  and non-STEM PhD), the immigration salary list and temporary shortage list entries, and each
  code's `skill_level` (Higher Skilled / Medium Skilled / Ineligible).
- **Never write a threshold or going rate from memory.** Regenerate the file with
  `python scripts/refresh_thresholds.py`. It scrapes the current guidance through the GOV.UK
  Content API and records each table's URL and publication date, and it raises instead of
  writing a partial file when a page changes shape. Check the diff, then commit it.
- Pages used: the Skilled Worker guide (`your-job`, `when-you-can-be-paid-less`) for the flat
  thresholds, plus the going rates, eligible occupations, new entrant, PhD discount,
  immigration salary list and temporary shortage list tables.
- `weeks_per_year_basis` (52) is not stated on the going-rates page, so `weeks_basis()` derives
  it from the table's "£X (£Y per hour)" pairs (all 531 agreed on 2026-10-16) and raises if they
  ever disagree. It matches Appendix Skilled Worker SW 14.3, which annualises as hourly x hours
  x 52 and counts at most 48 hours a week towards the salary thresholds.
- The requirement is always `max(floor, rate)`: the floor comes from `general_thresholds`, the
  rate from the occupation entry. Discounted rates are published per occupation, not computed
  as a percentage here.
- Some codes have no standard going rate. Healthcare and education jobs take theirs from
  national pay scales and are absent from the table; a few rows say "Not eligible for standard
  rate applications". Both give `going_rate_unavailable` with the published wording or a link,
  never an invented number.
- Every salary result carries `thresholds.effective_date`, the rule that produced the figure,
  and the "confirm with the employer, this is not immigration advice" caveat.

## Web API facts

- `api.py` is a thin FastAPI wrapper: four endpoints (`/api/check`, `/api/search`,
  `/api/salary`, `/api/register-info`) that call straight into `register.py`/`salary.py`, so
  the CLI, MCP server and web app can never disagree. Don't add matching or salary logic here;
  add it to `register.py`/`salary.py` and let this file stay thin.
- The register is provided through a `get_register()` FastAPI dependency (same
  lazy-singleton pattern as `server.py`'s `_register()`), so `test_api.py` can override it with
  `app.dependency_overrides` and point it at the fixture DB instead of the real cache. Follow
  that pattern for any new endpoint that needs the register.
- `/v1/*` (`/v1/lookup`, `/v1/salary-check`) plus `/healthz` is the stable contract for the
  Sponsor Badge extension, a separate repo (`sponsor-badge`) we can't update in lockstep. Its
  shapes are the Pydantic models in `api.py` (`LookupResult`, `SalaryFloors`): add fields, never
  rename or remove them. `/api/*` belongs to `web/` and may change with it.
  - `/v1/lookup` is `register.check()` reshaped; `possible_match` becomes `possible`. It keeps
    the `notes`, so the caveat and B-rated/provisional warnings still reach the user, but strips
    the Markdown emphasis (`*can*`) because `/v1` promises plain text.
  - `/v1/salary-check` takes only an amount (job ads rarely give a SOC code) and calls
    `salary.check_floors()`, which compares against the flat floors and says so in its notes.
    It also returns `hours_per_week_basis` and `weeks_per_year_basis` so a client can annualise
    an hourly rate without hardcoding either.
  - `_lookup` is an `lru_cache` keyed on `(Register, canonical(name, strict=True), route)`,
    cleared by `_default_register()` whenever it swaps in a newer register. The key must be the
    strict form: the loose one would make "Amazon" and "The Amazon" share an answer. Tests clear
    it in `client`.
  - slowapi limits `/v1` to `SPONSOR_CHECK_RATE_LIMIT` (default `60/minute`) per client IP,
    shared across all `/v1` endpoints, in memory (per process). Decorated endpoints need
    `request: Request` and `response: Response` params. The Dockerfile sets
    `FORWARDED_ALLOW_IPS=*` so uvicorn takes the client IP from the proxy's X-Forwarded-For.
    Tests call `limiter.reset()` in `client`.
- CORS is explicit and allowlist-based (`SPONSOR_CHECK_CORS_ORIGINS`, comma-separated; defaults
  to the Vite dev origins plus `DEV_EXTENSION_ORIGIN`, the extension's dev build, whose ID is
  pinned by the `key` in sponsor-badge's manifest). Production sets the env var, including the
  Web Store ID once it exists. `Retry-After` is exposed so a cross-origin caller can read it on
  a 429. This is the one surface here that's meant to be reachable from a browser, unlike the
  MCP server (stdio) and the CLI, so don't relax it to `*`.
- Logging: `log_request` middleware writes one JSON line per request to the
  `sponsor_check.access` logger (method, path, status, ms). Never the query string (names) or
  the client IP; health checks are skipped. `main()` turns uvicorn's access log off because it
  prints full URLs. slowapi's own warnings include the client IP, so leave the root logger
  unconfigured (slowapi's handler then discards them).
- Rate-limit client IP on Render is `(unverified)`: Render's docs don't say whether it replaces or
  appends to a client-sent `X-Forwarded-For`, and uvicorn with `FORWARDED_ALLOW_IPS=*` trusts the
  first entry. `scripts/check_deploy.py` measures it against the live URL. Locally it always
  reports spoofable, because uvicorn trusts headers from 127.0.0.1.
- `pyproject.toml`'s `api` extra (fastapi, uvicorn) is required for `api.py`; `dev` depends on
  it (`sponsor-check[api]`) so `pip install -e ".[dev]"` still installs everything needed to
  run the test suite, including `test_api.py`.
- `api.py` holds the live register in `_default_register()`, not an `lru_cache`: a
  long-running server must pick up the daily register. It starts a background
  `ensure_database()` at most hourly and swaps in a new `Register` when the DB file's mtime
  changes. Requests never wait on GOV.UK, except the very first one when no DB exists.
- Production is one Docker container: `SPONSOR_CHECK_WEB_DIR` makes `api.py` mount the built
  frontend at `/` (mounted last, so `/api` routes win). `PORT` (set by Render) overrides
  `SPONSOR_CHECK_API_PORT`. The register is baked into the image at build time.
- The web app (`web/`) is a separate Vite/React/TypeScript project, not part of the Python
  package. Its dev server proxies `/api` to `sponsor-check-api` (see `web/vite.config.ts`).
  `web/src/types.ts` mirrors the API's JSON shapes by hand; keep them in sync when a Python
  result shape changes.

## How matching works (don't break these)

1. `canonical()` lowercases, strips accents, turns `&` into `and`, removes punctuation and legal
   suffixes (`ltd`, `limited`, `plc`, `llp`, ...). Noise words (`uk`, `the`, `trade`, `name`)
   are dropped only if something meaningful remains, so a name never canonicalises to an empty
   string. `canonical(name, strict=True)` keeps the brand noise words (`the`, `trade`, `name`)
   and still drops `uk`, which behaves like a legal suffix.
2. `aliases()` indexes each org under its full canonical name AND each legal/trading part split on
   `T/A`, `t/as`, `trading as`, standalone `TA`. The split regex needs whitespace around the
   marker so words like "Tata" are not split.
3. Search: exact lookup on the loose alias first. A hit scores 100 only if the strict forms are
   also equal (`Register._confirms`, recomputed from the org's name, so no schema change);
   otherwise 99. "Amazon" vs "Maxico Uk limited t/a The Amazon" is the case this exists for.
   Then RapidFuzz `WRatio` over all aliases, with a boost when an alias starts with the query.

### Invariants

- **Only an exact alias match, strict forms included, may score 100.** Fuzzy scores and loose-only
  hits are capped at 99. The `licensed` verdict depends on this; a guess must never be reported
  as a confirmed licence.
- Verdict bands: 100 = `licensed` (or `licensed_other_routes`), 90-99 = `possible_match`,
  below = `not_found` with the closest names shown.
- Every verdict includes the register date and the caveat that a licence does not mean the
  employer will sponsor a specific role.
- B-rated and provisional licences must stay flagged in the notes.
- MCP tools are read-only (`ToolAnnotations(read_only_hint=True, open_world_hint=False)`) and
  return plain dicts/lists (JSON-serialisable).

## MCP SDK gotchas (mcp >= 2.2, < 3)

- v2 renamed FastMCP: use `from mcp.server.mcpserver import MCPServer`. Do not use
  `mcp.server.fastmcp` (that's v1 and raises an error on v2).
- v2 Pydantic models use snake_case fields: `read_only_hint`, `structured_content`, not camelCase.
- Server runs over stdio: never `print()` to stdout inside server code, it corrupts the protocol.
  Log to stderr if needed.
- Tool docstrings and argument descriptions are what the model sees. Keep them precise.

## Testing rules

- Tests are offline. Never make network calls in tests; mock `httpx` if testing `fetch.py`.
- Every new normalisation rule gets a parametrised test using a **real** register row.
- Any invented status (B rating, provisional, etc.) must use clearly fictional names ending in
  `Test` (e.g. `Fictional Widgets Test Ltd`) so no real employer is ever mislabelled.
- Don't put private individuals' names (sole traders appear in the register) in tests; use
  placeholders like `Jane Example T/A`.
- If you change the fixture, update the row/organisation counts in
  `test_build_groups_routes_per_organisation`.

## Conventions

- Python 3.10+, type hints, `from __future__ import annotations`, line length 100.
- Keep `normalize.py` pure. Keep network code in `fetch.py` only.
- Writes to the cache are atomic (write to a temp file, then `replace`), so a failed download or
  build never destroys the last good copy. Keep it that way.
- Cache location: `SPONSOR_CHECK_HOME` or `~/.cache/sponsor-check`. Auto-refresh after 24h; if
  GOV.UK is unreachable, fall back to the existing database.
- The owner develops on Windows: avoid shell-specific scripts, use `pathlib`, and add
  `*.sh text eol=lf` to `.gitattributes` if a shell script is ever added.
- No em dashes in README or user-facing text.

## Roadmap (next work, in order)

1. **`check_job` tool**: take pasted job-ad text, let the calling model extract employer +
   salary + occupation code (the tool accepts structured args; don't call an LLM from inside
   the server), run `check_sponsor` and `check_salary` and combine the two verdicts.
2. Companies House lookup to resolve brand names to legal entities (optional API key via env var;
   the tool must still work without it).
3. Publish to PyPI and the MCP registry; add a demo GIF to the README.

Done: `check_salary` (see "Salary threshold facts").

## Out of scope

- Giving immigration advice or predicting visa outcomes.
- Scraping job boards.
- Storing any user data. The only thing cached locally is the public register.