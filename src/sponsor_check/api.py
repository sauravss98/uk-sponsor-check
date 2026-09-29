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
"""

from __future__ import annotations

import os
import threading
import time
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .register import DEFAULT_ROUTE, Register, database_path, ensure_database
from .salary import check_salary as _check_salary
from .salary import thresholds as _thresholds

DEFAULT_ORIGINS = "http://localhost:5173,http://127.0.0.1:5173"

app = FastAPI(
    title="sponsor-check",
    description="Check UK employers against the Home Office register of licensed sponsors, "
                "and salaries against the Skilled Worker thresholds.",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.environ.get("SPONSOR_CHECK_CORS_ORIGINS", DEFAULT_ORIGINS).split(","),
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


REFRESH_INTERVAL = 3600  # seconds between checks for a newer register while the server runs

_lock = threading.Lock()
_live: dict = {"register": None, "mtime": 0.0, "checked": 0.0}


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
        return _live["register"]


def get_register() -> Register:
    """FastAPI dependency, overridden in tests to point at the fixture database."""
    return _default_register()


class SalaryRequest(BaseModel):
    salary: float = Field(gt=0, description="Gross annual salary offered, in pounds.")
    soc_code: str = Field(description="4-digit SOC 2020 occupation code, e.g. '2136'.")
    new_entrant: bool = Field(default=False, description="Apply the new entrant rate.")


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
    uvicorn.run("sponsor_check.api:app",
                host=os.environ.get("SPONSOR_CHECK_API_HOST", "127.0.0.1"),
                port=int(port))


if __name__ == "__main__":
    main()
