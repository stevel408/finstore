from __future__ import annotations

import json
import shutil
import sys


def run(
    env_file: str | None = None,
    account: str | None = None,
    yes: bool = False,
) -> None:
    from finstore.storage.paths import normalize_conn_id
    from finstore_local import logging as flog
    from finstore_local.config import get_settings, resolve_data_dir

    settings = get_settings()
    flog.configure(settings)

    try:
        data_dir = resolve_data_dir(settings, create=False)
    except FileNotFoundError:
        print("Storage directory does not exist — nothing to reset.", file=sys.stderr)
        raise SystemExit(0)

    if account:
        meta_path = data_dir / "meta.json"
        if not meta_path.exists():
            print("No cache found.", file=sys.stderr)
            raise SystemExit(1)
        meta = json.loads(meta_path.read_text())
        acct_info = meta.get("accounts", {}).get(account)
        if acct_info is None:
            print(f"No cached entry for {account!r}.", file=sys.stderr)
            raise SystemExit(1)
        conn_id = acct_info.get("conn_id", "_unknown")
        target = data_dir / "accounts" / normalize_conn_id(conn_id) / f"{account}.json"
        if not target.exists():
            print(f"No cached file for account {account!r}.", file=sys.stderr)
            raise SystemExit(1)
        if not yes:
            confirm = input(f"Delete cache entry for {account!r}? [y/N] ")
            if confirm.strip().lower() != "y":
                print("Aborted.", file=sys.stderr)
                raise SystemExit(0)
        target.unlink()
        meta.get("accounts", {}).pop(account, None)
        meta_path.write_text(json.dumps(meta))
        print(f"Removed cache entry for {account!r}.")
    else:
        if not yes:
            confirm = input(f"Delete entire cache at {data_dir}? [y/N] ")
            if confirm.strip().lower() != "y":
                print("Aborted.", file=sys.stderr)
                raise SystemExit(0)
        shutil.rmtree(data_dir)
        print(f"Cache deleted: {data_dir}")
