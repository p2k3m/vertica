"""Module entrypoint for `python -m mcp_vertica`."""

from __future__ import annotations

from . import cli


def main() -> None:
    """Invoke the Click CLI when executed as a module."""

    cli()


if __name__ == "__main__":  # pragma: no cover - CLI invocation guard
    main()
