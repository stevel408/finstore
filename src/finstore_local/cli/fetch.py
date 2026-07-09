from __future__ import annotations

import asyncio
import json
import sys
import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from finstore_local.config import Settings
    from finstore.storage.filesystem import FilesystemStorage


def run(
    env_file: str | None = None,
    start: str | None = None,
    backend: str | None = None,
    all_backends: bool = False,
    reset: bool = False,
) -> None:
    from finstore.storage.filesystem import FilesystemStorage as _FS
    from finstore_local import logging as flog
    from finstore_local.config import load_settings, resolve_data_dir

    settings = load_settings(env_file)
    flog.configure(settings)

    data_dir = resolve_data_dir(settings, create=True)
    storage = _FS(root=data_dir)

    if reset:
        scope = _reset_scope(backend, all_backends)
        storage.clear_cache(scope=scope)
        label = f"scope={scope}"
        print(f"Cache cleared ({label}).", file=sys.stderr)

    now_epoch = int(time.time())
    dtstart_epoch = _resolve_start(start, now_epoch, storage)

    if backend is not None and backend not in ("simplefin", "snaptrade"):
        print(
            f"ERROR: unknown backend {backend!r}. Use 'simplefin', 'snaptrade', or --all.",
            file=sys.stderr,
        )
        raise SystemExit(2)

    run_simplefin = all_backends or backend in (None, "simplefin")
    run_snaptrade = all_backends or backend == "snaptrade"

    # None = not configured, True = success, False = error
    results: list[bool | None] = []
    if run_simplefin:
        results.append(_fetch_simplefin(settings, storage, dtstart_epoch, now_epoch))
    if run_snaptrade:
        results.append(_fetch_snaptrade(settings, storage, dtstart_epoch, now_epoch))

    configured = [r for r in results if r is not None]
    if not configured:
        print(
            "ERROR: no credentials configured.\n"
            "  SimpleFIN: run 'finstore setup <token>'\n"
            "  SnapTrade: run 'finstore snaptrade setup'",
            file=sys.stderr,
        )
        raise SystemExit(2)

    if any(r is False for r in configured):
        raise SystemExit(1)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _reset_scope(backend: str | None, all_backends: bool) -> str:
    if all_backends or backend is None:
        return "all"
    if backend == "simplefin":
        return "banking"
    if backend == "snaptrade":
        return "investment"
    return "all"


# ---------------------------------------------------------------------------
# Per-backend fetch helpers
# ---------------------------------------------------------------------------


def _fetch_simplefin(
    settings: Settings,
    storage: FilesystemStorage,
    dtstart_epoch: int,
    now_epoch: int,
) -> bool | None:
    """Returns True on success, False on error, None if not configured."""
    import httpx
    from finstore import Tenant
    from finstore.backends.simplefin import SimpleFINBackend, SimpleFINCredentials

    if settings.simplefin_access_url:
        access_url: str | None = settings.simplefin_access_url.get_secret_value()
    else:
        raw = storage.read_backend_credential("local", "simplefin")
        access_url = raw.decode() if raw is not None else None

    if access_url is None:
        return None  # not configured — skip silently

    tenant = Tenant(id="local")

    async def _run() -> Any:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(
                connect=5.0,
                read=settings.simplefin_timeout_secs,
                write=5.0,
                pool=5.0,
            )
        ) as http_client:
            b = SimpleFINBackend(
                credentials=SimpleFINCredentials(access_url=access_url),
                httpx_client=http_client,
                chunk_window_days=settings.chunk_window_days,
                max_retries=settings.simplefin_max_retries,
            )
            return await b.fetch_and_persist(
                storage,
                tenant_id=tenant.id,
                dtstart_epoch=dtstart_epoch,
                dtend_epoch=now_epoch,
            )

    try:
        report = asyncio.run(_run())
    except Exception as exc:
        print(f"ERROR [simplefin]: {exc}", file=sys.stderr)
        return False

    print(
        f"simplefin: {report.chunks} chunks, "
        f"{report.accounts_seen} accounts, "
        f"{report.txns_new} new txns, "
        f"{report.txns_duplicate} duplicates "
        f"({report.duration_secs:.1f}s)",
        file=sys.stderr,
    )
    if report.errlist:
        for code, msg in report.errlist:
            print(f"WARN  simplefin upstream: {code} — {msg}", file=sys.stderr)
        return False
    return True


def _fetch_snaptrade(
    settings: Settings,
    storage: FilesystemStorage,
    dtstart_epoch: int,
    now_epoch: int,
) -> bool | None:
    """Returns True on success, False on error, None if not configured."""
    import httpx
    from finstore import Tenant
    from finstore.backends.snaptrade import SnapTradeBackend, SnapTradeCredentials

    client_id = settings.snaptrade_client_id
    consumer_key_obj = settings.snaptrade_consumer_key

    if not client_id or not consumer_key_obj:
        return None  # not configured — skip silently

    consumer_key: str = consumer_key_obj.get_secret_value()

    raw = storage.read_backend_credential("local", "snaptrade")
    if raw is None:
        print(
            "ERROR [snaptrade]: not configured. "
            "Run 'finstore snaptrade setup' first.",
            file=sys.stderr,
        )
        return False

    try:
        cred_data = json.loads(raw.decode())
    except json.JSONDecodeError as exc:
        print(f"ERROR [snaptrade]: credential blob is corrupt: {exc}", file=sys.stderr)
        return False

    is_personal = cred_data.get("type") == "personal"
    if is_personal:
        user_id_val: str | None = None
        user_secret_val: str | None = None
    else:
        try:
            user_id_val = cred_data["user_id"]
            user_secret_val = cred_data["user_secret"]
        except KeyError as exc:
            print(f"ERROR [snaptrade]: credential blob is corrupt: {exc}", file=sys.stderr)
            return False

    creds = SnapTradeCredentials(
        client_id=client_id,
        consumer_key=consumer_key,
        user_id=user_id_val,
        user_secret=user_secret_val,
    )
    tenant = Tenant(id="local")

    async def _run() -> Any:
        async with httpx.AsyncClient(timeout=30.0) as http_client:
            b = SnapTradeBackend(
                credentials=creds,
                httpx_client=http_client,
                activity_window_days=settings.chunk_window_days,
            )
            return await b.fetch_and_persist(
                storage,
                tenant_id=tenant.id,
                dtstart_epoch=dtstart_epoch,
                dtend_epoch=now_epoch,
            )

    try:
        report = asyncio.run(_run())
    except Exception as exc:
        print(f"ERROR [snaptrade]: {exc}", file=sys.stderr)
        return False

    print(
        f"snaptrade: {report.accounts_seen} accounts, "
        f"{report.inv_txns_new} new txns, "
        f"{report.inv_txns_duplicate} duplicates, "
        f"{report.positions_written} positions, "
        f"{report.securities_upserted} securities "
        f"({report.duration_secs:.1f}s)",
        file=sys.stderr,
    )
    return True


# ---------------------------------------------------------------------------
# Start-date resolution
# ---------------------------------------------------------------------------


def _resolve_start(
    start: str | None,
    now_epoch: int,
    storage: FilesystemStorage,
) -> int:
    if start is not None:
        try:
            dt = datetime.strptime(start, "%Y-%m-%d").replace(tzinfo=UTC)
            return int(dt.timestamp())
        except ValueError:
            print(
                f"ERROR: --start must be YYYY-MM-DD, got {start!r}", file=sys.stderr
            )
            raise SystemExit(2)

    from finstore.storage.exceptions import CacheEmptyError, CacheSchemaMismatchError

    try:
        meta = storage.read_meta("local")
        candidates: list[int] = []
        for acct_v in meta.accounts.values():
            if acct_v.latest_posted is not None:
                candidates.append(acct_v.latest_posted)
        for inv_v in meta.investment_accounts.values():
            if inv_v.latest_trade is not None:
                candidates.append(inv_v.latest_trade)
        if candidates:
            return max(candidates) - 7 * 86400  # 7-day overlap
    except (CacheEmptyError, CacheSchemaMismatchError):
        pass

    return now_epoch - 90 * 86400
