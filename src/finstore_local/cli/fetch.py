from __future__ import annotations

import asyncio
import sys
import time
from datetime import UTC, datetime

import httpx


def run(env_file: str | None = None, start: str | None = None) -> None:
    from finstore import Tenant
    from finstore.backends.simplefin import SimpleFINBackend, SimpleFINCredentials
    from finstore.storage.exceptions import CacheEmptyError
    from finstore.storage.filesystem import FilesystemStorage
    from finstore_local import logging as flog
    from finstore_local.config import load_settings, resolve_data_dir

    settings = load_settings(env_file)
    flog.configure(settings)

    if settings.simplefin_access_url is None:
        print(
            "ERROR: SIMPLEFIN_ACCESS_URL is required for 'fetch'.\n"
            "Set it in .env or pass it as an environment variable.",
            file=sys.stderr,
        )
        raise SystemExit(2)

    data_dir = resolve_data_dir(settings, create=True)
    storage = FilesystemStorage(root=data_dir)
    tenant = Tenant(id="local")

    now_epoch = int(time.time())
    if start is not None:
        try:
            dt = datetime.strptime(start, "%Y-%m-%d").replace(tzinfo=UTC)
            dtstart_epoch = int(dt.timestamp())
        except ValueError:
            print(f"ERROR: --start must be YYYY-MM-DD, got '{start}'", file=sys.stderr)
            raise SystemExit(2)
    else:
        try:
            meta = storage.read_meta(tenant.id)
            all_latest = [
                v.latest_posted
                for v in meta.accounts.values()
                if v.latest_posted is not None
            ]
            if all_latest:
                dtstart_epoch = max(all_latest) - 7 * 86400  # 7-day overlap
            else:
                dtstart_epoch = now_epoch - 90 * 86400
        except CacheEmptyError:
            dtstart_epoch = now_epoch - 90 * 86400

    creds = SimpleFINCredentials(
        access_url=settings.simplefin_access_url.get_secret_value()
    )

    async def _run() -> None:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(
                connect=5.0,
                read=settings.simplefin_timeout_secs,
                write=5.0,
                pool=5.0,
            )
        ) as http_client:
            backend = SimpleFINBackend(
                credentials=creds,
                httpx_client=http_client,
                chunk_window_days=settings.chunk_window_days,
                max_retries=settings.simplefin_max_retries,
            )
            report = await backend.fetch_and_persist(
                storage,
                tenant_id=tenant.id,
                dtstart_epoch=dtstart_epoch,
                dtend_epoch=now_epoch,
            )

        print(
            f"fetch complete: {report.chunks} chunks, "
            f"{report.accounts_seen} accounts, "
            f"{report.txns_new} new txns, "
            f"{report.txns_duplicate} duplicates "
            f"({report.duration_secs:.1f}s)",
            file=sys.stderr,
        )
        if report.errlist:
            for code, msg in report.errlist:
                print(f"WARN  upstream errlist: {code} — {msg}", file=sys.stderr)
            raise SystemExit(1)

    asyncio.run(_run())
