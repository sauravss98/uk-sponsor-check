"""API tests.

Offline, like the rest of the suite: the ``register`` fixture's dependency override
replaces ``get_register`` so these never call ``ensure_database`` or hit the network.
"""

from __future__ import annotations

import os
import shutil

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from sponsor_check import api
from sponsor_check.api import app, get_register, mount_web


@pytest.fixture
def client(register):
    app.dependency_overrides[get_register] = lambda: register
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def test_health(client):
    assert client.get("/api/health").json() == {"status": "ok"}


def test_register_info(client):
    body = client.get("/api/register-info").json()
    assert body["register_date"] == "2026-09-28"
    assert "thresholds_effective_date" in body


def test_check_licensed(client):
    body = client.get("/api/check", params={"company": "Gurkha Swindon"}).json()
    assert body["verdict"] == "licensed"
    assert body["matches"][0]["name"] == "Everest Kitchen Ltd T/A Gurkha Swindon"


def test_check_uses_requested_route(client):
    body = client.get("/api/check", params={"company": "Mode Agence", "route": "Creative Worker"})
    assert body.json()["verdict"] == "licensed"


def test_check_requires_company(client):
    assert client.get("/api/check").status_code == 422


def test_search(client):
    body = client.get("/api/search", params={"q": "cake glory", "limit": 3}).json()
    assert body and body[0]["name"] == "CAKE GLORY LTD LTD"
    assert len(body) <= 3


def test_salary_meets(client):
    body = client.post("/api/salary", json={"salary": 45000, "soc_code": "2136"}).json()
    assert body["verdict"] == "meets"


def test_salary_new_entrant(client):
    body = client.post(
        "/api/salary", json={"salary": 35000, "soc_code": "1111", "new_entrant": True},
    ).json()
    assert body["basis"] == "new_entrant"


def test_salary_validates_positive_amount(client):
    assert client.post("/api/salary", json={"salary": 0, "soc_code": "2136"}).status_code == 422


def test_salary_requires_non_empty_code(client):
    assert client.post("/api/salary", json={"salary": 45000, "soc_code": "  "}).status_code == 422


def test_cors_headers_present(client):
    resp = client.get("/api/health", headers={"Origin": "http://localhost:5173"})
    assert resp.headers.get("access-control-allow-origin") == "http://localhost:5173"


def test_mount_web_serves_frontend_without_shadowing_api(tmp_path):
    (tmp_path / "index.html").write_text("<div id=root></div>", encoding="utf-8")
    web_app = FastAPI()

    @web_app.get("/api/health")
    def health() -> dict:
        return {"status": "ok"}

    mount_web(web_app, tmp_path)
    web_client = TestClient(web_app)
    assert "id=root" in web_client.get("/").text
    assert web_client.get("/api/health").json() == {"status": "ok"}


@pytest.fixture
def live_home(tmp_path, monkeypatch, register):
    """A cache dir holding the fixture DB, with downloads stubbed out and fresh live state."""
    shutil.copy(register.conn.execute("PRAGMA database_list").fetchone()["file"],
                tmp_path / "register.sqlite3")
    monkeypatch.setenv("SPONSOR_CHECK_HOME", str(tmp_path))
    downloads: list[int] = []
    monkeypatch.setattr(api, "ensure_database", lambda: downloads.append(1))
    monkeypatch.setattr(api, "_live", {"register": None, "mtime": 0.0, "checked": 0.0})
    return tmp_path, downloads


def test_live_register_is_reused_until_the_file_changes(live_home):
    home, _ = live_home
    first = api._default_register()
    assert api._default_register() is first

    db = home / "register.sqlite3"
    stat = db.stat()
    os.utime(db, (stat.st_atime, stat.st_mtime + 60))  # a refresh replaced the file
    assert api._default_register() is not first


def test_live_register_refreshes_in_background_at_most_hourly(live_home):
    _, downloads = live_home
    api._default_register()
    api._default_register()
    for thread in api.threading.enumerate():
        if thread is not api.threading.current_thread() and thread.daemon:
            thread.join(timeout=5)
    assert downloads == [1]
