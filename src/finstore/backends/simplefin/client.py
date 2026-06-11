"""SimpleFIN transport. HTTP, retries, window-cap filtering — nothing else.

Backend orchestration (window iteration, normalization, persistence) lives
in `finstore.backends.simplefin.backend`.
"""
from __future__ import annotations

import asyncio
import json
import logging
from urllib.parse import urlparse, urlunparse

import httpx

from finstore.backends.simplefin.models import SfResponse, _decode
from finstore.exceptions import BackendError

log = logging.getLogger(__name__)

WINDOW_CAP_CODE = "gen.api"
WINDOW_CAP_MSG_FRAGMENT = "exceeds limit of 90 days"


class UpstreamServerError(BackendError):
    """SimpleFIN returned 5xx. Retryable."""

    def __init__(self, status_code: int):
        self.status_code = status_code
        super().__init__(f"HTTP {status_code}")


class UpstreamTransportError(BackendError):
    """A transport-level failure talking to SimpleFIN (DNS, TLS, timeout, ...). Retryable."""


class UpstreamClientError(BackendError):
    """SimpleFIN returned 4xx — auth or bad request. Not retryable."""

    def __init__(self, status_code: int):
        self.status_code = status_code
        super().__init__(f"HTTP {status_code}")


class UpstreamResponseError(BackendError):
    """SimpleFIN response could not be parsed as JSON."""


class SimpleFinClient:
    def __init__(
        self,
        access_url: str,
        httpx_client: httpx.AsyncClient,
        *,
        max_retries: int = 1,
    ):
        self._client = httpx_client
        self._max_retries = max_retries
        self._endpoint = _accounts_endpoint(access_url)

    async def fetch_chunk(self, start_date: int, end_date: int) -> SfResponse:
        for attempt in range(self._max_retries + 1):
            try:
                try:
                    r = await self._client.get(
                        self._endpoint,
                        params={"start-date": start_date, "end-date": end_date},
                    )
                except httpx.TransportError as exc:
                    raise UpstreamTransportError(str(exc)) from exc

                if r.status_code >= 500:
                    raise UpstreamServerError(r.status_code)
                if r.status_code >= 400:
                    raise UpstreamClientError(r.status_code)

                try:
                    payload = r.json()
                except (json.JSONDecodeError, ValueError) as exc:
                    raise UpstreamResponseError(
                        f"could not decode SimpleFIN response as JSON: {exc}"
                    ) from exc

                return _decode(payload)
            except (UpstreamTransportError, UpstreamServerError) as exc:
                if attempt == self._max_retries:
                    raise
                delay = 0.5 * (2 ** attempt)
                log.warning("sf_retry attempt=%d error=%s delay=%.1fs", attempt + 1, exc, delay)
                await asyncio.sleep(delay)
        raise RuntimeError("unreachable")  # pragma: no cover


def _accounts_endpoint(access_url: str) -> str:
    p = urlparse(access_url)
    base_path = p.path.rstrip("/")
    return urlunparse(p._replace(path=f"{base_path}/accounts"))


def _windows(dtstart: int, end_anchor: int, window_secs: int) -> list[tuple[int, int]]:
    """Return [(start, end), ...] windows of <= window_secs, oldest first."""
    out = []
    cursor = dtstart
    while cursor < end_anchor:
        end = min(cursor + window_secs, end_anchor)
        out.append((cursor, end))
        cursor = end
    return out if out else [(dtstart, end_anchor)]


def _sanitize_msg(msg: str) -> str:
    cleaned = "".join(c for c in msg if ord(c) >= 32 and ord(c) != 127)
    return cleaned[:200]


def _filter_errlist(
    errlist: tuple[tuple[str, str], ...]
) -> list[tuple[str, str]]:
    """Drop the 90-day-cap entry; sanitize the rest."""
    out = []
    for code, msg in errlist:
        if code == WINDOW_CAP_CODE and WINDOW_CAP_MSG_FRAGMENT in msg:
            continue
        out.append((code, _sanitize_msg(msg)))
    return out
