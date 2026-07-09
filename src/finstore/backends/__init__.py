"""Registry of backends bundled with finstore.

`BACKENDS` is a static, credential-agnostic list of every backend id finstore
ships. `backend_status()` combines it with the `Storage` credential API to
answer "which backends are activated" for a tenant — the one thing an
upper-level app needs without reaching for `finstore_local` or any
backend-specific extra.

Importing `finstore.backends` itself requires no extras; the concrete
backend classes (`finstore.backends.simplefin.SimpleFINBackend`, etc.) do.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from finstore.protocols import Storage


@dataclass(frozen=True)
class BackendInfo:
    id: str
    label: str


BACKENDS: tuple[BackendInfo, ...] = (
    BackendInfo(id="simplefin", label="SimpleFIN"),
    BackendInfo(id="snaptrade", label="SnapTrade"),
)


@dataclass(frozen=True)
class BackendStatus:
    id: str
    label: str
    activated: bool


def backend_status(storage: Storage, tenant_id: str) -> tuple[BackendStatus, ...]:
    """Activation status for every known backend, for `tenant_id`.

    `activated` reflects whether a credential has been persisted via
    `Storage.write_backend_credential` — the signal set by `activate()` /
    the setup CLI commands. It does not account for deployment-specific
    overrides (e.g. an env var supplying a credential directly); callers
    that support such overrides should layer them on top.
    """
    return tuple(
        BackendStatus(
            id=b.id,
            label=b.label,
            activated=storage.exists_backend_credential(tenant_id, b.id),
        )
        for b in BACKENDS
    )


__all__ = ["BACKENDS", "BackendInfo", "BackendStatus", "backend_status"]
