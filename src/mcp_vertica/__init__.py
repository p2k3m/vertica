"""CLI entry point for the Vertica MCP server."""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import Optional

import click

try:  # pragma: no cover - optional dependency for tests
    from dotenv import load_dotenv
except ModuleNotFoundError:  # pragma: no cover - optional dependency for tests
    def load_dotenv(*args, **kwargs):
        logging.getLogger("mcp-vertica").warning(
            "python-dotenv not installed; skipping .env loading"
        )
        return False

from .__about__ import __version__

logger = logging.getLogger("mcp-vertica")


def _configure_logging(verbose: int) -> None:
    level = logging.WARNING
    if verbose == 1:
        level = logging.INFO
    elif verbose >= 2:
        level = logging.DEBUG
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)s %(name)s %(message)s")


def _load_env_file(env_file: Optional[str]) -> None:
    if env_file:
        path = Path(env_file)
        if path.exists():
            load_dotenv(path)
            return
        raise click.BadParameter(f"Environment file not found: {env_file}")
    default = Path.cwd() / ".env"
    if default.exists():
        load_dotenv(default)


@click.group(invoke_without_command=True)
@click.option("--transport", type=click.Choice(["stdio", "http", "sse"]), default="stdio")
@click.option("--host", default="0.0.0.0", show_default=True)
@click.option("--port", default=8000, show_default=True, type=int)
@click.option("--env-file", type=str, help="Path to a .env file with Vertica credentials")
@click.option("-v", "--verbose", count=True, help="Increase logging verbosity")
@click.option("--read-only/--no-read-only", default=None, help="Force read-only mode regardless of schema allowlists")
def cli(transport: str, host: str, port: int, env_file: Optional[str], verbose: int, read_only: Optional[bool]) -> None:
    """Launch the Vertica MCP server using the selected transport."""

    _configure_logging(verbose)
    _load_env_file(env_file)
    if read_only is not None:
        os.environ["MCP_READ_ONLY"] = "true" if read_only else "false"

    from .mcp import mcp, run_http, run_sse

    if transport == "stdio":
        mcp.run()
    elif transport == "http":
        asyncio.run(run_http(port=port, host=host))
    else:
        asyncio.run(run_sse(port=port))


@cli.command("version")
def version_cmd() -> None:
    """Print the package version."""

    click.echo(__version__)


__all__ = ["cli", "__version__"]
