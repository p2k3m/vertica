import os
from typing import Generator

import pytest


@pytest.fixture(autouse=True)
def _set_test_env() -> Generator[None, None, None]:
    original = dict(os.environ)
    os.environ.setdefault("MCP_READ_ONLY", "true")
    os.environ.setdefault("VERTICA_CONNECTION_LIMIT", "1")
    yield
    os.environ.clear()
    os.environ.update(original)
