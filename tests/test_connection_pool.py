import sys
import types
from pathlib import Path

import pytest
from unittest.mock import Mock, patch

# Create a stub for vertica_python before importing the connection module
vertica_stub = types.ModuleType("vertica_python")
class _DummyConn:
    pass

vertica_stub.Connection = _DummyConn
vertica_stub.connect = lambda *args, **kwargs: _DummyConn()
sys.modules["vertica_python"] = vertica_stub

sys.path.append(str(Path(__file__).resolve().parents[1] / "src" / "mcp_vertica"))

from connection import VerticaConfig, VerticaConnectionPool


class FakeConnection:
    def __init__(self, is_closed: bool):
        self._closed = is_closed

    def closed(self):
        return self._closed

    def close(self):
        self._closed = True


def make_config() -> VerticaConfig:
    return VerticaConfig(
        host="localhost",
        port=5433,
        database="test",
        user="user",
        password="pass",
        connection_limit=1,
    )


def test_active_connections_not_incremented_on_replace_failure():
    config = make_config()
    fake_conn = FakeConnection(is_closed=True)

    with patch(
        "connection.vertica_python.connect",
        side_effect=[fake_conn, Exception("replace fail")],
    ):
        pool = VerticaConnectionPool(config)
        assert pool.active_connections == 0

        with pytest.raises(Exception):
            pool.get_connection()

        assert pool.active_connections == 0


def test_active_connections_reset_after_increment_failure():
    config = make_config()
    open_conn = FakeConnection(is_closed=False)

    with patch(
        "connection.vertica_python.connect", return_value=open_conn
    ):
        pool = VerticaConnectionPool(config)
        assert pool.active_connections == 0

        pool.checked_out_connections = Mock()
        pool.checked_out_connections.add.side_effect = Exception("boom")

        with pytest.raises(Exception):
            pool.get_connection()

        assert pool.active_connections == 0

