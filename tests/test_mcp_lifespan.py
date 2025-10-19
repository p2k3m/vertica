"""Tests covering the MCP server lifespan management."""

from __future__ import annotations

import asyncio
from types import ModuleType, SimpleNamespace

import sys

import pytest

try:
    import sqlparse  # type: ignore  # noqa: F401
except ModuleNotFoundError:
    sqlparse_stub = ModuleType("sqlparse")
    sqlparse_stub.parse = lambda value: []

    class _Keyword:
        DML = object()

    tokens_stub = ModuleType("sqlparse.tokens")
    tokens_stub.Keyword = _Keyword

    sql_module_stub = ModuleType("sqlparse.sql")
    sql_module_stub.Identifier = type("Identifier", (), {})
    sql_module_stub.IdentifierList = type("IdentifierList", (), {})

    sys.modules.setdefault("sqlparse", sqlparse_stub)
    sys.modules.setdefault("sqlparse.tokens", tokens_stub)
    sys.modules.setdefault("sqlparse.sql", sql_module_stub)

from mcp_vertica import mcp as mcp_module


def test_server_lifespan_eventually_recovers(monkeypatch) -> None:
    """The server lifespan should keep retrying until Vertica is ready."""

    statuses: list[tuple[str, dict[str, object]]] = []
    ready_event = asyncio.Event()
    attempts: dict[str, int] = {"count": 0}

    class DummyManager:
        def __init__(self) -> None:
            self.closed = False
            self.config = SimpleNamespace(connection_limit=0)

        def initialize_default(self, config: SimpleNamespace) -> None:
            attempts["count"] += 1
            if attempts["count"] < 3:
                raise RuntimeError("boom")
            self.config = config
            ready_event.set()

        def close_all(self) -> None:
            self.closed = True

        def schema_snapshot(self) -> dict[str, dict[str, bool]]:
            return {}

    dummy_config = SimpleNamespace(connection_limit=5)

    monkeypatch.setattr(mcp_module, "VerticaConnectionManager", DummyManager)
    monkeypatch.setattr(
        mcp_module.VerticaConfig,
        "from_env",
        classmethod(lambda cls: dummy_config),
    )
    monkeypatch.setenv("MCP_INIT_RETRY_SECONDS", "0.01")
    monkeypatch.setenv("MCP_INIT_MAX_RETRY_SECONDS", "0.01")

    def _record_status(name: str, **state: object) -> None:
        statuses.append((name, state))

    monkeypatch.setattr(mcp_module, "set_component_status", _record_status)

    async def _run_test() -> None:
        async with mcp_module.server_lifespan(mcp_module.mcp) as context:
            await asyncio.wait_for(ready_event.wait(), timeout=1)
            manager = context["vertica_manager"]
            assert manager.config is dummy_config
            assert attempts["count"] == 3
        assert manager.closed

    asyncio.run(_run_test())

    assert statuses[0][1]["ready"] is False
    assert any(state["ready"] for _, state in statuses)
    assert statuses[-1][1]["ready"] is False
