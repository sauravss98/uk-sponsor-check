"""API tests.

Offline, like the rest of the suite: the ``register`` fixture's dependency override
replaces ``get_register`` so these never call ``ensure_database`` or hit the network.
"""

from __future__ import annotations

import json
import logging
import os
import shutil

import pytest
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.testclient import TestClient

from sponsor_check import api
from sponsor_check.api import app, get_register, limiter, mount_web
from sponsor_check.salary import thresholds

FLOORS = thresholds()["general_thresholds"]


@pytest.fixture
def client(register):
    app.dependency_overrides[get_register] = lambda: register
    limiter.reset()
    api._lookup.cache_clear()
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


def test_cors_allows_dev_extension_by_default(client):
    origin = api.DEV_EXTENSION_ORIGIN
    resp = client.get("/v1/lookup", params={"name": "Gurkha Swindon"}, headers={"Origin": origin})
    assert resp.headers.get("access-control-allow-origin") == origin


def test_cors_headers_present(client):
    resp = client.get("/api/health", headers={"Origin": "http://localhost:5173"})
    assert resp.headers.get("access-control-allow-origin") == "http://localhost:5173"


def test_cors_allowlist_accepts_extension_origin(monkeypatch):
    monkeypatch.setenv("SPONSOR_CHECK_CORS_ORIGINS",
                       "https://example.test, chrome-extension://abcdefghijklmnop")
    assert api.cors_origins() == ["https://example.test", "chrome-extension://abcdefghijklmnop"]

    ext_app = FastAPI()
    ext_app.add_middleware(CORSMiddleware, allow_origins=api.cors_origins())

    @ext_app.get("/healthz")
    def healthz() -> dict:
        return {"status": "ok"}

    resp = TestClient(ext_app).get("/healthz",
                                   headers={"Origin": "chrome-extension://abcdefghijklmnop"})
    assert resp.headers["access-control-allow-origin"] == "chrome-extension://abcdefghijklmnop"


def test_cors_rejects_unlisted_extension_and_exposes_retry_after(client):
    cors = next(m for m in app.user_middleware if m.cls is CORSMiddleware)
    assert "Retry-After" in cors.kwargs["expose_headers"]
    resp = client.get("/v1/lookup", params={"name": "Gurkha Swindon"},
                      headers={"Origin": "chrome-extension://not-allowlisted"})
    assert "access-control-allow-origin" not in resp.headers


# --------------------------------------------------------------------------- /v1


def lookup(client, name, **params):
    resp = client.get("/v1/lookup", params={"name": name, **params})
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_request_log_has_no_names_or_ips(client, caplog):
    caplog.set_level(logging.INFO, logger="sponsor_check.access")
    client.get("/v1/lookup", params={"name": "Gurkha Swindon"},
               headers={"X-Forwarded-For": "203.0.113.7"})
    [record] = [r for r in caplog.records if r.name == "sponsor_check.access"]
    line = record.getMessage()
    assert json.loads(line) == {"method": "GET", "path": "/v1/lookup", "status": 200,
                                "ms": json.loads(line)["ms"]}
    assert "Gurkha" not in line and "203.0.113.7" not in line and "testclient" not in line


def test_health_checks_are_not_logged(client, caplog):
    caplog.set_level(logging.INFO, logger="sponsor_check.access")
    client.get("/healthz")
    assert not [r for r in caplog.records if r.name == "sponsor_check.access"]


def test_healthz(client):
    assert client.get("/healthz").json() == {"status": "ok"}


def test_v1_exact_match(client):
    body = lookup(client, "cake glory limited")
    assert body["status"] == "licensed"
    assert body["legal_name"] == "CAKE GLORY LTD LTD"
    assert body["confidence"] == 100
    assert body["rating"] == "A"
    assert body["register_date"] == "2026-09-28"
    assert body["source_url"].endswith("2026-09-28.csv")
    assert body["register_url"] == (
        "https://www.gov.uk/government/publications/register-of-licensed-sponsors-workers")


def test_v1_trading_name_resolves_to_legal_name(client):
    body = lookup(client, "Gurkha Swindon")
    assert body["status"] == "licensed"
    assert body["legal_name"] == "Everest Kitchen Ltd T/A Gurkha Swindon"


def test_v1_fuzzy_match_is_possible_never_licensed(client):
    body = lookup(client, "Example Analytics Group")
    assert body["status"] == "possible"
    assert body["legal_name"] == "Example Analytics Limited"
    assert 90 <= body["confidence"] < 100


def test_v1_not_found(client):
    body = lookup(client, "Totally Unrelated Quantum Bakery")
    assert body["status"] == "not_found"
    assert body["legal_name"] is None and body["routes"] == [] and body["confidence"] == 0
    assert any("different legal name" in n for n in body["notes"])


def test_v1_licensed_on_other_routes_only(client):
    body = lookup(client, "Mode Agence")
    assert body["status"] == "licensed_other_routes"
    assert body["rating"] is None
    assert body["routes"]


def test_v1_b_rating_is_flagged(client):
    body = lookup(client, "Example Widgets")
    assert body["status"] == "licensed" and body["rating"] == "B"
    assert any("B-rated" in n for n in body["notes"])


def test_v1_every_lookup_carries_the_caveat(client):
    body = lookup(client, "Gurkha Swindon")
    assert any("not that it will" in n for n in body["notes"])
    assert not any("*" in n for n in body["notes"])  # plain text, no Markdown emphasis


def test_v1_lookup_validates_name(client):
    assert client.get("/v1/lookup").status_code == 422
    assert client.get("/v1/lookup", params={"name": "x" * 201}).status_code == 422


def test_v1_cache_keeps_brand_words_apart(client):
    assert lookup(client, "Amazon")["status"] == "possible"
    assert lookup(client, "The Amazon")["status"] == "licensed"


def test_v1_premium_sponsor_is_a_rated(client):
    assert lookup(client, "Google")["rating"] == "A"


def test_v1_lookup_is_cached_on_canonical_name(client):
    lookup(client, "Gurkha Swindon")
    lookup(client, "GURKHA SWINDON LTD")
    info = api._lookup.cache_info()
    assert (info.hits, info.misses) == (1, 1)


@pytest.mark.parametrize(("offset", "general", "new_entrant"), [
    (1, True, True),       # above both
    (0, True, True),       # exactly on the general threshold counts as meeting it
    (-1, False, True),     # just under the general threshold, still above the new entrant floor
])
def test_v1_salary_check_general_threshold(client, offset, general, new_entrant):
    body = client.get("/v1/salary-check",
                      params={"amount": FLOORS["standard"] + offset}).json()
    assert (body["meets_general"], body["meets_new_entrant"]) == (general, new_entrant)
    assert body["general_threshold"] == FLOORS["standard"]


def test_v1_salary_check_below_both_floors(client):
    body = client.get("/v1/salary-check",
                      params={"amount": FLOORS["discounted_floor"] - 1}).json()
    assert body["meets_general"] is False and body["meets_new_entrant"] is False
    assert body["new_entrant_threshold"] == FLOORS["discounted_floor"]


def test_v1_salary_check_carries_source_and_caveat(client):
    body = client.get("/v1/salary-check", params={"amount": 50000}).json()
    assert body["hours_per_week_basis"] == thresholds()["hours_per_week_basis"]
    assert body["weeks_per_year_basis"] == thresholds()["weeks_per_year_basis"]
    assert body["thresholds"]["effective_date"] and body["thresholds"]["source_url"]
    assert any("going rate" in n for n in body["notes"])


def test_v1_salary_check_validates_amount(client):
    assert client.get("/v1/salary-check", params={"amount": 0}).status_code == 422
    assert client.get("/v1/salary-check").status_code == 422


def test_v1_rate_limit_is_shared_across_endpoints(client):
    for i in range(60):
        path = "/v1/lookup" if i % 2 else "/v1/salary-check"
        params = {"name": "Gurkha Swindon"} if i % 2 else {"amount": 50000}
        assert client.get(path, params=params).status_code == 200
    resp = client.get("/v1/lookup", params={"name": "Gurkha Swindon"},
                      headers={"Origin": "http://localhost:5173"})
    assert resp.status_code == 429
    assert "retry-after" in resp.headers
    assert resp.headers.get("access-control-allow-origin") == "http://localhost:5173"


def test_client_ip_uses_configured_header(monkeypatch):
    from starlette.requests import Request

    def request(headers: dict[str, str]) -> Request:
        raw = [(k.lower().encode(), v.encode()) for k, v in headers.items()]
        return Request({"type": "http", "headers": raw, "client": ("10.0.0.1", 1234)})

    monkeypatch.setattr(api, "CLIENT_IP_HEADER", "cf-connecting-ip")
    assert api.client_ip(request({"CF-Connecting-IP": "203.0.113.9"})) == "203.0.113.9"
    assert api.client_ip(request({})) == "10.0.0.1"  # header missing: fall back
    monkeypatch.setattr(api, "CLIENT_IP_HEADER", "")
    assert api.client_ip(request({"CF-Connecting-IP": "203.0.113.9"})) == "10.0.0.1"


def test_health_endpoints_are_not_rate_limited(client):
    for _ in range(70):
        assert client.get("/healthz").status_code == 200


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
    monkeypatch.setattr(api, "_live", {"register": None, "mtime": 0.0, "checked": float("-inf")})
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
