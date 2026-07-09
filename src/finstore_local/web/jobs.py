"""Background fetch job for the finstore dashboard."""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from finstore_local.config import Settings


@dataclass
class FetchJob:
    state: Literal["idle", "running", "done", "error"] = "idle"
    report: dict[str, Any] | None = None
    error: str | None = None
    task: asyncio.Task[None] | None = field(default=None, repr=False)


class JobRegistry:
    def __init__(self) -> None:
        self._job = FetchJob()
        self._last_success_at: int | None = None

    def reset(self) -> None:
        self._job = FetchJob()
        self._last_success_at = None

    def start(self, data_dir: Path, settings: Settings) -> bool:
        if self._job.state == "running":
            return False
        self._job = FetchJob(state="running")
        loop = asyncio.get_event_loop()
        self._job.task = loop.create_task(_run_fetch(self._job, data_dir, settings))
        return True

    def record_success(self) -> None:
        self._last_success_at = int(time.time())

    @property
    def last_success_at(self) -> int | None:
        return self._last_success_at

    def status(self) -> dict[str, Any]:
        j = self._job
        return {
            "state": j.state,
            "report": j.report,
            "error": j.error,
            "last_success_at": self._last_success_at,
        }


_registry = JobRegistry()


def get_registry() -> JobRegistry:
    return _registry


async def _run_fetch(job: FetchJob, data_dir: Path, settings: Settings) -> None:
    import json

    import httpx

    from finstore import Tenant
    from finstore.backends.simplefin import SimpleFINBackend, SimpleFINCredentials
    from finstore.backends.snaptrade import SnapTradeBackend, SnapTradeCredentials
    from finstore.storage.filesystem import FilesystemStorage

    t0 = time.monotonic()
    storage = FilesystemStorage(root=data_dir)
    tenant = Tenant(id="local")
    dtstart = int(time.time()) - 90 * 86400
    report: dict[str, Any] = {}

    # Each backend is isolated: a failure in one never blocks the other.

    # SimpleFIN
    if settings.simplefin_access_url is not None:
        try:
            async with httpx.AsyncClient(timeout=settings.simplefin_timeout_secs) as http:
                sf_backend = SimpleFINBackend(
                    credentials=SimpleFINCredentials(
                        access_url=settings.simplefin_access_url.get_secret_value()
                    ),
                    httpx_client=http,
                    chunk_window_days=settings.chunk_window_days,
                    max_retries=settings.simplefin_max_retries,
                )
                sf_report = await sf_backend.fetch_and_persist(
                    storage, tenant_id=tenant.id, dtstart_epoch=dtstart,
                )
            report["simplefin"] = {
                "chunks": sf_report.chunks,
                "accounts_seen": sf_report.accounts_seen,
                "txns_new": sf_report.txns_new,
                "txns_duplicate": sf_report.txns_duplicate,
                "errors": [{"code": e[0], "msg": e[1]} for e in sf_report.errlist],
            }
        except Exception as exc:
            report["simplefin_error"] = str(exc)

    # SnapTrade
    if settings.snaptrade_client_id and settings.snaptrade_consumer_key:
        raw = storage.read_backend_credential("local", "snaptrade")
        if raw is not None:
            try:
                cred_data = json.loads(raw.decode())
                is_personal = cred_data.get("type") == "personal"
                st_creds = SnapTradeCredentials(
                    client_id=settings.snaptrade_client_id,
                    consumer_key=settings.snaptrade_consumer_key.get_secret_value(),
                    user_id=None if is_personal else cred_data["user_id"],
                    user_secret=None if is_personal else cred_data["user_secret"],
                )
                async with httpx.AsyncClient(timeout=30.0) as http:
                    st_backend = SnapTradeBackend(
                        credentials=st_creds,
                        httpx_client=http,
                        activity_window_days=settings.chunk_window_days,
                    )
                    st_report = await st_backend.fetch_and_persist(
                        storage, tenant_id=tenant.id, dtstart_epoch=dtstart,
                    )
                report["snaptrade"] = {
                    "accounts_seen": st_report.accounts_seen,
                    "inv_txns_new": st_report.inv_txns_new,
                    "positions_written": st_report.positions_written,
                    "securities_upserted": st_report.securities_upserted,
                }
            except Exception as exc:
                report["snaptrade_error"] = str(exc)

    job.report = {
        **report,
        "duration_secs": round(time.monotonic() - t0, 1),
    }
    job.state = "done"
    get_registry().record_success()
