import types

import pytest

from mcp_vertica.connection import VerticaConfig, VerticaConnectionPool


class FakeConnection:
    def __init__(self):
        self._closed = False

    def closed(self) -> bool:  # pragma: no cover - compatibility with vertica_python
        return self._closed

    def close(self) -> None:
        self._closed = True

    def cursor(self) -> types.SimpleNamespace:  # pragma: no cover - safety for manager tests
        return types.SimpleNamespace(closed=lambda: False, close=lambda: None)


def _config(limit: int = 2) -> VerticaConfig:
    return VerticaConfig(
        host="localhost",
        port=5433,
        database="VMart",
        user="dbadmin",
        password="",
        connection_limit=limit,
    )


def test_pool_initialization_is_lazy(monkeypatch):
    calls: list[dict] = []

    def _fake_connect(**kwargs):
        calls.append(kwargs)
        return FakeConnection()

    monkeypatch.setattr("vertica_python.connect", _fake_connect)

    pool = VerticaConnectionPool(_config())
    assert calls == []
    pool.close_all()


def test_pool_creates_connections_on_demand(monkeypatch):
    created: list[FakeConnection] = []

    def _fake_connect(**kwargs):
        conn = FakeConnection()
        created.append(conn)
        return conn

    monkeypatch.setattr("vertica_python.connect", _fake_connect)

    pool = VerticaConnectionPool(_config(limit=1))
    conn = pool.acquire()
    assert conn is created[0]
    pool.release(conn)
    assert pool.acquire() is conn
    pool.release(conn)
    pool.close_all()


def test_pool_recovers_after_connection_failure(monkeypatch):
    attempts = {"count": 0}

    def _flaky_connect(**kwargs):
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise RuntimeError("boom")
        return FakeConnection()

    monkeypatch.setattr("vertica_python.connect", _flaky_connect)

    pool = VerticaConnectionPool(_config(limit=1))
    with pytest.raises(RuntimeError):
        pool.acquire()

    assert pool._current_size == 0  # type: ignore[attr-defined]

    conn = pool.acquire()
    pool.release(conn)
    pool.close_all()
