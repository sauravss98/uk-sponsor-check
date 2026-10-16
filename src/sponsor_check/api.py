"""HTTP API for the React frontend (and anyone else who wants JSON over HTTP).

Run with:  sponsor-check-api   (binds 127.0.0.1:8000 by default)

In production (see the Dockerfile) it also serves the built React app from
``SPONSOR_CHECK_WEB_DIR``, so the frontend and ``/api`` share one origin and one process.

This is a thin wrapper: all the matching and salary logic lives in register.py and
salary.py, same as the MCP server in server.py. Nothing here duplicates that logic,
so the CLI, the MCP tools and this API can never disagree with each other.

CORS is restricted to an allowlist (``SPONSOR_CHECK_CORS_ORIGINS``, comma-separated)
because this serves a public frontend, unlike the MCP server which only ever talks to
a local client over stdio.

Two surfaces share one app:

- ``/api/*`` serves the web app in this repo and can change along with it.
- ``/v1/*`` is the stable contract for the Sponsor Badge browser extension, which lives in
  its own repo and is installed on machines we cannot update. It only ever gains fields.
  It is cached on the canonical name and rate limited per client IP.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import threading
import time
from functools import lru_cache
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from .fetch import PUBLICATION_PAGE
from .normalize import canonical
from .register import DEFAULT_ROUTE, Register, database_path, ensure_database
from .salary import check_floors as _check_floors
from .salary import check_salary as _check_salary
from .salary import thresholds as _thresholds

# The Vite dev server, plus the Sponsor Badge extension's development build, whose ID is pinned
# by the public "key" in its manifest.json. Production sets SPONSOR_CHECK_CORS_ORIGINS instead.
DEV_EXTENSION_ORIGIN = "chrome-extension://kiggiklmmmlkmjfaikamcihbinjhgcpo"
DEFAULT_ORIGINS = f"http://localhost:5173,http://127.0.0.1:5173,{DEV_EXTENSION_ORIGIN}"


def cors_origins() -> list[str]:
    """The allowlist, e.g. the web app's origin plus ``chrome-extension://<extension id>``."""
    raw = os.environ.get("SPONSOR_CHECK_CORS_ORIGINS", DEFAULT_ORIGINS)
    return [origin.strip() for origin in raw.split(",") if origin.strip()]


app = FastAPI(
    title="sponsor-check",
    description="Check UK employers against the Home Office register of licensed sponsors, "
                "and salaries against the Skilled Worker thresholds.",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins(),
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
    # Lets a cross-origin caller (the extension) see how long to back off after a 429.
    expose_headers=["Retry-After"],
)


# One JSON line per request: path, status and latency only. Never the query string (it holds the
# employer name) or the client IP. uvicorn's own access log is switched off in main().
access_log = logging.getLogger("sponsor_check.access")
_UNLOGGED_PATHS = {"/healthz", "/api/health"}  # the host's health checks would drown the counts


@app.middleware("http")
async def log_request(request: Request, call_next):
    start = time.perf_counter()
    status = 500
    try:
        response = await call_next(request)
        status = response.status_code
        return response
    finally:
        if request.url.path not in _UNLOGGED_PATHS:
            access_log.info(json.dumps({
                "method": request.method,
                "path": request.url.path,
                "status": status,
                "ms": round((time.perf_counter() - start) * 1000, 1),
            }))


REFRESH_INTERVAL = 3600  # seconds between checks for a newer register while the server runs

_lock = threading.Lock()
_live: dict = {"register": None, "mtime": 0.0, "checked": float("-inf")}  # never checked


def _default_register() -> Register:
    """The live register, reloaded when a newer database lands on disk.

    A long-running server would otherwise keep the register it started with forever. The
    download runs in a background thread so no request waits on GOV.UK; the only blocking
    download is the very first one, when there is no cached copy at all.
    """
    path = database_path()
    with _lock:
        if not path.exists():
            ensure_database()
        now = time.monotonic()
        if now - _live["checked"] > REFRESH_INTERVAL:
            _live["checked"] = now
            # Downloads only when the cached copy is over 24h old, and keeps the last good
            # copy if GOV.UK is unreachable.
            threading.Thread(target=ensure_database, daemon=True).start()
        mtime = path.stat().st_mtime
        if _live["register"] is None or mtime != _live["mtime"]:
            _live.update(register=Register(path), mtime=mtime)
            _lookup.cache_clear()  # drop answers (and the old Register) from the last register
        return _live["register"]


def get_register() -> Register:
    """FastAPI dependency, overridden in tests to point at the fixture database."""
    return _default_register()


class SalaryRequest(BaseModel):
    salary: float = Field(gt=0, description="Gross annual salary offered, in pounds.")
    soc_code: str = Field(description="4-digit SOC 2020 occupation code, e.g. '2136'.")
    new_entrant: bool = Field(default=False, description="Apply the new entrant rate.")


@app.get("/healthz")
@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/api/register-info")
def register_info(register: Register = Depends(get_register)) -> dict:
    """Dates and sources of the loaded data: the sponsor register and the salary thresholds."""
    data = _thresholds()
    return {**register.meta(), "thresholds_effective_date": data["effective_date"],
            "thresholds_source_url": data["source_url"]}


@app.get("/api/search")
def search(
    q: str = Query(..., min_length=1, description="Employer name to search for."),
    limit: int = Query(5, ge=1, le=25),
    register: Register = Depends(get_register),
) -> list[dict]:
    return [m.to_dict() for m in register.search(q, limit)]


@app.get("/api/check")
def check(
    company: str = Query(..., min_length=1, description="Employer name, legal or trading."),
    route: str = Query(DEFAULT_ROUTE, description="Visa route, e.g. 'Skilled Worker'."),
    register: Register = Depends(get_register),
) -> dict:
    return register.check(company, route)


@app.post("/api/salary")
def salary(req: SalaryRequest) -> dict:
    if not req.soc_code.strip():
        raise HTTPException(422, "soc_code is required")
    return _check_salary(req.salary, req.soc_code, req.new_entrant)


# --------------------------------------------------------------------------- /v1

RATE_LIMIT = os.environ.get("SPONSOR_CHECK_RATE_LIMIT", "60/minute")

# In memory, so per process: fine for a single container. Behind a proxy the client IP comes
# from X-Forwarded-For, which uvicorn only trusts from FORWARDED_ALLOW_IPS (see Dockerfile).
limiter = Limiter(key_func=get_remote_address, headers_enabled=True)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
# One budget shared by every /v1 endpoint, rather than 60/min for each of them.
v1_limit = limiter.shared_limit(RATE_LIMIT, scope="v1")

v1 = APIRouter(prefix="/v1", tags=["v1"])

STATUS = {
    "licensed": "licensed",
    "licensed_other_routes": "licensed_other_routes",
    "possible_match": "possible",
    "not_found": "not_found",
}


class Licence(BaseModel):
    route: str
    rating: str = Field(description="A, B or Provisional.")
    type: str = Field(description="The register's raw 'Type & Rating' value.")


class LookupResult(BaseModel):
    status: Literal["licensed", "licensed_other_routes", "possible", "not_found"]
    legal_name: str | None = Field(description="Name on the register; null when not found.")
    town: str | None
    rating: str | None = Field(description="Rating on the requested route, if licensed for it.")
    routes: list[Licence]
    register_date: str
    source_url: str = Field(description="The register CSV this answer came from.")
    register_url: str = Field(description="The GOV.UK publication page, for people to read.")
    confidence: float = Field(ge=0, le=100,
                              description="Match score. Only an exact name match scores 100.")
    notes: list[str] = Field(description="Caveats, including B-rated and provisional warnings.")


class SalaryFloors(BaseModel):
    salary: float
    route: str
    general_threshold: int
    meets_general: bool
    new_entrant_threshold: int
    meets_new_entrant: bool
    hours_per_week_basis: float = Field(description="Working week the going rates assume.")
    weeks_per_year_basis: int = Field(description="Weeks a year the rules annualise pay over.")
    thresholds: dict[str, str] = Field(description="effective_date and source_url.")
    notes: list[str]


@lru_cache(maxsize=4096)
def _lookup(register: Register, name: str, route: str) -> LookupResult:
    """``register.check`` reshaped for the extension, cached per register.

    Callers pass the strict canonical name, so "Starling Bank" and "STARLING BANK LTD" share
    one entry but "Amazon" and "The Amazon" (which only the strict key tells apart) do not.
    The live register clears the cache when it swaps in a newer one.
    """
    result = register.check(name, route)
    top = result["matches"][0] if result["matches"] and result["verdict"] != "not_found" else None
    rating = None
    if top:
        rating = next((r["rating"] for r in top["routes"]
                       if r["route"].lower() == route.lower()), None)
    return LookupResult(
        status=STATUS[result["verdict"]],
        legal_name=top["name"] if top else None,
        town=top["town"] if top else None,
        rating=rating,
        routes=top["routes"] if top else [],
        register_date=result["register_date"],
        source_url=register.meta().get("source_url", ""),
        register_url=PUBLICATION_PAGE,
        confidence=top["score"] if top else 0,
        # register.py writes notes for the CLI and MCP, which render Markdown ("*can*"); the
        # /v1 contract promises plain text.
        notes=[note.replace("*", "") for note in result["notes"]],
    )


@v1.get("/lookup", response_model=LookupResult)
@v1_limit
def lookup(
    request: Request,
    response: Response,
    name: str = Query(..., min_length=1, max_length=200, description="Employer name on the ad."),
    route: str = Query(DEFAULT_ROUTE, description="Visa route, e.g. 'Skilled Worker'."),
    register: Register = Depends(get_register),
) -> LookupResult:
    return _lookup(register, canonical(name, strict=True), route)


@v1.get("/salary-check", response_model=SalaryFloors)
@v1_limit
def salary_check(
    request: Request,
    response: Response,
    amount: float = Query(..., gt=0, description="Advertised gross annual salary, in pounds."),
) -> dict:
    return _check_floors(amount)


app.include_router(v1)


def mount_web(target: FastAPI, directory: Path) -> None:
    """Serve the built frontend at ``/``. Mounted last, so every ``/api`` route wins."""
    target.mount("/", StaticFiles(directory=directory, html=True), name="web")


_web_dir = os.environ.get("SPONSOR_CHECK_WEB_DIR")
if _web_dir and Path(_web_dir).is_dir():
    mount_web(app, Path(_web_dir))


def main() -> None:
    import uvicorn

    # PORT is what hosts such as Render assign; SPONSOR_CHECK_API_PORT is the local override.
    port = os.environ.get("PORT") or os.environ.get("SPONSOR_CHECK_API_PORT", "8000")
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(message)s"))
    access_log.addHandler(handler)
    access_log.setLevel(logging.INFO)
    access_log.propagate = False
    uvicorn.run("sponsor_check.api:app",
                host=os.environ.get("SPONSOR_CHECK_API_HOST", "127.0.0.1"),
                port=int(port),
                access_log=False)  # it logs full URLs, names included


if __name__ == "__main__":
    main()
