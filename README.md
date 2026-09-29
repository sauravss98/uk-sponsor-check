# sponsor-check

**Can this UK employer sponsor my visa?** Ask Claude, get an answer from the official Home Office register in seconds.

`sponsor-check` is an MCP server, command-line tool and (in progress) web app that checks
employers against the
[Register of licensed sponsors: workers](https://www.gov.uk/government/publications/register-of-licensed-sponsors-workers),
which UK Visas and Immigration republishes almost every working day. It also checks a salary
against the published Skilled Worker thresholds and going rates.

```
$ sponsor-check check "Synthesia"
YES: Synthesia / Skilled Worker (register 2026-09-28)
  Synthesia Limited  (London)  score 100
      - Skilled Worker  [A]

$ sponsor-check salary 45000 2136
YES: £45,000 for occupation code 2136 (IT quality and testing professionals)
  required: £41,700
  rule: Standard rate: the higher of the £41,700 general salary threshold and the £41,200
        going rate for occupation code 2136 (IT quality and testing professionals).
```

## Why

Checking the register by hand means downloading a ~10 MB CSV and Ctrl+F-ing it for every
application. That breaks in predictable ways:

- **Trading names vs legal names.** Job ads use the brand; the register uses the legal entity,
  often as `LEGAL NAME LTD T/A Brand`. sponsor-check indexes both halves.
- **Inconsistent data entry.** `CAKE GLORY LTD LTD`, `F-Secure (UK) Limited`, `2i Limited` vs
  `2I LIMITED`. Names are normalised (case, punctuation, legal suffixes, accents, `&`) before matching.
- **One row per route.** The same employer appears once per visa route. Results are grouped per
  organisation, with each route and its A/B rating.
- **Downgraded licences.** B-rated and provisional licences are flagged, because they change
  what you should ask the employer.

## Use it from Claude

**Claude Code**

```bash
claude mcp add sponsor-check -- sponsor-check-mcp
```

**Claude Desktop** (`claude_desktop_config.json`)

```json
{
  "mcpServers": {
    "sponsor-check": { "command": "sponsor-check-mcp" }
  }
}
```

Then ask things like *"Can Octopus Energy sponsor a Skilled Worker visa?"* or paste a job ad and
ask whether the employer is on the register.

| Tool | What it does |
|---|---|
| `check_sponsor(company, route="Skilled Worker")` | Verdict: `licensed`, `licensed_other_routes`, `possible_match` or `not_found`, with evidence and caveats |
| `search_sponsors(query, limit=5)` | Ranked fuzzy matches with routes and ratings |
| `check_salary(salary, soc_code, new_entrant=False)` | Verdict: `meets`, `below`, `occupation_ineligible`, `going_rate_unavailable` or `unknown_occupation`, with the rule that applied and the lower rates the job could qualify for |
| `register_info()` | Register and thresholds dates, sizes and GOV.UK source URLs |

All tools are read-only.

## Command line

```bash
pip install git+https://github.com/sauravss98/sponsor-check
sponsor-check update                                   # download today's register
sponsor-check check "Octopus Energy"                   # exit code 0 only if licensed
sponsor-check check "Mode Agence" --route "Creative Worker"
sponsor-check search "octopus" -n 10 --json
sponsor-check salary 45000 2136                        # exit code 0 only if the salary meets it
sponsor-check salary 62000 1111 --new-entrant --json
```

The register is cached in `~/.cache/sponsor-check` (override with `SPONSOR_CHECK_HOME`) and
refreshed automatically when it is more than 24 hours old. If GOV.UK is unreachable, the last
good copy is used.

## How it works

```
GOV.UK Content API ──► find today's CSV URL ──► download (atomic swap)
                                                     │
                                                     ▼
                         parse ► group rows by organisation ► SQLite
                                        │
                           aliases: full name, legal part, trading part(s)
                                        │
query ► normalise ► exact alias lookup ─┴─► RapidFuzz WRatio over aliases ► verdict
```

- The CSV link changes with every publication, so it is discovered through the GOV.UK Content
  API, with an HTML fallback.
- Exact alias hits score 100. Fuzzy hits are capped at 99 so a guess is never reported as a
  confirmed licence; names that start with the query get a boost.
- Verdict bands: 100 = `licensed`, 90 to 99 = `possible_match`, below that = `not_found`
  (closest names still shown).

### Salary thresholds

The salary requirement is the higher of a flat general threshold and the occupation's going
rate, and both move with the Immigration Rules. No figure is hardcoded: they are scraped from
the published GOV.UK guidance into `src/sponsor_check/data/thresholds.json`, which records the
source URL and publication date of every table it used. Every answer repeats that date, names
the rule that produced it, and lists the lower rates the job could qualify for, such as the new
entrant, PhD, immigration salary list and temporary shortage list rates.

Refresh the data after a rules change with `python scripts/refresh_thresholds.py`, then commit
the diff. The script fails loudly rather than writing a half-empty file if a page changes shape.

## Web app

A React frontend is taking shape in [`web/`](web/), talking to a small FastAPI wrapper
(`src/sponsor_check/api.py`) over the same `register.py`/`salary.py` logic the CLI and MCP
server use, so all three surfaces always agree.

```bash
pip install -e ".[dev]"
sponsor-check-api          # http://127.0.0.1:8000

cd web
npm install
npm run dev                # http://localhost:5173, proxies /api to the server above
```

See [`web/README.md`](web/README.md) for more.

### Deploying

The [`Dockerfile`](Dockerfile) builds everything into one container: FastAPI serves `/api` and
the built frontend from the same origin, so no CORS setup is needed. The register is downloaded
at build time, so a cold start serves straight away, and the running server refreshes it in the
background once it is more than 24 hours old.

```bash
docker build -t sponsor-check .
docker run -p 8000:8000 sponsor-check     # http://localhost:8000
```

[`render.yaml`](render.yaml) deploys it to Render's free tier: in the Render dashboard choose
**New > Blueprint** and pick this repository. Free services sleep when idle, so the first visit
after a quiet spell takes a little while to wake up.

## Development

```bash
pip install -e ".[dev]"
pytest
```

Tests run against a fixture of real rows taken from the published register, plus clearly
fictional `Example ...` rows for the B-rated case. They are offline: the salary tests read the
committed thresholds file, and `scripts/refresh_thresholds.py` is the only thing that talks to
GOV.UK at build time.

## Roadmap

- [x] Salary check against Skilled Worker thresholds by occupation code
- [ ] Web app: FastAPI + React frontend in `web/`, deployable to Render (see Deploying)
- [ ] `check_job` tool: extract employer and salary from a pasted job ad, run both checks
- [ ] Companies House lookup to resolve brand names to legal entities
- [ ] Publish to PyPI and the MCP registry

## Disclaimer

Not legal or immigration advice. A licence means an employer *can* sponsor, not that it will
sponsor a particular role. Always confirm with the employer.

Register data and salary thresholds: UK Visas and Immigration, published on GOV.UK under the
[Open Government Licence v3.0](https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/).
Code: MIT.
