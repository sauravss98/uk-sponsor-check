# sponsor-check web

React frontend for `sponsor-check`. A thin client over the FastAPI backend in
`src/sponsor_check/api.py`, which wraps the same `register.py`/`salary.py` logic used by the
CLI and the MCP server, so all three surfaces always agree.

## Development

You need the Python API running first (from the repo root, in the same or another terminal):

```bash
pip install -e ".[dev]"
sponsor-check-api            # http://127.0.0.1:8000
```

Then, from this directory:

```bash
npm install
npm run dev                  # http://localhost:5173
```

The Vite dev server proxies `/api/*` to `http://127.0.0.1:8000` (see `vite.config.ts`), so the
frontend never hardcodes the API's origin.

```bash
npm run build                # type-check + production build to dist/
npm run lint                 # oxlint
```

## Layout

```
src/
  api.ts        fetch wrapper for the four endpoints (check, search, salary, register-info)
  types.ts      TypeScript mirrors of the JSON the API returns
  components/   SponsorCheck, SalaryCheck, VerdictBadge, Footer
  App.tsx       tab layout
```

## Deploying

The root [`Dockerfile`](../Dockerfile) runs `npm run build` and copies `dist/` into the Python
image, where `sponsor-check-api` serves it at `/` (via `SPONSOR_CHECK_WEB_DIR`) next to `/api`.
One origin, so `api.ts` keeps using relative `/api` paths in production too. See "Deploying" in
the main README for Render.

## Next steps

- No shared schema between `types.ts` and the Python models yet; keep them in sync by hand
  until this needs more than a handful of endpoints.
- No tests on this side yet. If this grows, look at Vitest + Testing Library.
