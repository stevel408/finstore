"""Three protocols define the contract between core, backends, and storage.

The shapes here match the bundled `FilesystemStorage` and `SimpleFINBackend`
exactly — `isinstance(fs, Storage)` and `isinstance(sf, Backend)` both pass
at runtime, and `finstore.fetch()` delegates through these signatures.

Design points:

- `Credentials` stays an empty marker. Each backend defines its own
  credential dataclass and accepts it in its constructor (the runtime fetch
  call doesn't take credentials — see plan §11 open question on
  marker-vs-generic).
- `Backend.fetch_and_persist` is coarse on purpose: backends iterate their
  own windows and merge into storage directly. A future per-account API
  (`fetch_accounts` / `fetch_transactions`) is a non-breaking addition
  once a second backend lands.
- `Storage` exposes the surface the gateway and dashboard actually use.
  Per-account `write_account` / `read_transactions` are reserved for the
  same future expansion.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from finstore.model import AccountSummary, StorageChunk
    from finstore.storage.types import CachedAccount, CacheMeta, MergeStats


@runtime_checkable
class Credentials(Protocol):
    """Opaque marker for backend-specific credential payloads.

    Empty by design — credential shapes vary (URL, OAuth token, API key +
    secret, multi-step session). Each backend defines its own concrete model.
    """


@runtime_checkable
class Backend(Protocol):
    """Source of financial data. Credentials live on the constructed
    instance; window iteration is the backend's responsibility."""

    async def fetch_and_persist(
        self,
        storage: Storage,
        *,
        tenant_id: str,
        dtstart_epoch: int,
        dtend_epoch: int | None = None,
    ) -> Any: ...


@runtime_checkable
class Storage(Protocol):
    """Where normalized data lives. The reference impl is
    `finstore.storage.filesystem.FilesystemStorage`."""

    def merge_chunk(self, tenant_id: str, chunk: StorageChunk) -> MergeStats: ...

    def read_meta(self, tenant_id: str = ...) -> CacheMeta: ...

    def resolve_display_id(self, tenant_id: str, display_id: str) -> str: ...

    def read_account(self, tenant_id: str, account_id: str) -> CachedAccount: ...

    def read_account_window(
        self,
        tenant_id: str,
        account_id: str,
        dtstart_epoch: int,
        dtend_epoch: int | None,
    ) -> CachedAccount: ...

    def list_accounts(self, tenant_id: str = ...) -> tuple[AccountSummary, ...]: ...


__all__ = ["Backend", "Credentials", "Storage"]
