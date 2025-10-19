"""Connection management and permission enforcement for Vertica."""

from __future__ import annotations

import contextlib
import logging
import os
import queue
import threading
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Dict, Iterable, Optional

import vertica_python

logger = logging.getLogger("mcp-vertica")


class OperationType(Enum):
    """Supported SQL operation classes."""

    SELECT = auto()
    INSERT = auto()
    UPDATE = auto()
    DELETE = auto()
    DDL = auto()


@dataclass
class SchemaPermissions:
    """Per-schema permissions for each SQL operation class."""

    select: bool = False
    insert: bool = False
    update: bool = False
    delete: bool = False
    ddl: bool = False

    def as_dict(self) -> Dict[str, bool]:
        return {
            "select": self.select,
            "insert": self.insert,
            "update": self.update,
            "delete": self.delete,
            "ddl": self.ddl,
        }


@dataclass
class VerticaConfig:
    """Vertica connection configuration sourced from environment variables."""

    host: str
    port: int
    database: str
    user: str
    password: str
    connection_limit: int = 5
    ssl: bool = False
    ssl_reject_unauthorized: bool = True
    allow_select: bool = True
    allow_insert: bool = False
    allow_update: bool = False
    allow_delete: bool = False
    allow_ddl: bool = False
    schema_permissions: Dict[str, SchemaPermissions] = field(default_factory=dict)
    read_only: bool = False

    @classmethod
    def from_env(cls) -> "VerticaConfig":
        """Create a configuration instance from process environment variables."""

        def _get_bool(key: str, default: bool = False) -> bool:
            return os.getenv(key, str(default)).strip().lower() in {"1", "true", "yes", "on"}

        schema_permissions: Dict[str, SchemaPermissions] = {}
        permission_envs = {
            "SCHEMA_SELECT_PERMISSIONS": "select",
            "SCHEMA_INSERT_PERMISSIONS": "insert",
            "SCHEMA_UPDATE_PERMISSIONS": "update",
            "SCHEMA_DELETE_PERMISSIONS": "delete",
            "SCHEMA_DDL_PERMISSIONS": "ddl",
        }
        for env_var, perm_name in permission_envs.items():
            raw = os.getenv(env_var, "").strip()
            if not raw:
                continue
            for pair in raw.split(","):
                if not pair:
                    continue
                try:
                    schema, value = (part.strip() for part in pair.split(":", 1))
                except ValueError:
                    logger.warning("Invalid schema permission entry '%s' in %s", pair, env_var)
                    continue
                schema = schema.lower()
                perm = schema_permissions.setdefault(schema, SchemaPermissions())
                setattr(perm, perm_name, value.lower() in {"1", "true", "yes", "on"})

        return cls(
            host=os.getenv("VERTICA_HOST", "localhost"),
            port=int(os.getenv("VERTICA_PORT", "5433")),
            database=os.getenv("VERTICA_DATABASE", "VMart"),
            user=os.getenv("VERTICA_USER", "dbadmin"),
            password=os.getenv("VERTICA_PASSWORD", ""),
            connection_limit=max(1, int(os.getenv("VERTICA_CONNECTION_LIMIT", "5"))),
            ssl=_get_bool("VERTICA_SSL"),
            ssl_reject_unauthorized=_get_bool("VERTICA_SSL_REJECT_UNAUTHORIZED", True),
            allow_select=_get_bool("ALLOW_SELECT_OPERATION", True),
            allow_insert=_get_bool("ALLOW_INSERT_OPERATION"),
            allow_update=_get_bool("ALLOW_UPDATE_OPERATION"),
            allow_delete=_get_bool("ALLOW_DELETE_OPERATION"),
            allow_ddl=_get_bool("ALLOW_DDL_OPERATION"),
            schema_permissions=schema_permissions,
            read_only=_get_bool("MCP_READ_ONLY"),
        )


class VerticaConnectionPool:
    """Thread-safe connection pool for Vertica."""

    def __init__(self, config: VerticaConfig):
        self._config = config
        self._pool: "queue.LifoQueue[vertica_python.Connection]" = queue.LifoQueue(maxsize=config.connection_limit)
        self._checked_out: set[vertica_python.Connection] = set()
        self._lock = threading.Lock()
        self._shutdown = threading.Event()
        self._metrics_thread = threading.Thread(
            target=self._emit_metrics, name="vertica-pool-metrics", daemon=True
        )
        self._initialize_pool()
        self._metrics_thread.start()

    def _emit_metrics(self) -> None:
        """Emit pool metrics periodically for observability."""
        while not self._shutdown.wait(timeout=60):
            try:
                logger.debug(
                    "pool-status",
                    extra={
                        "checked_out": len(self._checked_out),
                        "available": self._pool.qsize(),
                        "capacity": self._config.connection_limit,
                    },
                )
            except Exception:  # pragma: no cover - defensive
                logger.exception("Failed to emit pool metrics")

    def _get_connection_kwargs(self) -> Dict[str, Any]:
        cfg: Dict[str, Any] = {
            "host": self._config.host,
            "port": self._config.port,
            "database": self._config.database,
            "user": self._config.user,
            "password": self._config.password,
        }
        if self._config.ssl:
            cfg["ssl"] = True
            cfg["ssl_verify"] = self._config.ssl_reject_unauthorized
        else:
            cfg["ssl"] = False
        return cfg

    def _initialize_pool(self) -> None:
        logger.info(
            "initializing-vertica-pool", extra={"limit": self._config.connection_limit, "host": self._config.host}
        )
        for _ in range(self._config.connection_limit):
            conn = vertica_python.connect(**self._get_connection_kwargs())
            self._pool.put(conn)

    def acquire(self, timeout: float = 30.0) -> vertica_python.Connection:
        try:
            conn = self._pool.get(timeout=timeout)
        except queue.Empty as exc:  # pragma: no cover - defensive
            raise TimeoutError("Timed out waiting for a Vertica connection") from exc
        with self._lock:
            self._checked_out.add(conn)
        return conn

    def release(self, conn: vertica_python.Connection) -> None:
        with self._lock:
            if conn not in self._checked_out:
                logger.warning("Ignoring release of unmanaged connection")
                return
            self._checked_out.remove(conn)
        try:
            if conn.closed():
                conn = vertica_python.connect(**self._get_connection_kwargs())
            self._pool.put(conn, block=False)
        except queue.Full:  # pragma: no cover - defensive
            conn.close()

    def close_all(self) -> None:
        self._shutdown.set()
        with contextlib.suppress(Exception):
            if self._metrics_thread.is_alive():
                self._metrics_thread.join(timeout=1)
        while not self._pool.empty():
            conn = self._pool.get_nowait()
            with contextlib.suppress(Exception):
                conn.close()
        for conn in list(self._checked_out):
            with contextlib.suppress(Exception):
                conn.close()
        self._checked_out.clear()


class VerticaConnectionManager:
    """High-level facade for connection pooling and permission checks."""

    def __init__(self) -> None:
        self._pool: Optional[VerticaConnectionPool] = None
        self._config: Optional[VerticaConfig] = None
        self._lock = threading.Lock()

    def initialize_default(self, config: VerticaConfig) -> None:
        with self._lock:
            if self._pool is not None:
                logger.debug("Re-initializing Vertica pool")
                self._pool.close_all()
            self._pool = VerticaConnectionPool(config)
            self._config = config

    def get_connection(self, timeout: float = 30.0) -> vertica_python.Connection:
        if not self._pool:
            raise RuntimeError("Connection pool has not been initialized")
        return self._pool.acquire(timeout=timeout)

    def release_connection(self, conn: vertica_python.Connection) -> None:
        if not self._pool:
            raise RuntimeError("Connection pool has not been initialized")
        self._pool.release(conn)

    def close_all(self) -> None:
        if self._pool:
            self._pool.close_all()
            self._pool = None

    @property
    def config(self) -> VerticaConfig:
        if not self._config:
            raise RuntimeError("Connection manager not initialized")
        return self._config

    def is_operation_allowed(self, schema: str, operation: OperationType) -> bool:
        cfg = self.config
        if cfg.read_only and operation is not OperationType.SELECT:
            return False
        if schema:
            perm = cfg.schema_permissions.get(schema.lower())
            if perm:
                mapping = {
                    OperationType.SELECT: perm.select,
                    OperationType.INSERT: perm.insert,
                    OperationType.UPDATE: perm.update,
                    OperationType.DELETE: perm.delete,
                    OperationType.DDL: perm.ddl,
                }
                return mapping[operation]
        mapping = {
            OperationType.SELECT: cfg.allow_select,
            OperationType.INSERT: cfg.allow_insert,
            OperationType.UPDATE: cfg.allow_update,
            OperationType.DELETE: cfg.allow_delete,
            OperationType.DDL: cfg.allow_ddl,
        }
        return mapping[operation]

    def schema_snapshot(self) -> Dict[str, Dict[str, bool]]:
        cfg = self.config
        merged: Dict[str, Dict[str, bool]] = {schema: perm.as_dict() for schema, perm in cfg.schema_permissions.items()}
        merged["__global__"] = {
            "select": cfg.allow_select,
            "insert": cfg.allow_insert,
            "update": cfg.allow_update,
            "delete": cfg.allow_delete,
            "ddl": cfg.allow_ddl,
            "read_only": cfg.read_only,
        }
        return merged

    @contextlib.contextmanager
    def get_cursor(self, *, timeout: float = 30.0) -> Iterable[vertica_python.Cursor]:
        conn = self.get_connection(timeout=timeout)
        cursor = conn.cursor()
        try:
            yield cursor
            if not cursor.closed():
                conn.commit()
        finally:
            with contextlib.suppress(Exception):
                cursor.close()
            self.release_connection(conn)

