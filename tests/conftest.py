import sys
import types


def _install_vertica_stub() -> None:
    if "vertica_python" in sys.modules:
        return

    module = types.ModuleType("vertica_python")

    class _StubConnection:
        def __init__(self, *_, **__):
            self._closed = False

        def close(self) -> None:
            self._closed = True

        def closed(self) -> bool:  # pragma: no cover - behaviour matches vertica_python
            return self._closed

        def cursor(self):  # pragma: no cover - compatibility shim
            return types.SimpleNamespace(closed=lambda: False, close=lambda: None)

    def _connect(**kwargs):  # pragma: no cover - patched in tests
        raise RuntimeError("vertica_python stub connect invoked")

    module.connect = _connect
    module.Connection = _StubConnection
    module.Cursor = types.SimpleNamespace
    sys.modules["vertica_python"] = module


_install_vertica_stub()
