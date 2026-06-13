"""SimpleFIN activation: obtain and persist a credential, return a ready backend.

The single public entry-point is `activate()`. All setup-token / access-URL
detection and exchange logic is private here; callers never see the distinction.
"""
from __future__ import annotations

import base64
import time
from typing import TYPE_CHECKING

from finstore.exceptions import BackendError

if TYPE_CHECKING:
    import httpx

    from finstore.backends.simplefin.backend import SimpleFINBackend
    from finstore.protocols import Storage

_BACKEND_ID = "simplefin"


async def activate(
    secret: str | None,
    *,
    storage: Storage,
    tenant_id: str,
    client: httpx.AsyncClient,
) -> SimpleFINBackend:
    """Activate a SimpleFIN backend, returning it ready to fetch.

    - If `secret` is non-None, finstore auto-detects whether it is a
      base64-encoded setup token (requiring a one-time exchange) or an
      already-usable access URL, resolves it to an access URL, persists it
      via `storage`, and returns a wired backend. Any previously persisted
      credential is replaced.
    - If `secret` is None, the previously persisted credential is loaded
      from `storage`. Raises `BackendError` if none exists.
    - On any failure (bad secret, exchange error, missing credential) raises
      `BackendError`.

    Caller owns `client`; `activate` neither opens nor closes it.
    """
    from finstore.backends.simplefin.backend import SimpleFINBackend, SimpleFINCredentials

    if secret is None:
        data = storage.read_backend_credential(tenant_id, _BACKEND_ID)
        if data is None:
            raise BackendError(
                "no SimpleFIN credential found; call activate(secret=...) first"
            )
        access_url = data.decode()
    else:
        access_url, validated_by_exchange = await _resolve_access_url(secret, client)
        if not validated_by_exchange:
            await _validate_access_url(access_url, client)
        storage.write_backend_credential(tenant_id, _BACKEND_ID, access_url.encode())

    return SimpleFINBackend(
        SimpleFINCredentials(access_url=access_url),
        httpx_client=client,
    )


async def _resolve_access_url(
    secret: str, client: httpx.AsyncClient
) -> tuple[str, bool]:
    """Return (access_url, validated_by_exchange) from `secret`.

    `validated_by_exchange` is True when the URL was just produced by a
    successful setup-token exchange (which doubles as upstream validation).
    For an already-exchanged access URL passed directly, it is False — the
    caller must run an explicit validation probe before persisting.
    """
    if secret.startswith("https://"):
        return secret, False
    claim_url = _decode_setup_token(secret)
    access_url = await _exchange_setup_token(claim_url, client)
    return access_url, True


def _decode_setup_token(token: str) -> str:
    """Base64-decode a setup token into a claim URL. Raises BackendError on failure."""
    padded = token.strip() + "=="
    for decoder in (base64.b64decode, base64.urlsafe_b64decode):
        try:
            decoded = decoder(padded).decode()
            if decoded.startswith("https://"):
                return decoded
        except Exception:
            continue
    raise BackendError("cannot decode setup token: not a base64-encoded https:// URL")


async def _exchange_setup_token(claim_url: str, client: httpx.AsyncClient) -> str:
    """POST to the claim URL and return the access URL. One-shot and irreversible."""
    import httpx as _httpx

    try:
        resp = await client.post(claim_url, timeout=15.0)
        resp.raise_for_status()
    except _httpx.HTTPStatusError as exc:
        raise BackendError(
            f"setup token exchange failed: HTTP {exc.response.status_code}"
        ) from exc
    except _httpx.RequestError as exc:
        raise BackendError(f"setup token exchange failed: {exc}") from exc

    access_url = resp.text.strip()
    if not access_url.startswith("https://"):
        raise BackendError(f"unexpected exchange response: {access_url!r}")
    return access_url


async def _validate_access_url(access_url: str, client: httpx.AsyncClient) -> None:
    """Probe the access URL with an empty-window /accounts query.

    Any non-2xx response (3xx, 4xx, 5xx) or transport error is converted to
    `BackendError`. `follow_redirects=False` is explicit: a 3xx from SimpleFIN
    would be a protocol change we want to surface, not silently follow.
    """
    import httpx as _httpx

    now = int(time.time())
    url = f"{access_url.rstrip('/')}/accounts"
    try:
        resp = await client.get(
            url,
            params={"start-date": now, "end-date": now},
            follow_redirects=False,
        )
    except _httpx.RequestError as exc:
        raise BackendError(
            f"SimpleFIN access URL validation failed: {exc}"
        ) from exc
    if not (200 <= resp.status_code < 300):
        raise BackendError(
            f"SimpleFIN access URL validation failed: HTTP {resp.status_code}"
        )


__all__ = ["activate"]
