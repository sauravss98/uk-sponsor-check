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
npx @modelcontextprotocol/inspector sponsor-check-mcp   # poke the MCP tools by hand
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
scripts/
  refresh_thresholds.py   scrapes GOV.UK to regenerate data/thresholds.json (dev only)
tests/
  fixtures/register_sample.csv   real register rows + fictional "... Test" rows
  test_normalize.py, test_register.py, test_salary.py, conftest.py (session-scoped test DB)
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
- The requirement is always `max(floor, rate)`: the floor comes from `general_thresholds`, the
  rate from the occupation entry. Discounted rates are published per occupation, not computed
  as a percentage here.
- Some codes have no standard going rate. Healthcare and education jobs take theirs from
  national pay scales and are absent from the table; a few rows say "Not eligible for standard
  rate applications". Both give `going_rate_unavailable` with the published wording or a link,
  never an invented number.
- Every salary result carries `thresholds.effective_date`, the rule that produced the figure,
  and the "confirm with the employer, this is not immigration advice" caveat.

## How matching works (don't break these)

1. `canonical()` lowercases, strips accents, turns `&` into `and`, removes punctuation and legal
   suffixes (`ltd`, `limited`, `plc`, `llp`, ...). Noise words (`uk`, `the`) are dropped only if
   something meaningful remains, so a name never canonicalises to an empty string.
2. `aliases()` indexes each org under its full canonical name AND each legal/trading part split on
   `T/A`, `t/as`, `trading as`, standalone `TA`. The split regex needs whitespace around the
   marker so words like "Tata" are not split.
3. Search: exact alias lookup first (score 100), then RapidFuzz `WRatio` over all aliases, with a
   boost when an alias starts with the query.

### Invariants

- **Only an exact alias match may score 100.** Fuzzy scores are capped at 99. The `licensed`
  verdict depends on this; a guess must never be reported as a confirmed licence.
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