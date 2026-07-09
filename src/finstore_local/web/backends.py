"""Backend availability/activation status — shared by the dashboard and the API.

Activation itself is answered by `finstore.backend_status()` (persisted
credential presence). This module layers the deployment-specific overrides
`finstore_local` supports on top — an env-supplied SimpleFIN access URL
bypasses the persisted credential; SnapTrade additionally requires partner
keys — and adds the UI-only bits (docs links) the core has no business
knowing about.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from finstore import backend_status as _core_backend_status

if TYPE_CHECKING:
    from finstore.protocols import Storage
    from finstore_local.config import Settings

_DOCS_BASE = "https://github.com/stevel408/finstore/blob/main/docs/running-locally.md"

_DOCS_URLS = {
    "simplefin": f"{_DOCS_BASE}#3-simplefin-setup",
    "snaptrade": f"{_DOCS_BASE}#4-snaptrade-setup",
}


def backend_status(
    storage: Storage, tenant_id: str, settings: Settings
) -> list[dict[str, object]]:
    """Return each known backend's id/label/docs link and whether it's activated."""
    has_snaptrade_keys = bool(settings.snaptrade_client_id and settings.snaptrade_consumer_key)
    overrides = {
        "simplefin": lambda activated: activated or settings.simplefin_access_url is not None,
        "snaptrade": lambda activated: activated and has_snaptrade_keys,
    }
    return [
        {
            "id": s.id,
            "label": s.label,
            "configured": overrides[s.id](s.activated),
            "docs_url": _DOCS_URLS[s.id],
        }
        for s in _core_backend_status(storage, tenant_id)
    ]
