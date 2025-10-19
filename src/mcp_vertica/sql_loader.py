"""Helpers for loading SQL templates shipped with the MCP server."""

from __future__ import annotations

from importlib import resources
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
SQL_DIR = PACKAGE_ROOT / "sql"


class SQL:
    @staticmethod
    def load(name: str) -> str:
        path = SQL_DIR / name
        if path.exists():
            return path.read_text(encoding="utf-8")
        try:
            candidate = resources.files("sql").joinpath(name)
            if candidate.is_file():
                return candidate.read_text("utf-8")
        except (FileNotFoundError, ModuleNotFoundError):
            pass
        raise FileNotFoundError(f"SQL file not found: {path}")

    @staticmethod
    def render(sql: str, **kwargs) -> str:
        allowed = {k: v for k, v in kwargs.items() if k in {"schema", "view_bs_to_ci"}}
        rendered = sql
        for key, value in allowed.items():
            rendered = rendered.replace("{" + key + "}", str(value))
        return rendered

