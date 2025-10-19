import asyncio
import json

from mcp_vertica.health import healthz


class DummyRequest:
    pass


def test_healthz_returns_ok():
    response = asyncio.run(healthz(DummyRequest()))
    assert response.status_code == 200
    assert json.loads(response.body.decode("utf-8")) == {"ok": True}
