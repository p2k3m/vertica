import os
import sys
import types
import pytest

# Ensure project root is on sys.path for importing scripts
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# Stub vertica_python module
vp = types.ModuleType("vertica_python")
vp.Connection = object
vp.errors = types.SimpleNamespace(ConnectionError=Exception)
vp.connect = lambda *a, **k: None
sys.modules.setdefault("vertica_python", vp)

# Stub mcp_vertica.connection module
mcp_mod = types.ModuleType("mcp_vertica")
conn_mod = types.ModuleType("mcp_vertica.connection")
class VerticaConnectionManager: ...
class VerticaConfig: ...
conn_mod.VerticaConnectionManager = VerticaConnectionManager
conn_mod.VerticaConfig = VerticaConfig
mcp_mod.connection = conn_mod
sys.modules.setdefault("mcp_vertica", mcp_mod)
sys.modules.setdefault("mcp_vertica.connection", conn_mod)

from scripts.seed_itsm import synthesize_and_load


class MockCursor:
    def __init__(self, fail: bool = False):
        self.copy_calls: list[str] = []
        self.executed: list[str] = []
        self.closed = False
        self.fail = fail

    def execute(self, sql, params=None):
        self.executed.append(sql)

    def copy(self, sql, buf):
        self.copy_calls.append(sql)
        if self.fail:
            raise RuntimeError("copy failed")

    def fetchall(self):
        return []

    def close(self):
        self.closed = True


class MockConnection:
    def __init__(self, cursor: 'MockCursor'):
        self.autocommit = True
        self.cursor_obj = cursor
        self.committed = False
        self.rollback_called = False

    def cursor(self):
        return self.cursor_obj

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rollback_called = True


class DummyManager:
    def __init__(self, conn: MockConnection):
        self.conn = conn
        self.released = False

    def get_connection(self):
        return self.conn

    def release_connection(self, conn):
        self.released = True


def test_synthesize_and_load_issues_copy_statements():
    cursor = MockCursor()
    conn = MockConnection(cursor)
    mgr = DummyManager(conn)

    synthesize_and_load(mgr, n_incidents=1)

    sqls = cursor.copy_calls
    assert any("COPY cmdb.ci" in s for s in sqls)
    assert any("COPY cmdb.ci_rel" in s for s in sqls)
    assert any("COPY itsm.change" in s for s in sqls)
    assert any("COPY itsm.incident" in s for s in sqls)
    assert conn.committed
    assert cursor.closed
    assert mgr.released


def test_synthesize_and_load_rolls_back_on_error():
    cursor = MockCursor(fail=True)
    conn = MockConnection(cursor)
    mgr = DummyManager(conn)

    with pytest.raises(RuntimeError):
        synthesize_and_load(mgr, n_incidents=1)

    assert conn.rollback_called
    assert not conn.committed
    assert cursor.closed
    assert mgr.released
