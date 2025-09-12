import warnings
import re

warnings.filterwarnings(
    "ignore",
    message='Field name "schema" in ".*" shadows an attribute in parent "ArgModelBase"',
    category=UserWarning,
    module="pydantic._internal._fields"
)

import asyncio
import logging
import os
import click
from dotenv import load_dotenv
from .mcp import *
from .connection import (
    VERTICA_HOST,
    VERTICA_PORT,
    VERTICA_DATABASE,
    VERTICA_USER,
    VERTICA_PASSWORD,
    VERTICA_CONNECTION_LIMIT,
    VERTICA_SSL,
    VERTICA_SSL_REJECT_UNAUTHORIZED,
)
from .rest import serve_rest as _serve_rest
from .nlp import NL2SQL, SimilarIncidents
from .connection import VerticaConnectionManager, VerticaConfig

__version__ = "0.1.4"

logger = logging.getLogger("mcp-vertica")

def setup_logger(verbose: int) -> logging.Logger:
    logger = logging.getLogger("mcp-vertica")
    logger.propagate = False
    level = logging.CRITICAL
    if not logger.hasHandlers():
        handler = logging.StreamHandler()
        if verbose == 0:
            handler.setLevel(logging.CRITICAL)
            logger.setLevel(logging.CRITICAL)
        elif verbose == 1:
            handler.setLevel(logging.INFO)
            logger.setLevel(logging.INFO)
            level = logging.INFO
        else:
            handler.setLevel(logging.DEBUG)
            logger.setLevel(logging.DEBUG)
            level = logging.DEBUG
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        handler.setFormatter(formatter)
        logger.addHandler(handler)

    logging.basicConfig(level=level, force=True)
    return logger

def validate_port(ctx, param, value):
    if value is not None and not (1024 <= value <= 65535):
        raise click.BadParameter(f"{param.name} must be between 1024 and 65535")
    return value

def validate_host(ctx, param, value):
    if value is not None:
        if not re.match(r"^[\w\.-]+$", value):
            raise click.BadParameter(f"{param.name} must be a valid hostname or IP address")
    return value

def main(
    verbose: int,
    env_file: str | None,
    transport: str,
    port: int,
    host: str | None,
    db_port: int | None,
    database: str | None,
    user: str | None,
    password: str | None,
    connection_limit: int | None,
    ssl: bool | None,
    ssl_reject_unauthorized: bool | None,
) -> None:
    """MCP Vertica Server - Vertica functionality for MCP"""

    # Configure logging based on verbosity
    setup_logger(verbose)

    # Load environment variables from file if specified, otherwise try default .env
    if env_file:
        logging.debug(f"Loading environment from file: {env_file}")
        load_dotenv(env_file)
    else:
        logging.debug("Attempting to load environment from default .env file")
        load_dotenv()

    # Set default environment variables
    os.environ.setdefault(VERTICA_CONNECTION_LIMIT, "10")
    os.environ.setdefault(VERTICA_SSL, "false")
    os.environ.setdefault(VERTICA_SSL_REJECT_UNAUTHORIZED, "true")

    # Set environment variables from command line arguments if provided
    if host is not None:
        os.environ[VERTICA_HOST] = host
    if db_port:
        os.environ[VERTICA_PORT] = str(db_port)
    if database is not None:
        os.environ[VERTICA_DATABASE] = database
    if user is not None:
        os.environ[VERTICA_USER] = user
    if password is not None:
        os.environ[VERTICA_PASSWORD] = password
    if connection_limit is not None:
        os.environ[VERTICA_CONNECTION_LIMIT] = str(connection_limit)
    if ssl is not None:
        os.environ[VERTICA_SSL] = str(ssl).lower()
    if ssl_reject_unauthorized is not None:
        os.environ[VERTICA_SSL_REJECT_UNAUTHORIZED] = str(ssl_reject_unauthorized).lower()

    # Run the server with specified transport
    if transport == "sse":
        asyncio.run(run_sse(port=port))
    else:
        mcp.run()

@click.group(invoke_without_command=True)
@click.option(
    "-v",
    "--verbose",
    count=True,
    help="Increase verbosity (can be used multiple times, e.g., -v, -vv, -vvv)",
)
@click.option(
    "--env-file", type=click.Path(exists=True, dir_okay=False), help="Path to .env file"
)
@click.option(
    "--transport",
    type=click.Choice(["stdio", "sse"]),
    default="stdio",
    help="Transport type (stdio or sse)",
)
@click.option(
    "--port",
    default=8000,
    callback=validate_port,
    help="Port to listen on for SSE transport",
)
@click.option(
    "--host",
    callback=validate_host,
    help="Vertica host",
)
@click.option(
    "--db-port",
    type=int,
    callback=validate_port,
    help="Vertica port",
)
@click.option(
    "--database",
    help="Vertica database name",
)
@click.option(
    "--user",
    help="Vertica username",
)
@click.option(
    "--password",
    help="Vertica password",
)
@click.option(
    "--connection-limit",
    type=int,
    default=None,
    show_default="10",
    help="Maximum number of connections in the pool",
)
@click.option(
    "--ssl/--no-ssl",
    default=None,
    help="Enable SSL for database connection",
)
@click.option(
    "--ssl-reject-unauthorized/--no-ssl-reject-unauthorized",
    default=None,
    help="Reject unauthorized SSL certificates",
)
@click.pass_context
def cli(ctx, **kwargs):
    if ctx.invoked_subcommand is None:
        main(**kwargs)


@click.group()
def nlp():
    "Natural language tools"
    pass


@nlp.command("ask")
@click.argument("question", nargs=-1)
@click.option("--execute/--dry-run", default=True, help="Execute the SQL or just print it")
@click.option("--model", default="llama3.1:8b")
@click.option("--ollama-host", default="http://127.0.0.1:11434")
def nlp_ask(question, execute, model, ollama_host):
    q = " ".join(question)
    mgr = VerticaConnectionManager()
    mgr.initialize_default(VerticaConfig.from_env())
    n2s = NL2SQL(ollama_host=ollama_host, model=model)
    sql = n2s.generate_sql(mgr, q)
    click.echo(f"SQL:\n{sql}")
    if not execute:
        return
    conn = cur = None
    try:
        conn = mgr.get_connection()
        cur = conn.cursor()
        cur.execute(sql)
        if cur.description:
            rows = cur.fetchall()
            cols = [d[0] for d in cur.description]
            click.echo(f"Columns: {cols}")
            for r in rows[:50]:
                click.echo(str(r))
        else:
            conn.commit()
            click.echo("Statement executed and committed.")
    finally:
        if cur: cur.close()
        if conn: mgr.release_connection(conn)


@nlp.command("similar")
@click.option("--incident-id", default=None)
@click.option("--text", default=None)
@click.option("--top-k", default=5, type=int)
def nlp_similar(incident_id, text, top_k):
    mgr = VerticaConnectionManager()
    mgr.initialize_default(VerticaConfig.from_env())
    sim = SimilarIncidents(top_k=top_k)
    res = sim.query(mgr, text=text, incident_id=incident_id)
    for r in res:
        click.echo(r)


@click.command("serve-rest")
@click.option("--host", default="0.0.0.0")
@click.option("--port", default=8001, type=int)
def serve_rest(host, port):
    _serve_rest(host=host, port=port)


@cli.command("seed-itsm")
def seed_itsm():
    from scripts.seed_itsm import main as seed_main
    seed_main()


cli.add_command(nlp)
cli.add_command(serve_rest)

if __name__ == "__main__":
    cli()

__all__ = ["main", "cli"]
