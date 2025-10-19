"""Lightweight health endpoint for the MCP server."""

from __future__ import annotations

import logging
import os
import threading
from copy import deepcopy
from typing import Any, Dict, Optional

from starlette.requests import Request
from starlette.responses import JSONResponse

logger = logging.getLogger("mcp-vertica")

_COMPONENT_LOCK = threading.Lock()
_COMPONENTS: Dict[str, Dict[str, Any]] = {}


def _snapshot() -> Dict[str, Any]:
    with _COMPONENT_LOCK:
        components = deepcopy(_COMPONENTS)
    ok = True
    if components:
        ok = all(component.get("ready", False) for component in components.values())
    payload: Dict[str, Any] = {"ok": ok, "components": components}
    return payload


def set_component_status(
    name: str,
    *,
    ready: bool,
    attempts: int,
    last_error: Optional[str],
    last_attempt_utc: Optional[str],
    ready_since_utc: Optional[str],
) -> None:
    """Record health information for a named component."""

    with _COMPONENT_LOCK:
        component_state = {
            "ready": ready,
            "attempts": attempts,
            "last_error": last_error,
            "last_attempt_utc": last_attempt_utc,
            "ready_since_utc": ready_since_utc,
        }
        _COMPONENTS[name] = component_state

    logger.debug(
        "Recorded health component state",
        extra={"component": name, "state": component_state},
    )


def reset_health_state() -> None:
    """Clear any recorded health information (primarily for tests)."""

    with _COMPONENT_LOCK:
        _COMPONENTS.clear()


async def healthz(request: Request) -> JSONResponse:
    """Return health information for HTTP checks."""

    payload = _snapshot()
    require_ready = os.getenv("MCP_HEALTH_REQUIRE_READY", "").lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    status_code = 200 if payload["ok"] or not require_ready else 503
    if not payload["ok"]:
        log_level = logging.WARNING if status_code >= 400 else logging.INFO
        logger.log(
            log_level,
            "healthz degraded",
            extra={
                "components": payload["components"],
                "require_ready": require_ready,
                "status_code": status_code,
            },
        )
    else:
        logger.debug("healthz ok", extra={"components": payload["components"]})
    return JSONResponse(payload, status_code=status_code)
