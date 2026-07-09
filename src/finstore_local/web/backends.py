"""Backend availability/activation status — shared by the dashboard and the API."""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from finstore_local.config import Settings

_DOCS_BASE = "https://github.com/stevel408/finstore/blob/main/docs/running-locally.md"

_BACKENDS = (
    {"id": "simplefin", "label": "SimpleFIN", "docs_url": f"{_DOCS_BASE}#3-simplefin-setup"},
    {"id": "snaptrade", "label": "SnapTrade", "docs_url": f"{_DOCS_BASE}#4-snaptrade-setup"},
)


def backend_status(settings: Settings) -> list[dict[str, object]]:
    """Return each known backend's id/label/docs link and whether it's activated.

    "Activated" means credentials are configured — the only signal the
    dashboard needs. Setup itself happens through the CLI (`finstore setup`,
    `finstore snaptrade setup`), not the web UI.
    """
    configured = {
        "simplefin": settings.simplefin_access_url is not None,
        "snaptrade": bool(settings.snaptrade_client_id and settings.snaptrade_consumer_key),
    }
    return [{**b, "configured": configured[b["id"]]} for b in _BACKENDS]
