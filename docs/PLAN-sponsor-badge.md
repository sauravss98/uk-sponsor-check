# Project 1: Sponsor Badge — browser extension for UK visa job seekers

## How to use this file with Claude Code
Put this file in the repo root as `PLAN.md`. Start each session with:
> Read PLAN.md. We are on Milestone N. Explain your approach before writing code, keep changes small, and stop after each milestone so I can review and commit.

## Working rules for Claude Code
- Explain every design decision in one or two sentences before implementing it. I want to be able to defend each choice in an interview.
- Small commits, conventional commit messages (`feat:`, `fix:`, `test:`, `docs:`).
- Tests come with the code, not after.
- Never invent usage numbers, benchmarks or metrics in the README. Only report what we measure.
- Prefer boring, well-known libraries over clever ones.

---

## 1. Problem
International students and graduates in the UK waste hours applying to jobs at employers who cannot sponsor a Skilled Worker visa. The Home Office publishes the register of licensed sponsors, but nobody checks it while scrolling LinkedIn or Indeed. Company names on job ads (trading names) rarely match the legal names on the register.

## 2. Users
- International students and graduates on Student or Graduate visas looking for UK jobs.
- Anyone needing Skilled Worker sponsorship.

## 3. What it does (MVP)
On a job listing page (LinkedIn, Indeed UK, and one more board), the extension:
1. Reads the employer name from the page.
2. Calls the Sponsor Badge API.
3. Shows a small badge next to the employer name:
   - Green: "Licensed sponsor (A-rated) — Skilled Worker"
   - Amber: "Possible match — check" (fuzzy match, shows the matched legal name)
   - Grey: "Not found on register"
4. Clicking the badge opens a small panel with: matched legal name, town, rating, routes, register date, and a link to the official register.
5. If the page shows a salary, the panel says whether it clears the general Skilled Worker threshold and the new-entrant threshold, with the source and date of those thresholds.

Out of scope for MVP: accounts, saving jobs, any personal data collection.

## 4. Architecture
```
Chrome extension (Manifest V3, TypeScript)
  ├─ content scripts per job board (extract employer + salary, inject badge)
  ├─ background service worker (calls API, caches results in chrome.storage.session)
  └─ popup (manual search box + settings)
          │ HTTPS
          ▼
Sponsor Badge API (FastAPI, Python)  ← reuses the sponsor-check matching + register code
  ├─ GET /v1/lookup?name=...          → match result
  ├─ GET /v1/salary-check?amount=...  → threshold result
  ├─ GET /healthz
  ├─ in-memory LRU cache + SQLite register (daily refresh, atomic swap — already built)
  └─ rate limiting per IP
          │
Deployed on a small host (Fly.io, Render or AWS Lambda + API Gateway)
```

## 5. Tech stack
- Extension: TypeScript, Manifest V3, Vite (or esbuild) for bundling, Vitest for unit tests, Playwright for one end-to-end test against saved HTML fixtures.
- API: Python 3.12, FastAPI, Pydantic, existing sponsor-check package as a dependency, pytest, `slowapi` (or similar) for rate limiting.
- CI: GitHub Actions (lint, type-check, tests for both packages).
- Hosting: pick one cheap option; document the choice.

## 6. Privacy rules (put these in the README)
- The extension sends only the employer name and, if present, the advertised salary. No URLs, no user identifiers, no browsing history.
- No analytics in the extension at all. Usage is measured only from anonymous API request counts.
- Minimum Chrome permissions: `storage` plus host permissions for the supported job boards only.

## 7. Milestones
### M1 — API wrapper (2–3 evenings)
- FastAPI app exposing `/v1/lookup`, `/v1/salary-check`, `/healthz`, importing sponsor-check.
- Response model: `{status: "licensed"|"possible"|"not_found", legal_name, town, rating, routes, register_date, source_url, confidence}`.
- LRU cache on normalised name. Rate limit 60 requests/min/IP.
- Tests: exact match, trading-name match, fuzzy "possible", not found, salary above/below thresholds.
- **Done when:** `pytest` passes and `curl` works locally.

### M2 — Deploy the API (1 evening)
- Dockerfile, deploy, HTTPS URL, `/healthz` monitored.
- Structured JSON logging of request count and latency only (no names logged in production).
- **Done when:** public URL responds in under 300 ms for cached lookups.

### M3 — Extension skeleton + popup search (2 evenings)
- MV3 manifest, background worker, popup with a search box calling the API.
- **Done when:** loading the unpacked extension and searching "Starling Bank" shows the correct badge.

### M4 — LinkedIn and Indeed content scripts (3–4 evenings)
- One extractor module per site with saved HTML fixtures in `fixtures/`.
- Badge injection that survives page navigation (LinkedIn is a single-page app: use a MutationObserver).
- Unit tests for each extractor against fixtures.
- **Done when:** badges appear correctly on 10 real listings per site.

### M5 — Salary check panel (1–2 evenings)
- Parse salary text ("£45,000 - £55,000 a year", "£40k", per-hour), use the lower bound, compare to thresholds from the API.
- Tests for at least 15 salary string formats.

### M6 — Publish (1–2 evenings)
- README with screenshots/GIF, privacy section, how matching works, known limitations.
- Chrome Web Store listing (developer fee applies) or GitHub release with install instructions.
- Post on LinkedIn using the "fuzzy match should never look like a confirmed answer" angle.

## 8. Measuring real use (honestly)
- Count unique daily API callers by hashed IP with a daily salt (not stored long-term).
- Chrome Web Store install count.
- Only quote these numbers on the CV once they exist.

## 9. Interview talking points this project gives you
- Why fuzzy matches are capped below exact matches.
- Handling a single-page app DOM that keeps changing.
- Privacy-by-design choices and minimum permissions.
- Caching and rate limiting a public API on a tiny budget.

## 10. CV bullet templates (fill in real numbers only)
- Built and published a Chrome extension (TypeScript, Manifest V3) that flags whether employers on LinkedIn and Indeed hold a UK Skilled Worker sponsor licence, backed by a FastAPI service over the Home Office register; [N] installs.
- Designed privacy-first data flow sending only employer name and salary, with caching and rate limiting keeping cached lookups under [X] ms.
