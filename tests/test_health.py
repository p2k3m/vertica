from fastapi.testclient import TestClient

from mcp_vertica.server import app


def test_health():
    client = TestClient(app)
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json()["ok"] is True
