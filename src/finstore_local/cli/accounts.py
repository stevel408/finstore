from __future__ import annotations

import json
import sys


def run(env_file: str | None = None, json_output: bool = False) -> None:
    from finstore.storage.exceptions import CacheEmptyError
    from finstore.storage.filesystem import FilesystemStorage
    from finstore_local import logging as flog
    from finstore_local.config import get_settings, resolve_data_dir

    settings = get_settings()
    flog.configure(settings)

    try:
        data_dir = resolve_data_dir(settings, create=False)
    except FileNotFoundError:
        print("Storage is empty — run 'finstore fetch' to populate it.", file=sys.stderr)
        raise SystemExit(1)

    storage = FilesystemStorage(root=data_dir)
    try:
        stubs = storage.list_accounts("local")
    except CacheEmptyError:
        print("Storage is empty — run 'finstore fetch' to populate it.", file=sys.stderr)
        raise SystemExit(1)

    if not stubs:
        print("Storage is empty — run 'finstore fetch' to populate it.", file=sys.stderr)
        raise SystemExit(1)

    if json_output:
        out = [
            {
                "acctid": s.acctid,
                "name": s.name,
                "currency": s.currency,
                "connection": {
                    "conn_id": s.connection.conn_id,
                    "org_name": s.connection.org_name,
                    "org_id": s.connection.org_id,
                },
                "last_fetch_at": s.last_fetch_at,
                "txn_count": s.txn_count,
            }
            for s in stubs
        ]
        print(json.dumps(out, indent=2))
    else:
        print(f"{'ACCOUNT ID':<45} {'NAME':<30} {'CONN'}")
        print("-" * 85)
        for s in stubs:
            print(f"{s.acctid:<45} {s.name[:30]:<30} {s.connection.conn_id}")
