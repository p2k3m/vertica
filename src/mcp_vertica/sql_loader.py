"""Utility helpers for loading SQL templates."""

from __future__ import annotations

from importlib import resources
from pathlib import Path
from typing import Iterable


def _candidate_paths(name: str) -> Iterable[Path]:
    base = Path(__file__).resolve().parent
    yield base / "sql" / name
    yield base.parent.parent / "sql" / name


def load_sql(name: str) -> str:
    """Load a SQL template from the packaged resources.

    The function first attempts to resolve ``sql/<name>`` within the Python
    package and then falls back to repository-relative lookup. This allows the
    server to run both from source and when installed as a package.
    """

    try:
        package_contents = resources.files("sql").joinpath(name)
        if package_contents.is_file():
            return package_contents.read_text("utf-8")
    except (FileNotFoundError, ModuleNotFoundError):
        pass

    for candidate in _candidate_paths(name):
        if candidate.is_file():
            return candidate.read_text("utf-8")

    raise FileNotFoundError(f"SQL template not found: {name}")

