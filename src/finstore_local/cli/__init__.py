"""finstore_local CLI entrypoint. Registered as the `finstore` console script.

This module lazy-imports its dependencies so that `pip install finstore`
without the `[local]` extra produces a one-line error here rather than a
deep import traceback (plan §4.5 console-script behavior).
"""
from __future__ import annotations

import sys


def main() -> None:
    try:
        import typer  # noqa: F401
    except ImportError:
        print(
            "ERROR: `finstore` CLI requires the `[local]` extra. "
            "Install with: pipx install 'finstore[local]'",
            file=sys.stderr,
        )
        raise SystemExit(2)

    from finstore_local.cli._app import app

    app()


if __name__ == "__main__":  # pragma: no cover
    main()
