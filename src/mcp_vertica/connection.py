import os
import logging
from queue import Queue, Empty
import threading
import vertica_python
from typing import Dict, Any, Optional, Set
from dataclasses import dataclass
from enum import Enum, auto

# Constants for environment variables
VERTICA_HOST = "VERTICA_HOST"
VERTICA_PORT = "VERTICA_PORT"
VERTICA_DATABASE = "VERTICA_DATABASE"
VERTICA_USER = "VERTICA_USER"
VERTICA_PASSWORD = "VERTICA_PASSWORD"
VERTICA_CONNECTION_LIMIT = "VERTICA_CONNECTION_LIMIT"
VERTICA_SSL = "VERTICA_SSL"
VERTICA_SSL_REJECT_UNAUTHORIZED = "VERTICA_SSL_REJECT_UNAUTHORIZED"

# Configure logging
logger = logging.getLogger("mcp-vertica")

class OperationType(Enum):
    SELECT = auto()
    INSERT = auto()
    UPDATE = auto()
    DELETE = auto()
    DDL = auto()

@dataclass
class SchemaPermissions:
    select: bool = False
    insert: bool = False
    update: bool = False
    delete: bool = False
    ddl: bool = False

@dataclass
class VerticaConfig:
    host: str
    port: int
    database: str
    user: str
    password: str
    connection_limit: int = 10
    ssl: bool = False
    ssl_reject_unauthorized: bool = True
    # Global operation permissions
    allow_select: bool = True
    allow_insert: bool = False
    allow_update: bool = False
    allow_delete: bool = False
    allow_ddl: bool = False
    # Schema-specific permissions
    schema_permissions: Optional[Dict[str, SchemaPermissions]] = None

    def __post_init__(self):
        if self.schema_permissions is None:
            self.schema_permissions = {}

    @classmethod
    def from_env(cls) -> 'VerticaConfig':
        """Create config from environment variables."""
        # Parse schema permissions
        schema_permissions = {}
        for schema_perm in [
            ("SCHEMA_SELECT_PERMISSIONS", "select"),
            ("SCHEMA_INSERT_PERMISSIONS", "insert"),
            ("SCHEMA_UPDATE_PERMISSIONS", "update"),
            ("SCHEMA_DELETE_PERMISSIONS", "delete"),
            ("SCHEMA_DDL_PERMISSIONS", "ddl")
        ]:
            env_var, perm_type = schema_perm
            if perm_str := os.getenv(env_var):
                for pair in perm_str.split(','):
                    pair = pair.strip()
                    if not pair:
                        continue
                    try:
                        schema, value = pair.split(':', 1)
                    except ValueError:
                        logger.warning(
                            "Invalid schema permission entry '%s' in %s", pair, env_var
                        )
                        continue
                    schema = schema.strip().lower()
                    if schema not in schema_permissions:
                        schema_permissions[schema] = SchemaPermissions()
                    setattr(
                        schema_permissions[schema],
                        perm_type,
                        value.strip().lower() == 'true',
                    )

        if not schema_permissions:
            logger.info(
                "No schema-specific permissions configured; defaulting to global settings "
                "for SELECT, INSERT, UPDATE, DELETE, and DDL operations."
            )

        return cls(
            host=os.getenv("VERTICA_HOST", "localhost"),
            port=int(os.getenv("VERTICA_PORT", "5433")),
            database=os.getenv("VERTICA_DATABASE", "VMart"),
            user=os.getenv("VERTICA_USER", "dbadmin"),
            password=os.getenv("VERTICA_PASSWORD", ""),
            connection_limit=int(os.getenv("VERTICA_CONNECTION_LIMIT", "10")),
            ssl=os.getenv("VERTICA_SSL", "false").lower() == "true",
            ssl_reject_unauthorized=os.getenv("VERTICA_SSL_REJECT_UNAUTHORIZED", "true").lower() == "true",
            allow_select=os.getenv("ALLOW_SELECT_OPERATION", "true").lower() == "true",
            allow_insert=os.getenv("ALLOW_INSERT_OPERATION", "false").lower() == "true",
            allow_update=os.getenv("ALLOW_UPDATE_OPERATION", "false").lower() == "true",
            allow_delete=os.getenv("ALLOW_DELETE_OPERATION", "false").lower() == "true",
            allow_ddl=os.getenv("ALLOW_DDL_OPERATION", "false").lower() == "true",
            schema_permissions=schema_permissions
        )

class VerticaConnectionPool:
    def __init__(self, config: VerticaConfig):
        self.config = config
        self.pool: Queue = Queue(maxsize=config.connection_limit)
        self.active_connections = 0
        self.lock = threading.Lock()
        # Track connections currently checked out of the pool to prevent
        # double releases or releasing connections that were never acquired
        self.checked_out_connections: Set[vertica_python.Connection] = set()
        # Track pool rebuild attempts to avoid infinite loops
        self.rebuild_attempts = 0
        self.max_rebuild_attempts = 3
        try:
            self._initialize_pool()
        except Exception as e:
            logger.error("Failed to initialize connection pool: %s", e)
            raise

    def _get_connection_config(self) -> Dict[str, Any]:
        """Get connection configuration with SSL settings if enabled."""
        config = {
            "host": self.config.host,
            "port": self.config.port,
            "database": self.config.database,
            "user": self.config.user,
            "password": self.config.password,
        }

        if self.config.ssl:
            config["ssl"] = True
            config["ssl_reject_unauthorized"] = self.config.ssl_reject_unauthorized
        else:
            config["tlsmode"] = "disable"
        logger.debug("Connection config: %s", self._get_safe_config(config))
        return config

    def _get_safe_config(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """Create a safe version of the config for logging by masking sensitive data."""
        safe_config = config.copy()
        if "password" in safe_config:
            safe_config["password"] = "********"
        return safe_config

    def _initialize_pool(self):
        """Initialize or rebuild the connection pool."""
        # Close any connections that are currently checked out
        for conn in list(self.checked_out_connections):
            try:
                conn.close()
            except Exception as e:
                logger.error(
                    "Error closing checked-out connection during pool rebuild: %s", e
                )

        # Clear checked out connections and reset the active connection count
        self.checked_out_connections.clear()
        self.active_connections = 0

        # If the pool already has connections, we are rebuilding after a failure.
        # Close existing idle connections and reset the accounting so we start fresh.
        if not self.pool.empty():
            logger.warning(
                "Rebuilding Vertica connection pool; closing existing idle connections",
            )
            while not self.pool.empty():
                try:
                    conn = self.pool.get_nowait()
                    conn.close()
                except Exception as e:
                    logger.error(
                        "Error closing connection during pool rebuild: %s", e
                    )
            # Reset connection count since all existing connections are closed
            self.active_connections = 0

        logger.info(
            f"Initializing Vertica connection pool with {self.config.connection_limit} connections"
        )
        created_connections = []
        for _ in range(self.config.connection_limit):
            try:
                conn = vertica_python.connect(**self._get_connection_config())
                self.pool.put(conn)
                created_connections.append(conn)
            except Exception as e:
                logger.error(f"Failed to create connection: {str(e)}")
                # Close any connections that were successfully created
                for created_conn in created_connections:
                    try:
                        created_conn.close()
                    except Exception as close_error:
                        logger.error(
                            "Error closing connection during pool initialization: %s",
                            close_error,
                        )
                # Ensure the queue is empty
                while not self.pool.empty():
                    try:
                        self.pool.get_nowait()
                    except Exception:
                        break
                # Reset active connection count
                self.active_connections = 0
                raise
        # Reset rebuild attempts after successful initialization
        self.rebuild_attempts = 0

    def _log_pool_diagnostics(self) -> None:
        """Log diagnostic information about the pool state."""
        logger.error(
            "Pool diagnostics: active_connections=%d, queue_size=%d, checked_out=%d",
            self.active_connections,
            self.pool.qsize(),
            len(self.checked_out_connections),
        )

    def _handle_rebuild(self) -> None:
        """Attempt to rebuild the pool with a limited number of retries."""
        if self.rebuild_attempts >= self.max_rebuild_attempts:
            logger.error(
                "Maximum pool rebuild attempts (%d) reached; skipping rebuild",
                self.max_rebuild_attempts,
            )
            return

        self.rebuild_attempts += 1
        logger.info(
            "Attempting to rebuild connection pool (attempt %d/%d)",
            self.rebuild_attempts,
            self.max_rebuild_attempts,
        )
        try:
            self._initialize_pool()
        except Exception as rebuild_error:
            logger.error(
                "Pool rebuild attempt %d failed: %s",
                self.rebuild_attempts,
                rebuild_error,
                exc_info=True,
            )

    def get_connection(self) -> vertica_python.Connection:
        """Get a connection from the pool."""
        with self.lock:
            if self.active_connections >= self.config.connection_limit:
                raise Exception("No available connections in the pool")

            connection_counted = False
            try:
                try:
                    conn = self.pool.get(timeout=5)  # 5 second timeout
                except Empty:
                    logger.warning("Timed out waiting for connection from pool")
                    raise Exception("Timeout waiting for connection from pool")
                except Exception as e:
                    logger.error(
                        "Failed to retrieve connection from queue: %s", e, exc_info=True
                    )
                    self._log_pool_diagnostics()
                    self._handle_rebuild()
                    raise

                if conn.closed():
                    logger.warning(
                        "Retrieved Vertica connection is closed; attempting to replace it"
                    )
                    try:
                        conn.close()
                    except Exception:
                        pass
                    try:
                        conn = vertica_python.connect(**self._get_connection_config())
                    except Exception as e:
                        logger.error(
                            "Failed to create replacement connection: %s", e, exc_info=True
                        )
                        self._log_pool_diagnostics()
                        self._handle_rebuild()
                        raise

                self.active_connections += 1
                connection_counted = True
                # Track the connection as checked out so we can verify it on release
                self.checked_out_connections.add(conn)
                return conn
            except Exception:
                if connection_counted and self.active_connections > 0:
                    self.active_connections -= 1
                raise

    def release_connection(self, conn: vertica_python.Connection):
        """Release a connection back to the pool."""
        with self.lock:
            if conn not in self.checked_out_connections:
                # If the connection wasn't checked out, avoid adding it back to
                # the pool and warn to help catch potential double releases.
                logger.warning(
                    "Attempted to release connection not checked out from pool"
                )
                return

            # The connection is being returned, remove it from the tracked set
            self.checked_out_connections.remove(conn)

            if conn.closed():
                logger.warning(
                    "Released Vertica connection is closed; attempting to replace it"
                )
                try:
                    new_conn = vertica_python.connect(**self._get_connection_config())
                    self.pool.put(new_conn)
                except Exception as e:
                    logger.warning(
                        "Failed to create replacement Vertica connection: %s", e
                    )
            else:
                try:
                    self.pool.put(conn)
                except Exception as e:
                    logger.error(
                        f"Failed to release connection to pool: {str(e)}"
                    )
                    try:
                        conn.close()
                    except Exception as close_error:
                        logger.error(
                            f"Failed to close connection: {close_error}"
                        )

            if self.active_connections > 0:
                self.active_connections -= 1
            else:
                logger.warning(
                    "Active connection count is already zero; cannot decrement"
                )

    def close_all(self):
        """Close all connections in the pool."""
        with self.lock:
            while not self.pool.empty():
                try:
                    conn = self.pool.get_nowait()
                    conn.close()
                except Exception as e:
                    logger.error(f"Error closing connection: {e}")

            # Close any connections that are currently checked out
            for conn in list(self.checked_out_connections):
                try:
                    conn.close()
                except Exception as e:
                    logger.error(
                        f"Error closing checked-out connection: {e}"
                    )

            # Clear tracking and reset counters
            self.checked_out_connections.clear()
            self.active_connections = 0

class VerticaConnectionManager:
    def __init__(self):
        self.pool: Optional[VerticaConnectionPool] = None
        self.config: Optional[VerticaConfig] = None
        self.lock = threading.Lock()
        self.is_multi_db_mode: bool = False

    def initialize_default(self, config: VerticaConfig):
        """Initialize the connection pool."""
        self.config = config
        self.is_multi_db_mode = not config.database
        if self.pool:
            self.pool.close_all()
        self.pool = VerticaConnectionPool(config)

    def get_connection(self) -> vertica_python.Connection:
        """Get a connection from the pool. Vertica does not support runtime database switching."""
        if not self.pool:
            raise Exception("Connection pool not initialized")
        conn = self.pool.get_connection()
        return conn

    def release_connection(self, conn: vertica_python.Connection):
        """Release a connection back to the pool."""
        if self.pool:
            self.pool.release_connection(conn)

    def is_operation_allowed(self, schema: str, operation: OperationType) -> bool:
        """Check if an operation is allowed for a specific schema."""
        if not self.config:
            return False

        # Normalize schema name for case-insensitive comparisons
        schema = schema.lower()

        # Get schema permissions
        schema_permissions = self.config.schema_permissions or {}
        schema_perms = schema_permissions.get(schema)

        # Check schema-specific permissions first
        if schema_perms:
            if operation == OperationType.SELECT:
                return schema_perms.select
            if operation == OperationType.INSERT:
                return schema_perms.insert
            elif operation == OperationType.UPDATE:
                return schema_perms.update
            elif operation == OperationType.DELETE:
                return schema_perms.delete
            elif operation == OperationType.DDL:
                return schema_perms.ddl

        # Fall back to global permissions
        if operation == OperationType.SELECT:
            return self.config.allow_select
        elif operation == OperationType.INSERT:
            return self.config.allow_insert
        elif operation == OperationType.UPDATE:
            return self.config.allow_update
        elif operation == OperationType.DELETE:
            return self.config.allow_delete
        elif operation == OperationType.DDL:
            return self.config.allow_ddl

        return False

    def close_all(self):
        """Close all connections in the pool."""
        if self.pool:
            self.pool.close_all()
