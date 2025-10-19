"""Main entry-point for the Vertica MCP server."""

from __future__ import annotations

import asyncio
import csv
import io
import json
import logging
import os
import re
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, AsyncIterator, Dict, List, Optional, Sequence

import sqlparse
from mcp.server.fastmcp import Context, FastMCP
from sqlparse import tokens as T
from sqlparse.sql import Identifier, IdentifierList
from starlette.applications import Starlette
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse, Response
from starlette.routing import Mount
import uvicorn

from .connection import OperationType, VerticaConfig, VerticaConnectionManager
from .health import healthz
from .sql_loader import SQL

logger = logging.getLogger("mcp-vertica")


SCHEMA_DEFAULT = os.environ.get("VERTICA_SCHEMA", "mf_shared_provider_default")
VIEW_BS_TO_CI = os.environ.get("VIEW_BS_TO_CI", "v_bs_to_ci_edges")


@dataclass
class Provenance:
    """Metadata emitted with every tool response."""

    request_id: str
    server_time_utc: str
    row_count: int
    stale: bool
    source: Optional[str] = None
    parameters: Optional[Sequence[Any]] = None
    as_of_ts: Optional[str] = None

    def as_dict(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "request_id": self.request_id,
            "server_time_utc": self.server_time_utc,
            "row_count": self.row_count,
            "stale": self.stale,
        }
        if self.source is not None:
            payload["source"] = self.source
        if self.parameters is not None:
            payload["parameters"] = list(self.parameters)
        if self.as_of_ts is not None:
            payload["as_of_ts"] = self.as_of_ts
        return payload


def _sanitize_ident(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", value):
        raise ValueError(f"Invalid identifier: {value!r}")
    return value


def _qual(schema: Optional[str], name: str) -> str:
    if schema:
        return f'{_sanitize_ident(schema)}.{_sanitize_ident(name)}'
    return _sanitize_ident(name)


def _is_stale(value: Optional[str | datetime | int | float]) -> bool:
    if value is None:
        return True
    if isinstance(value, datetime):
        ts = value
    elif isinstance(value, (int, float)):
        ts = datetime.fromtimestamp(float(value), tz=UTC)
    elif isinstance(value, str):
        value = value.strip()
        if not value:
            return True
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S.%fZ"):
            try:
                ts = datetime.strptime(value[:26], fmt)
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=UTC)
                break
            except ValueError:
                continue
        else:
            return True
    else:
        return True
    age = datetime.now(UTC) - ts.astimezone(UTC)
    return age.total_seconds() > 3600


def _extract_operation_type(query: str) -> Optional[OperationType]:
    statements = sqlparse.parse(query)
    if not statements:
        return None
    statement = statements[0]
    idx = -1
    token = None
    while True:
        idx, token = statement.token_next(idx, skip_ws=True, skip_cm=True)
        if token is None:
            return None
        if token.match(T.Keyword, "WITH"):
            idx, token = statement.token_next_by(t=(T.Keyword.DML,))
            if token is None:
                return None
            break
        break
    keyword = token.normalized if token.ttype in T.Keyword else token.value.upper()
    mapping = {
        "SELECT": OperationType.SELECT,
        "INSERT": OperationType.INSERT,
        "UPDATE": OperationType.UPDATE,
        "DELETE": OperationType.DELETE,
        "CREATE": OperationType.DDL,
        "ALTER": OperationType.DDL,
        "DROP": OperationType.DDL,
        "TRUNCATE": OperationType.DDL,
    }
    return mapping.get(keyword)


def _extract_schemas(query: str) -> set[str]:
    schemas: set[str] = set()

    def _walk(token: sqlparse.sql.Token) -> None:
        if isinstance(token, IdentifierList):
            for identifier in token.get_identifiers():
                _walk(identifier)
        elif isinstance(token, Identifier):
            schema = token.get_parent_name()
            if schema:
                schemas.add(schema.strip('"'))
        elif getattr(token, "is_group", False):
            for child in token.tokens:
                _walk(child)

    for statement in sqlparse.parse(query):
        for token in statement.tokens:
            _walk(token)

    regex = re.compile(r'(?:"([^"]+)"|([A-Za-z_][A-Za-z0-9_]*))\s*\.\s*(?:"[^"]+"|[A-Za-z_][A-Za-z0-9_]*)')
    schemas.update(filter(None, (match[0] or match[1] for match in regex.findall(query))))
    return {schema.lower() for schema in schemas}


def _format_rows(rows: Sequence[Sequence[Any]]) -> List[List[Any]]:
    formatted: List[List[Any]] = []
    for row in rows:
        formatted.append([None if cell is None else str(cell) for cell in row])
    return formatted


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _parse_as_of(value: Optional[str]) -> str:
    if not value:
        return _now_iso()
    value = value.strip()
    if not value:
        return _now_iso()
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return value
    return parsed.astimezone(UTC).isoformat()


def _as_datetime(value: str) -> datetime:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        try:
            return datetime.fromtimestamp(float(value), tz=UTC)
        except ValueError:
            return datetime.now(UTC)


class TooManyRequestsError(RuntimeError):
    """Raised when the query limiter rejects a request."""


class QueryLimiter:
    def __init__(self) -> None:
        limit = int(os.getenv("MCP_MAX_CONCURRENT_QUERIES", "4"))
        self._sem = asyncio.Semaphore(max(1, limit))
        self._timeout = float(os.getenv("MCP_MAX_QUERY_WAIT_SECONDS", "5"))
        self._acquired = False

    async def __aenter__(self) -> None:
        try:
            await asyncio.wait_for(self._sem.acquire(), timeout=self._timeout)
            self._acquired = True
        except asyncio.TimeoutError as exc:
            raise TooManyRequestsError("Too many concurrent queries") from exc

    async def __aexit__(self, exc_type, exc, tb) -> None:  # type: ignore[override]
        if self._acquired:
            self._sem.release()
            self._acquired = False


query_limiter = QueryLimiter()


@asynccontextmanager
async def server_lifespan(server: FastMCP) -> AsyncIterator[dict[str, Any]]:
    manager = VerticaConnectionManager()
    try:
        config = VerticaConfig.from_env()
        manager.initialize_default(config)
        logger.info("Vertica connection pool ready", extra={"limit": config.connection_limit})
        yield {"vertica_manager": manager}
    finally:
        manager.close_all()
        logger.info("Vertica connection pool closed")


mcp = FastMCP(
    "Vertica Service",
    dependencies=["vertica-python", "pydantic", "starlette", "uvicorn"],
    lifespan=server_lifespan,
)


class RequestIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        request.state.request_id = request.headers.get("X-Request-Id", str(uuid.uuid4()))
        response = await call_next(request)
        response.headers["X-Request-Id"] = request.state.request_id
        return response


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        path = request.url.path.rstrip("/") or "/"
        if path in {"/healthz", "/_alive"}:
            return await call_next(request)
        token = os.getenv("MCP_HTTP_TOKEN")
        if not token:
            return await call_next(request)
        supplied = request.headers.get("X-API-Key") or request.query_params.get("token")
        if supplied != token:
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        return await call_next(request)


async def _alive(request: Request) -> Response:
    return PlainTextResponse("ok")


async def _tools(request: Request) -> Response:
    payload = {tool.name: tool.description for tool in mcp.tools}
    return JSONResponse(payload)


async def _info(request: Request) -> Response:
    manager: VerticaConnectionManager = request.app.state.vertica_manager
    payload = {
        "version": os.getenv("VERTICA_MCP_VERSION", "unknown"),
        "pool": manager.config.connection_limit,
        "schemas": manager.schema_snapshot(),
    }
    return JSONResponse(payload)


def create_http_app() -> Starlette:
    app = Starlette()
    app.state.vertica_manager = None  # type: ignore[attr-defined]

    @app.on_event("startup")
    async def _on_start() -> None:
        app.state.vertica_manager = mcp.router.state.get("vertica_manager")

    allowed_origins = [origin.strip() for origin in os.getenv("ALLOWED_ORIGINS", "").split(",") if origin.strip()]

    app.add_middleware(RequestIdMiddleware)
    app.add_middleware(AuthMiddleware)
    if allowed_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=allowed_origins,
            allow_methods=["GET", "POST", "OPTIONS"],
            allow_headers=["*"],
        )

    http_app = mcp.http_app()
    routes = [Mount("/", app=http_app)]
    starlette_app = Starlette(routes=routes)
    starlette_app.add_route("/healthz", healthz, methods=["GET"])
    starlette_app.add_route("/_alive", _alive, methods=["GET"])
    starlette_app.add_route("/api/info", _info, methods=["GET"])
    starlette_app.add_route("/tools.json", _tools, methods=["GET"])

    @starlette_app.exception_handler(TooManyRequestsError)
    async def _handle_rate_limit(request: Request, exc: TooManyRequestsError) -> Response:  # pragma: no cover - HTTP wiring
        return JSONResponse({"error": str(exc)}, status_code=429)

    for middleware in app.user_middleware:
        starlette_app.add_middleware(middleware.cls, **middleware.options)

    starlette_app.state.vertica_manager = None  # type: ignore[attr-defined]

    @starlette_app.on_event("startup")
    async def _startup() -> None:
        starlette_app.state.vertica_manager = mcp.router.state.get("vertica_manager")

    return starlette_app


async def run_http(port: int = 8000, host: str = "0.0.0.0") -> None:  # noqa: S104
    app = create_http_app()
    config = uvicorn.Config(app, host=host, port=port, log_level="info")
    server = uvicorn.Server(config)
    await server.serve()


async def run_sse(port: int = 8000) -> None:
    starlette_app = Starlette(routes=[Mount("/", app=mcp.sse_app())])
    starlette_app.add_route("/healthz", healthz, methods=["GET"])
    config = uvicorn.Config(starlette_app, host="0.0.0.0", port=port)  # noqa: S104
    server = uvicorn.Server(config)
    await server.serve()


async def _ensure_permissions(manager: VerticaConnectionManager, query: str) -> None:
    op = _extract_operation_type(query)
    if not op:
        return
    schemas = _extract_schemas(query) or {""}
    for schema in schemas:
        if not manager.is_operation_allowed(schema, op):
            raise PermissionError(f"Operation {op.name} not allowed for schema {schema or '__default__'}")


async def _execute_sql(
    manager: VerticaConnectionManager,
    query: str,
    params: Sequence[Any] | None = None,
    *,
    expect_result: bool = True,
) -> tuple[list[str], list[list[Any]], int, bool]:
    async with query_limiter:
        await asyncio.sleep(0)  # ensure context switch
        with manager.get_cursor() as cursor:
            cursor.execute(query, params or tuple())
            if cursor.description and expect_result:
                rows = cursor.fetchall()
                columns = [desc[0] for desc in cursor.description]
                stale = any(_is_stale(next((cell for cell in row if isinstance(cell, datetime)), None)) for row in rows)
                return columns, _format_rows(rows), len(rows), stale
            return [], [], cursor.rowcount or 0, False


async def _serialize_response(
    ctx: Context,
    columns: list[str],
    rows: list[list[Any]],
    row_count: int,
    stale: bool,
    *,
    source: Optional[str] = None,
    parameters: Optional[Sequence[Any]] = None,
    as_of_ts: Optional[str] = None,
) -> str:
    request_id = getattr(ctx.request_context, "request_id", str(uuid.uuid4()))
    provenance = Provenance(
        request_id=request_id,
        server_time_utc=_now_iso(),
        row_count=row_count,
        stale=stale,
        source=source,
        parameters=parameters,
        as_of_ts=as_of_ts,
    )
    payload = {"columns": columns, "rows": rows, "provenance": provenance.as_dict()}
    accept = ctx.metadata.get("accept") if hasattr(ctx, "metadata") else None
    if accept and "text/csv" in accept:
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(columns)
        writer.writerows(rows)
        return output.getvalue()
    return json.dumps(payload)


@mcp.tool()
async def execute_query(ctx: Context, query: str, *, schema: Optional[str] = None) -> str:
    manager: VerticaConnectionManager = ctx.request_context.lifespan_context["vertica_manager"]
    await ctx.debug(f"Executing query (length={len(query)} chars)")
    _ = schema  # maintained for backwards compatibility
    await _ensure_permissions(manager, query)
    try:
        columns, rows, row_count, stale = await _execute_sql(manager, query, expect_result=True)
        return await _serialize_response(
            ctx,
            columns,
            rows,
            row_count,
            stale,
            source=query,
            as_of_ts=_now_iso(),
        )
    except TooManyRequestsError as exc:
        await ctx.error(str(exc))
        return json.dumps({"error": str(exc)})


@mcp.tool()
async def stream_query(ctx: Context, query: str, *, batch_size: int = 500, schema: Optional[str] = None) -> str:
    manager: VerticaConnectionManager = ctx.request_context.lifespan_context["vertica_manager"]
    await ctx.debug(f"Streaming query in batches of {batch_size}")
    await _ensure_permissions(manager, query)

    try:
        async with query_limiter:
            with manager.get_cursor() as cursor:
                cursor.execute(query)
                if not cursor.description:
                    return json.dumps({"rows_streamed": 0})
                columns = [desc[0] for desc in cursor.description]
                total = 0
                await ctx.send(json.dumps({"columns": columns}))
                while True:
                    batch = cursor.fetchmany(batch_size)
                    if not batch:
                        break
                    total += len(batch)
                    await ctx.send(json.dumps(_format_rows(batch)))
                return json.dumps({"rows_streamed": total})
    except TooManyRequestsError as exc:
        await ctx.error(str(exc))
        return json.dumps({"error": str(exc)})


@mcp.tool()
async def copy_data(ctx: Context, schema: str, table: str, data: List[List[Any]]) -> str:
    manager: VerticaConnectionManager = ctx.request_context.lifespan_context["vertica_manager"]
    target_schema = schema.lower()
    if not manager.is_operation_allowed(target_schema, OperationType.INSERT):
        raise PermissionError(f"INSERT operation not allowed for schema {schema}")
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n", quoting=csv.QUOTE_MINIMAL)
    writer.writerows([["\\N" if cell is None else cell for cell in row] for row in data])
    buffer.seek(0)
    enclose = "'\"'"
    copy_sql = (
        f"COPY {_qual(target_schema, table)} "
        "FROM STDIN DELIMITER ',' "
        f"ENCLOSED BY {enclose} "
        "NULL '\\N'"
    )
    try:
        async with query_limiter:
            with manager.get_cursor() as cursor:
                cursor.copy(copy_sql, buffer)
    except TooManyRequestsError as exc:
        await ctx.error(str(exc))
        return json.dumps({"error": str(exc)})
    provenance = Provenance(
        request_id=str(uuid.uuid4()),
        server_time_utc=datetime.now(UTC).isoformat(),
        row_count=len(data),
        stale=False,
        source=f"COPY {_qual(target_schema, table)}",
        parameters=[len(data)],
        as_of_ts=_now_iso(),
    )
    return json.dumps({"rows_copied": len(data), "provenance": provenance.as_dict()})


def _get_manager(ctx: Context) -> VerticaConnectionManager:
    return ctx.request_context.lifespan_context["vertica_manager"]


async def _run_select(
    ctx: Context,
    sql: str,
    params: Sequence[Any],
    source: str,
    *,
    as_of_ts: Optional[str] = None,
) -> str:
    manager = _get_manager(ctx)
    await ctx.debug(f"Running query for {source}")
    try:
        parameters = tuple(params)
        columns, rows, row_count, stale = await _execute_sql(manager, sql, parameters)
        return await _serialize_response(
            ctx,
            columns,
            rows,
            row_count,
            stale,
            source=source,
            parameters=parameters,
            as_of_ts=as_of_ts,
        )
    except TooManyRequestsError as exc:
        await ctx.error(str(exc))
        return json.dumps({"error": str(exc)})


@mcp.tool()
async def get_event_application(
    ctx: Context,
    field_schema: str = SCHEMA_DEFAULT,
    limit: int = 25,
    as_of_ts: Optional[str] = None,
) -> str:
    as_of = _parse_as_of(as_of_ts)
    sql = SQL.render(SQL.load("get_event_application.sql"), schema=field_schema)
    return await _run_select(
        ctx,
        sql,
        (limit,),
        f"{field_schema}.opr_event",
        as_of_ts=as_of,
    )


@mcp.tool()
async def get_event_ci(
    ctx: Context,
    field_schema: str = SCHEMA_DEFAULT,
    limit: int = 25,
    as_of_ts: Optional[str] = None,
) -> str:
    as_of = _parse_as_of(as_of_ts)
    sql = SQL.render(SQL.load("get_event_ci.sql"), schema=field_schema)
    return await _run_select(
        ctx,
        sql,
        (limit,),
        f"{field_schema}.opr_event",
        as_of_ts=as_of,
    )


@mcp.tool()
async def cis_for_business_service(
    ctx: Context,
    field_schema: str = SCHEMA_DEFAULT,
    bs_id: Optional[str] = None,
    bs_name: Optional[str] = None,
    limit: int = 25,
    as_of_ts: Optional[str] = None,
) -> str:
    cutoff = _parse_as_of(as_of_ts)
    if bs_id:
        sql = SQL.render(
            SQL.load("cis_for_business_service_view.sql"),
            view_bs_to_ci=VIEW_BS_TO_CI,
        )
        return await _run_select(ctx, sql, (bs_id,), VIEW_BS_TO_CI, as_of_ts=cutoff)
    sql = SQL.render(SQL.load("cis_for_business_service_events.sql"), schema=field_schema)
    like = f"%{bs_name}%" if bs_name else None
    params = (bs_name, like, cutoff, limit)
    return await _run_select(
        ctx,
        sql,
        params,
        f"{field_schema}.opr_event",
        as_of_ts=cutoff,
    )


@mcp.tool()
async def collection_for_ci(
    ctx: Context,
    field_schema: str = SCHEMA_DEFAULT,
    ci_cmdb_id: Optional[str] = None,
    search: Optional[str] = None,
    as_of_ts: Optional[str] = None,
) -> str:
    if not ci_cmdb_id and not search:
        raise ValueError("Provide either ci_cmdb_id or search")
    like = f"%{search}%" if search else None
    sql = SQL.render(SQL.load("collection_for_ci.sql"), schema=field_schema)
    params = (
        ci_cmdb_id,
        ci_cmdb_id,
        search,
        like,
        like,
        ci_cmdb_id,
        ci_cmdb_id,
        search,
        like,
        ci_cmdb_id,
        ci_cmdb_id,
        search,
        like,
        like,
    )
    return await _run_select(
        ctx,
        sql,
        params,
        f"{field_schema}.collection",
        as_of_ts=_parse_as_of(as_of_ts),
    )


@mcp.tool()
async def collection_members_nodes(
    ctx: Context,
    cluster_name: str,
    field_schema: str = SCHEMA_DEFAULT,
    as_of_ts: Optional[str] = None,
) -> str:
    sql = SQL.render(SQL.load("collection_members_nodes.sql"), schema=field_schema)
    return await _run_select(
        ctx,
        sql,
        (cluster_name,),
        f"{field_schema}.cloud_gcp_gke_node",
        as_of_ts=_parse_as_of(as_of_ts),
    )


@mcp.tool()
async def collection_members_pods(
    ctx: Context,
    cluster_name: str,
    field_schema: str = SCHEMA_DEFAULT,
    as_of_ts: Optional[str] = None,
) -> str:
    sql = SQL.render(SQL.load("collection_members_pods.sql"), schema=field_schema)
    return await _run_select(
        ctx,
        sql,
        (cluster_name,),
        f"{field_schema}.cloud_gcp_gke_pod",
        as_of_ts=_parse_as_of(as_of_ts),
    )


@mcp.tool()
async def collection_members_containers(
    ctx: Context,
    cluster_name: str,
    field_schema: str = SCHEMA_DEFAULT,
    as_of_ts: Optional[str] = None,
) -> str:
    sql = SQL.render(SQL.load("collection_members_containers.sql"), schema=field_schema)
    return await _run_select(
        ctx,
        sql,
        (cluster_name,),
        f"{field_schema}.cloud_gcp_gke_container",
        as_of_ts=_parse_as_of(as_of_ts),
    )


@mcp.tool()
async def ci_facts_node(
    ctx: Context,
    cmdb_id: str,
    field_schema: str = SCHEMA_DEFAULT,
    as_of_ts: Optional[str] = None,
) -> str:
    sql = SQL.render(SQL.load("ci_facts_node.sql"), schema=field_schema)
    return await _run_select(
        ctx,
        sql,
        (cmdb_id,),
        f"{field_schema}.cloud_gcp_gke_node",
        as_of_ts=_parse_as_of(as_of_ts),
    )


@mcp.tool()
async def ci_facts_pod(
    ctx: Context,
    cmdb_id: str,
    field_schema: str = SCHEMA_DEFAULT,
    as_of_ts: Optional[str] = None,
) -> str:
    sql = SQL.render(SQL.load("ci_facts_pod.sql"), schema=field_schema)
    return await _run_select(
        ctx,
        sql,
        (cmdb_id,),
        f"{field_schema}.cloud_gcp_gke_pod",
        as_of_ts=_parse_as_of(as_of_ts),
    )


@mcp.tool()
async def ci_facts_container(
    ctx: Context,
    cmdb_id: str,
    field_schema: str = SCHEMA_DEFAULT,
    as_of_ts: Optional[str] = None,
) -> str:
    sql = SQL.render(SQL.load("ci_facts_container.sql"), schema=field_schema)
    return await _run_select(
        ctx,
        sql,
        (cmdb_id,),
        f"{field_schema}.cloud_gcp_gke_container",
        as_of_ts=_parse_as_of(as_of_ts),
    )


@mcp.tool()
async def ci_facts_security_7d(
    ctx: Context,
    cmdb_id: str,
    field_schema: str = SCHEMA_DEFAULT,
    end_ts: Optional[str] = None,
) -> str:
    end = _parse_as_of(end_ts)
    start = (_as_datetime(end) - timedelta(days=7)).astimezone(UTC).isoformat()
    sql = SQL.render(SQL.load("ci_facts_security_7d.sql"), schema=field_schema)
    params = (cmdb_id, start, end)
    return await _run_select(
        ctx,
        sql,
        params,
        f"{field_schema}.opr_event",
        as_of_ts=end,
    )


@mcp.tool()
async def gke_identify_application_pod(
    ctx: Context,
    search: str,
    field_schema: str = SCHEMA_DEFAULT,
    limit: int = 25,
    as_of_ts: Optional[str] = None,
) -> str:
    like = f"%{search}%"
    sql = SQL.render(SQL.load("gke_identify_application_pod.sql"), schema=field_schema)
    params = (like, like, limit)
    return await _run_select(
        ctx,
        sql,
        params,
        f"{field_schema}.cloud_gcp_gke_pod",
        as_of_ts=_parse_as_of(as_of_ts),
    )


@mcp.tool()
async def gke_identify_pod_cluster(
    ctx: Context,
    pod_id: str,
    field_schema: str = SCHEMA_DEFAULT,
    as_of_ts: Optional[str] = None,
) -> str:
    sql = SQL.render(SQL.load("gke_identify_pod_cluster.sql"), schema=field_schema)
    return await _run_select(
        ctx,
        sql,
        (pod_id,),
        f"{field_schema}.cloud_gcp_gke_pod",
        as_of_ts=_parse_as_of(as_of_ts),
    )


@mcp.tool()
async def gke_identify_pod_node(
    ctx: Context,
    pod_id: str,
    field_schema: str = SCHEMA_DEFAULT,
    as_of_ts: Optional[str] = None,
) -> str:
    sql = SQL.render(SQL.load("gke_identify_pod_node.sql"), schema=field_schema)
    return await _run_select(
        ctx,
        sql,
        (pod_id,),
        f"{field_schema}.cloud_gcp_gke_node",
        as_of_ts=_parse_as_of(as_of_ts),
    )


@mcp.tool()
async def repeat_issues(
    ctx: Context,
    cmdb_id: str,
    field_schema: str = SCHEMA_DEFAULT,
    lookback_hours: int = 72,
    limit: int = 25,
    token_filter: str = "TRUE",
    as_of_ts: Optional[str] = None,
) -> str:
    end = _parse_as_of(as_of_ts)
    start = (_as_datetime(end) - timedelta(hours=lookback_hours)).astimezone(UTC).isoformat()
    sql = SQL.render(SQL.load("repeat_issues.sql"), schema=field_schema)
    params = (
        cmdb_id,
        cmdb_id,
        cmdb_id,
        start,
        end,
        token_filter,
        end,
        limit,
    )
    return await _run_select(
        ctx,
        sql,
        params,
        f"{field_schema}.opr_event",
        as_of_ts=end,
    )


@mcp.tool()
async def api_info(ctx: Context) -> str:
    manager = _get_manager(ctx)
    payload = {
        "version": os.getenv("VERTICA_MCP_VERSION", "unknown"),
        "pool": manager.config.connection_limit,
        "schemas": manager.schema_snapshot(),
    }
    return json.dumps(payload)


__all__ = ["mcp", "run_http", "run_sse"]
