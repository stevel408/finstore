"""Typer subcommands for the finstore CLI."""
from __future__ import annotations

import typer

app = typer.Typer(name="finstore", add_completion=False)
cache_app = typer.Typer()
snaptrade_app = typer.Typer(help="SnapTrade brokerage connection management.")
app.add_typer(cache_app, name="cache")
app.add_typer(snaptrade_app, name="snaptrade")


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
    backend: str = typer.Option(
        None, "--backend", help="Which backend to fetch: simplefin | snaptrade"
    ),
    all_backends: bool = typer.Option(
        False, "--all", help="Fetch all configured backends in sequence"
    ),
    reset: bool = typer.Option(
        False, "--reset", help="Clear cached data before fetching (credentials are preserved)"
    ),
) -> None:
    """Pull data from the configured backend(s) into local storage."""
    from finstore_local.cli.fetch import run
    run(env_file=env_file, start=start, backend=backend, all_backends=all_backends, reset=reset)


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


@snaptrade_app.command("setup")
def snaptrade_setup(
    env_file: str = typer.Option(None, "--env-file"),
) -> None:
    """Register with SnapTrade and get a brokerage connection link."""
    from finstore_local.cli.snaptrade import run_setup
    run_setup(env_file=env_file)


@snaptrade_app.command("status")
def snaptrade_status(
    env_file: str = typer.Option(None, "--env-file"),
) -> None:
    """Show SnapTrade registration status and connected accounts."""
    from finstore_local.cli.snaptrade import run_status
    run_status(env_file=env_file)


@snaptrade_app.command("delete")
def snaptrade_delete(
    env_file: str = typer.Option(None, "--env-file"),
    yes: bool = typer.Option(False, "--yes", help="Skip confirmation prompt"),
) -> None:
    """Deregister the SnapTrade user and delete local credentials."""
    from finstore_local.cli.snaptrade import run_delete
    run_delete(env_file=env_file, yes=yes)


@cache_app.command("reset")
def cache_reset(
    env_file: str = typer.Option(None, "--env-file"),
    account: str = typer.Option(None, "--account", help="Reset only this account"),
    yes: bool = typer.Option(False, "--yes", help="Skip confirmation"),
) -> None:
    """Wipe local storage (or a single account entry)."""
    from finstore_local.cli.cache_reset import run
    run(env_file=env_file, account=account, yes=yes)
