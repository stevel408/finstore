"""Top-level fetch orchestration. See plan §4.1.

For 0.1 the orchestration is intentionally thin: it delegates to the backend,
which owns its window iteration and merges into storage directly. Credentials
live on the constructed backend; the orchestrator doesn't see them.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from finstore.model import Tenant, Window
    from finstore.protocols import Backend, Storage


async def fetch(
    tenant: Tenant,
    backend: Backend,
    storage: Storage,
    *,
    window: Window,
) -> Any:
    """Fetch `window` worth of data via `backend` into `storage` for `tenant`.

    Returns whatever the backend's `fetch_and_persist` returns (today: a
    `FetchReport`).

    Cancellation: propagates `asyncio.CancelledError` from the caller.
    Per-account writes inside `Storage.merge_chunk` are atomic, so any
    chunks that completed before cancellation stay on disk; the in-flight
    chunk is dropped. No rollback is attempted.
    """
    dtstart, dtend = window
    return await backend.fetch_and_persist(
        storage,
        tenant_id=tenant.id,
        dtstart_epoch=dtstart,
        dtend_epoch=dtend,
    )


__all__ = ["fetch"]
