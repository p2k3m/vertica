"""Lightweight health endpoint for the MCP server."""

from __future__ import annotations

from starlette.requests import Request
from starlette.responses import JSONResponse


async def healthz(request: Request) -> JSONResponse:
    """Return a simple 200 OK body for HTTP health checks."""

    return JSONResponse({"ok": True})
