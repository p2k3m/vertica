from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, List
from mcp.server.fastmcp import FastMCP, Context
import logging
import re
import json
import sqlparse
from sqlparse import tokens as T
from sqlparse.sql import Identifier, IdentifierList
from .connection import VerticaConnectionManager, VerticaConfig, OperationType
from starlette.applications import Starlette
from starlette.routing import Mount
import uvicorn
import csv
import io

# Configure logging
logger = logging.getLogger("mcp-vertica")

def extract_operation_type(query: str) -> OperationType | None:
    """Extract the operation type from a SQL query.

    The query is parsed with :mod:`sqlparse` and the first meaningful token is
    inspected. Leading comments and ``WITH``/CTE blocks are skipped before
    determining the command keyword.
    """

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

        # Skip initial WITH/CTE block
        if token.ttype is T.Keyword.CTE and token.normalized == "WITH":
            while True:
                idx, token = statement.token_next(idx, skip_ws=True, skip_cm=True)
                if token is None:
                    return None
                if token.ttype in T.Keyword:
                    break
            break

        break

    keyword = token.normalized if token.ttype in T.Keyword else token.value.upper()

    if keyword == "INSERT":
        return OperationType.INSERT
    if keyword == "UPDATE":
        return OperationType.UPDATE
    if keyword == "DELETE":
        return OperationType.DELETE
    if keyword in {"CREATE", "ALTER", "DROP", "TRUNCATE"}:
        return OperationType.DDL
    return None


def extract_schema_from_query(query: str) -> set[str]:
    """Extract all schema names from a SQL query.

    Uses ``sqlparse`` to walk the parsed tokens and collect schema-qualified
    table references. Falls back to a regex for simple ``schema.table``
    patterns. Quoted identifiers are supported.

    Args:
        query: SQL query to analyze.

    Returns:
        Set of unique schema names referenced in the query.
    """

    schemas: set[str] = set()

    def _extract(token: sqlparse.sql.Token) -> None:
        if isinstance(token, IdentifierList):
            for identifier in token.get_identifiers():
                _extract(identifier)
        elif isinstance(token, Identifier):
            schema = token.get_parent_name()
            if schema:
                schemas.add(schema.strip('"'))
        elif getattr(token, "is_group", False):
            for t in token.tokens:
                _extract(t)

    for statement in sqlparse.parse(query):
        for token in statement.tokens:
            _extract(token)

    # Fallback to regex for any remaining simple patterns
    if not schemas:
        pattern = r'(?:"([^"]+)"|([a-zA-Z_][a-zA-Z0-9_]*))\s*\.\s*(?:"[^"]+"|[a-zA-Z_][a-zA-Z0-9_]*)'
        for match in re.findall(pattern, query):
            schema = match[0] or match[1]
            if schema:
                schemas.add(schema)

    return schemas


@asynccontextmanager
async def server_lifespan(server: FastMCP) -> AsyncIterator[dict[str, Any]]:
    """Server lifespan context manager that handles initialization and cleanup.

    Args:
        server: FastMCP server instance

    Yields:
        Dictionary containing the Vertica connection manager
    """
    manager = None
    try:
        # Initialize Vertica connection manager
        manager = VerticaConnectionManager()
        config = VerticaConfig.from_env()
        manager.initialize_default(config)
        logger.info("Vertica connection manager initialized")
        yield {"vertica_manager": manager}
    except Exception as e:
        logger.error(f"Failed to initialize server: {str(e)}")
        raise
    finally:
        # Cleanup resources
        if manager:
            try:
                manager.close_all()
                logger.info("Vertica connection manager closed")
            except Exception as e:
                logger.error(f"Error during cleanup: {str(e)}")


# Create FastMCP instance with SSE support
mcp = FastMCP(
    "Vertica Service",
    dependencies=["vertica-python", "pydantic", "starlette", "uvicorn"],
    lifespan=server_lifespan,
)


async def run_sse(port: int = 8000) -> None:
    """Run the MCP server with SSE transport.

    Args:
        port: Port to listen on for SSE transport
    """
    starlette_app = Starlette(routes=[Mount("/", app=mcp.sse_app())])
    config = uvicorn.Config(starlette_app, host="0.0.0.0", port=port)  # noqa: S104
    app = uvicorn.Server(config)
    await app.serve()


@mcp.tool()
async def execute_query(ctx: Context, query: str) -> str:
    """Execute a SQL query and return the results.

    Args:
        ctx: FastMCP context for progress reporting and logging
        query: SQL query to execute
        database: Optional database name to execute the query against

    Returns:
        Query results as a string
    """
    await ctx.info(f"Executing query: {query}")

    # Get connection manager from context
    manager = ctx.request_context.lifespan_context.get("vertica_manager")
    if not manager:
        await ctx.error("No database connection manager available")
        return "Error: No database connection manager available"

    statements = [s.strip() for s in sqlparse.split(query) if s.strip()]
    if not statements:
        return "Error: No SQL statements provided"

    # Check permissions for each statement before executing anything
    for stmt in statements:
        schemas = extract_schema_from_query(stmt)
        operation = extract_operation_type(stmt)
        if operation:
            for schema in schemas or {"default"}:
                if not manager.is_operation_allowed(schema=schema.lower(), operation=operation):
                    error_msg = (
                        f"Operation {operation.name} not allowed for schema {schema}"
                    )
                    await ctx.error(error_msg)
                    return error_msg

    conn = None
    cursor = None
    try:
        conn = manager.get_connection()  # Always use default DB connection
        cursor = conn.cursor()
        rows: list[Any] = []
        cols: list[str] = []

        for stmt in statements:
            cursor.execute(stmt)
            if cursor.description:
                rows = cursor.fetchall()
                cols = [d[0] for d in cursor.description]
            else:
                rows, cols = [], []
                conn.commit()
        await ctx.info(f"Query executed successfully, returned {len(rows)} rows")
        return json.dumps({"columns": cols, "rows": [list(r) for r in rows]})
    except Exception as e:
        error_msg = f"Error executing query: {str(e)}"
        await ctx.error(error_msg)
        if conn:
            conn.rollback()
        return error_msg
    finally:
        if cursor:
            cursor.close()
        if conn:
            manager.release_connection(conn)


@mcp.tool()
async def stream_query(
    ctx: Context, query: str, batch_size: int = 1000
) -> str:
    """Execute a SQL query and stream results in batches.

    Args:
        ctx: FastMCP context for progress reporting and logging
        query: SQL query to execute
        batch_size: Number of rows to fetch at once

    Returns:
        Completion message or metadata about the stream
    """
    await ctx.info(f"Executing query with batching: {query}")

    # Get connection manager from context
    manager = ctx.request_context.lifespan_context.get("vertica_manager")
    if not manager:
        await ctx.error("No database connection manager available")
        return "Error: No database connection manager available"

    statements = [s.strip() for s in sqlparse.split(query) if s.strip()]
    if not statements:
        return "Error: No SQL statements provided"

    # Check permissions for each statement before executing anything
    for stmt in statements:
        schemas = extract_schema_from_query(stmt)
        operation = extract_operation_type(stmt)
        if operation:
            for schema in schemas or {"default"}:
                if not manager.is_operation_allowed(schema=schema.lower(), operation=operation):
                    error_msg = (
                        f"Operation {operation.name} not allowed for schema {schema}"
                    )
                    await ctx.error(error_msg)
                    return error_msg

    conn = None
    cursor = None
    try:
        conn = manager.get_connection()  # Always use default DB connection
        cursor = conn.cursor()

        # Execute all but the final statement without streaming results
        for stmt in statements[:-1]:
            cursor.execute(stmt)
            if cursor.description:
                cursor.fetchall()  # Discard any interim results
            else:
                conn.commit()

        final_stmt = statements[-1]
        cursor.execute(final_stmt)
        if not cursor.description:
            conn.commit()
            await ctx.info("Query executed successfully with no results")
            return json.dumps({"rows_streamed": 0})

        total_rows = 0

        cols = [d[0] for d in cursor.description]
        await ctx.send(json.dumps({"columns": cols}))

        while True:
            batch = cursor.fetchmany(batch_size)
            if not batch:
                break
            total_rows += len(batch)
            await ctx.debug(f"Fetched {total_rows} rows")
            await ctx.send(json.dumps([list(r) for r in batch]))

        await ctx.info(f"Query completed, total rows: {total_rows}")
        return json.dumps({"rows_streamed": total_rows})
    except Exception as e:
        error_msg = f"Error executing query: {str(e)}"
        await ctx.error(error_msg)
        if conn:
            conn.rollback()
        return error_msg
    finally:
        if cursor:
            cursor.close()
        if conn:
            manager.release_connection(conn)


@mcp.tool()
async def copy_data(
    ctx: Context, schema: str, table: str, data: List[List[Any]],
) -> str:
    """Copy data into a Vertica table using COPY command.

    Args:
        ctx: FastMCP context for progress reporting and logging
        schema: vertica schema to execute the copy against
        table: Target table name
        data: List of rows to insert

    Returns:
        Status message indicating success or failure
    """
    await ctx.info(f"Copying {len(data)} rows to table: {table}")

    # Get connection manager from context
    manager = ctx.request_context.lifespan_context.get("vertica_manager")
    if not manager:
        await ctx.error("No database connection manager available")
        return "Error: No database connection manager available"

    # Check operation permissions
    if not manager.is_operation_allowed(schema=schema.lower(), operation=OperationType.INSERT):
        error_msg = f"INSERT operation not allowed for schema {schema}"
        await ctx.error(error_msg)
        return error_msg

    conn = None
    cursor = None
    # Validate identifiers before constructing the COPY query
    ident_pattern = r"^[A-Za-z_][A-Za-z0-9_]*$"
    if not re.match(ident_pattern, schema):
        raise ValueError(f"Invalid schema name: {schema}")
    if not re.match(ident_pattern, table):
        raise ValueError(f"Invalid table name: {table}")

    try:
        conn = manager.get_connection()
        cursor = conn.cursor()

        # Convert data to CSV string
        output = io.StringIO()
        writer = csv.writer(output, lineterminator="\n", quoting=csv.QUOTE_MINIMAL)
        writer.writerows([["\\N" if v is None else v for v in row] for row in data])
        output.seek(0)

        # Create COPY command including schema and stream data from buffer
        copy_query = f"COPY {schema}.{table} FROM STDIN DELIMITER ',' ENCLOSED BY '\"' NULL '\\N'"
        output.seek(0)
        cursor.copy(copy_query, output)
        conn.commit()

        success_msg = f"Successfully copied {len(data)} rows to {table}"
        await ctx.info(success_msg)
        return success_msg
    except Exception as e:
        error_msg = f"Error copying data: {str(e)}"
        await ctx.error(error_msg)
        if conn:
            conn.rollback()
        return error_msg
    finally:
        if cursor:
            cursor.close()
        if conn:
            manager.release_connection(conn)


@mcp.tool()
async def get_table_structure(
    ctx: Context,
    table_name: str,
    schema: str = "public"
) -> str:
    """Get the structure of a table including columns, data types, and constraints.

    Args:
        ctx: FastMCP context for progress reporting and logging
        table_name: Name of the table to inspect
        schema: Schema name (default: public)

    Returns:
        Table structure information as a string
    """
    await ctx.info(f"Getting structure for table: {schema}.{table_name}")

    manager = ctx.request_context.lifespan_context.get("vertica_manager")
    if not manager:
        await ctx.error("No database connection manager available")
        return "Error: No database connection manager available"

    query = """
    SELECT
        column_name,
        data_type,
        character_maximum_length,
        numeric_precision,
        numeric_scale,
        is_nullable,
        column_default
    FROM v_catalog.columns
    WHERE table_schema = %s
    AND table_name = %s
    ORDER BY ordinal_position;
    """

    conn = None
    cursor = None
    try:
        conn = manager.get_connection()
        cursor = conn.cursor()
        cursor.execute(query, (schema, table_name))
        columns = cursor.fetchall()

        if not columns:
            return f"No table found: {schema}.{table_name}"

        # Get constraints
        cursor.execute("""
            SELECT
                constraint_name,
                constraint_type,
                column_name
            FROM v_catalog.constraint_columns
            WHERE table_schema = %s
            AND table_name = %s;
        """, (schema, table_name))
        constraints = cursor.fetchall()

        # Format the output
        result = f"Table Structure for {schema}.{table_name}:\n\n"
        result += "Columns:\n"
        for col in columns:
            result += f"- {col[0]}: {col[1]}"
            if col[2]:  # character_maximum_length
                result += f"({col[2]})"
            elif col[3]:  # numeric_precision
                result += f"({col[3]},{col[4]})"
            result += f" {'NULL' if col[5] == 'YES' else 'NOT NULL'}"
            if col[6]:  # column_default
                result += f" DEFAULT {col[6]}"
            result += "\n"

        if constraints:
            result += "\nConstraints:\n"
            for const in constraints:
                result += f"- {const[0]} ({const[1]}): {const[2]}\n"

        return result

    except Exception as e:
        error_msg = f"Error getting table structure: {str(e)}"
        await ctx.error(error_msg)
        return error_msg
    finally:
        if cursor:
            cursor.close()
        if conn:
            manager.release_connection(conn)


@mcp.tool()
async def list_indexes(
    ctx: Context,
    table_name: str,
    schema: str = "public"
) -> str:
    """List all indexes for a specific table.

    Args:
        ctx: FastMCP context for progress reporting and logging
        table_name: Name of the table to inspect
        schema: Schema name (default: public)

    Returns:
        Index information as a string
    """
    await ctx.info(f"Listing indexes for table: {schema}.{table_name}")

    manager = ctx.request_context.lifespan_context.get("vertica_manager")
    if not manager:
        await ctx.error("No database connection manager available")
        return "Error: No database connection manager available"

    query = """
    SELECT
        projection_name,
        is_super_projection,
        anchor_table_name
    FROM v_catalog.projections
    WHERE projection_schema = %s
    AND anchor_table_name = %s
    ORDER BY projection_name;
    """

    conn = None
    cursor = None
    try:
        conn = manager.get_connection()
        cursor = conn.cursor()
        cursor.execute(query, (schema, table_name))
        indexes = cursor.fetchall()

        if not indexes:
            return f"No projections found for table: {schema}.{table_name}"

        # Format the output for projections
        result = f"Projections for {schema}.{table_name}:\n\n"
        for proj in indexes:
            # proj[0]: projection_name, proj[1]: is_super_projection, proj[2]: anchor_table_name
            result += f"- {proj[0]} (Super Projection: {proj[1]}) [Table: {proj[2]}]\n"
        return result

    except Exception as e:
        error_msg = f"Error listing indexes: {str(e)}"
        await ctx.error(error_msg)
        return error_msg
    finally:
        if cursor:
            cursor.close()
        if conn:
            manager.release_connection(conn)


@mcp.tool()
async def list_views(
    ctx: Context,
    schema: str = "public"
) -> str:
    """List all views in a schema.

    Args:
        ctx: FastMCP context for progress reporting and logging
        schema: Schema name (default: public)

    Returns:
        View information as a string
    """
    await ctx.info(f"Listing views in schema: {schema}")

    manager = ctx.request_context.lifespan_context.get("vertica_manager")
    if not manager:
        await ctx.error("No database connection manager available")
        return "Error: No database connection manager available"

    query = """
    SELECT
        table_name,
        view_definition
    FROM v_catalog.views
    WHERE table_schema = %s
    ORDER BY table_name;
    """

    conn = None
    cursor = None
    try:
        conn = manager.get_connection()
        cursor = conn.cursor()
        cursor.execute(query, (schema,))
        views = cursor.fetchall()

        if not views:
            return f"No views found in schema: {schema}"

        result = f"Views in schema {schema}:\n\n"
        for view in views:
            result += f"View: {view[0]}\n"
            result += f"Definition:\n{view[1]}\n\n"

        return result

    except Exception as e:
        error_msg = f"Error listing views: {str(e)}"
        await ctx.error(error_msg)
        return error_msg
    finally:
        if cursor:
            cursor.close()
        if conn:
            manager.release_connection(conn)
