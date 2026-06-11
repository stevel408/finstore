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
    import httpx

    from finstore import Tenant
    from finstore.backends.simplefin import SimpleFINBackend, SimpleFINCredentials
    from finstore.storage.filesystem import FilesystemStorage

    t0 = time.monotonic()
    try:
        creds = SimpleFINCredentials(
            access_url=settings.simplefin_access_url.get_secret_value()  # type: ignore[union-attr]
        )
        storage = FilesystemStorage(root=data_dir)
        tenant = Tenant(id="local")
        async with httpx.AsyncClient(timeout=settings.simplefin_timeout_secs) as http:
            backend = SimpleFINBackend(
                credentials=creds,
                httpx_client=http,
                chunk_window_days=settings.chunk_window_days,
                max_retries=settings.simplefin_max_retries,
            )
            dtstart = int(time.time()) - 90 * 86400
            report = await backend.fetch_and_persist(
                storage,
                tenant_id=tenant.id,
                dtstart_epoch=dtstart,
            )
        job.report = {
            "chunks": report.chunks,
            "accounts_seen": report.accounts_seen,
            "txns_new": report.txns_new,
            "txns_duplicate": report.txns_duplicate,
            "duration_secs": round(time.monotonic() - t0, 1),
            "errors": [{"code": e[0], "msg": e[1]} for e in report.errlist],
        }
        job.state = "done"
        get_registry().record_success()
    except Exception as exc:
        job.error = str(exc)
        job.state = "error"
