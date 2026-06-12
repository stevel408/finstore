"""Typer subcommands for the finstore CLI."""
from __future__ import annotations

import typer

app = typer.Typer(name="finstore", add_completion=False)
cache_app = typer.Typer()
app.add_typer(cache_app, name="cache")


@app.command()
def setup(
    token: str = typer.Argument(None, help="Setup token from SimpleFIN (base64)"),
    demo: bool = typer.Option(False, "--demo", help="Use SimpleFIN demo credentials"),
    env_file: str = typer.Option(None, "--env-file", help="Path to .env file"),
) -> None:
    """Exchange a SimpleFIN setup token for an access URL and save it locally."""
    from finstore_local.cli.setup import run
    run(token=token, demo=demo, env_file=env_file)


@app.command()
def fetch(
    env_file: str = typer.Option(None, "--env-file", help="Path to .env file"),
    start: str = typer.Option(None, "--start", help="Start date YYYY-MM-DD (backfill)"),
) -> None:
    """Pull data from the configured backend into local storage."""
    from finstore_local.cli.fetch import run
    run(env_file=env_file, start=start)


@app.command()
def serve(
    env_file: str = typer.Option(None, "--env-file"),
    host: str = typer.Option(None, "--host"),
    port: int = typer.Option(None, "--port"),
    debug: bool = typer.Option(False, "--debug"),
) -> None:
    """Run the finstore dashboard (does not serve OFX — use gnc-sfin-gateway for that)."""
    from finstore_local.cli.serve import run
    run(env_file=env_file, host=host, port=port, debug=debug)


@app.command()
def accounts(
    env_file: str = typer.Option(None, "--env-file"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """List stored accounts (reads storage; never hits the backend)."""
    from finstore_local.cli.accounts import run
    run(env_file=env_file, json_output=json_output)


@app.command()
def validate(
    env_file: str = typer.Option(None, "--env-file"),
) -> None:
    """Validate all stored account files against defined rules."""
    from finstore_local.cli.validate import run
    run(env_file=env_file)


@cache_app.command("reset")
def cache_reset(
    env_file: str = typer.Option(None, "--env-file"),
    account: str = typer.Option(None, "--account", help="Reset only this account"),
    yes: bool = typer.Option(False, "--yes", help="Skip confirmation"),
) -> None:
    """Wipe local storage (or a single account entry)."""
    from finstore_local.cli.cache_reset import run
    run(env_file=env_file, account=account, yes=yes)
