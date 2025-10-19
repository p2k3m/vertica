import asyncio
import json

import pytest

pytest.importorskip("starlette")

from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.testclient import TestClient

from mcp_vertica.health import healthz, reset_health_state, set_component_status
from mcp_vertica.mcp import AuthMiddleware


@pytest.fixture(autouse=True)
def _reset_health_state():
    reset_health_state()
    yield
    reset_health_state()


class DummyRequest:
    pass


def _build_app() -> Starlette:
    app = Starlette()
    app.add_middleware(AuthMiddleware)

    @app.route("/protected")
    async def _protected(_request):
        return JSONResponse({"ok": True})

    @app.route("/healthz")
    async def _health(request) -> JSONResponse:
        return await healthz(request)

    return app


def test_healthz_returns_ok():
    response = asyncio.run(healthz(DummyRequest()))
    assert response.status_code == 200
    assert json.loads(response.body.decode("utf-8")) == {"ok": True, "components": {}}


def test_healthz_bypasses_auth(monkeypatch):
    monkeypatch.setenv("MCP_HTTP_TOKEN", "secret")
    app = _build_app()
    with TestClient(app) as client:
        response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"ok": True, "components": {}}


def test_healthz_reports_component_failure():
    set_component_status(
        "vertica",
        ready=False,
        attempts=3,
        last_error="RuntimeError: boom",
        last_attempt_utc="2024-01-01T00:00:00Z",
        ready_since_utc=None,
    )
    response = asyncio.run(healthz(DummyRequest()))
    assert response.status_code == 503
    payload = json.loads(response.body.decode("utf-8"))
    assert payload["ok"] is False
    assert payload["components"] == {
        "vertica": {
            "ready": False,
            "attempts": 3,
            "last_error": "RuntimeError: boom",
            "last_attempt_utc": "2024-01-01T00:00:00Z",
            "ready_since_utc": None,
        }
    }


def test_protected_endpoint_requires_auth(monkeypatch):
    monkeypatch.setenv("MCP_HTTP_TOKEN", "secret")
    app = _build_app()
    with TestClient(app) as client:
        response = client.get("/protected")
        assert response.status_code == 401
        authed = client.get("/protected", headers={"X-API-Key": "secret"})
    assert authed.status_code == 200
    assert authed.json() == {"ok": True}
