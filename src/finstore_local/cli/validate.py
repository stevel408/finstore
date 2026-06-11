from __future__ import annotations

import typer

from finstore.storage.validate import ACCOUNT_RULES, TRANSACTION_RULES, validate_cache


def run(env_file: str | None) -> None:
    from finstore_local.config import Settings, resolve_data_dir

    settings = Settings(_env_file=env_file)  # type: ignore[call-arg]
    data_dir = resolve_data_dir(settings)

    violations = validate_cache(data_dir)

    if not violations:
        account_rules = len(ACCOUNT_RULES)
        txn_rules = len(TRANSACTION_RULES) + 1
        typer.echo(
            f"OK  {account_rules} account rules, {txn_rules} transaction rules"
            " — no violations found."
        )
        return

    for v in violations:
        typer.echo(str(v))

    typer.echo(f"\n{len(violations)} violation(s) found.", err=True)
    raise typer.Exit(1)
