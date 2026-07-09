"""SnapTrade HTTP client — pure transport, no normalization.

Every method returns ``St*`` types from ``models.py``; no neutral
``finstore.model`` types appear here.

Authentication: every request is signed with HMAC-SHA256 over the request
timestamp using the partner consumer key.  Per-user ``userId`` and
``userSecret`` are passed as query parameters on all user-scoped endpoints.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import time
from datetime import date, timedelta
from typing import Any
from urllib.parse import urlencode

import httpx

from finstore.backends.snaptrade.models import (
    StAccount,
    StActivity,
    StBalance,
    StBrokerageAuthorization,
    StOrder,
    StPosition,
    _decode_account,
    _decode_activity,
    _decode_balance,
    _decode_brokerage_authorization,
    _decode_order,
    _decode_position,
)

log = logging.getLogger(__name__)

_BASE_URL = "https://api.snaptrade.com/api/v1"
_API_PATH_PREFIX = "/api/v1"
_PAGE_LIMIT = 1000


def _make_signature(
    consumer_key: str,
    path: str,
    query_string: str,
    body: dict[str, Any] | None,
) -> str:
    """Compute the SnapTrade HMAC-SHA256 Signature header value."""
    sig_object = {"content": body, "path": path, "query": query_string}
    sig_content = json.dumps(sig_object, separators=(",", ":"), sort_keys=True)
    return base64.b64encode(
        hmac.new(consumer_key.encode(), sig_content.encode(), hashlib.sha256).digest()
    ).decode()


class StClient:
    """Async SnapTrade REST client.

    All calls are authenticated with:
    - ``clientId`` query parameter (partner-level)
    - ``timestamp`` + ``Signature`` request headers (HMAC-SHA256)
    - ``userId`` + ``userSecret`` query parameters (user-level)
    """

    def __init__(
        self,
        client_id: str,
        consumer_key: str,
        httpx_client: httpx.AsyncClient,
        user_id: str | None = None,
        user_secret: str | None = None,
    ) -> None:
        self._client_id = client_id
        self._consumer_key = consumer_key
        self._user_id = user_id
        self._user_secret = user_secret
        self._http = httpx_client

    # ------------------------------------------------------------------ auth

    def _build_params(self, extra: dict[str, str] | None = None) -> dict[str, str]:
        """Build the full query-param dict for one request.

        Order matches the official SDK: user params first, then clientId and
        timestamp last.  userId/userSecret are omitted for personal accounts
        (PERS- prefix clientId) where the account is identified by clientId alone.
        """
        timestamp = str(int(time.time()))
        params: dict[str, str] = {}
        if self._user_id is not None:
            params["userId"] = self._user_id
        if self._user_secret is not None:
            params["userSecret"] = self._user_secret
        params.update(extra or {})
        params["clientId"] = self._client_id
        params["timestamp"] = timestamp
        return params

    async def _get(
        self, path: str, extra_params: dict[str, str] | None = None
    ) -> Any:
        params = self._build_params(extra_params)
        full_path = f"{_API_PATH_PREFIX}{path}"
        signature = _make_signature(self._consumer_key, full_path, urlencode(params), None)
        resp = await self._http.get(
            f"{_BASE_URL}{path}",
            params=params,
            headers={"Signature": signature},
        )
        resp.raise_for_status()
        return resp.json()

    # ---------------------------------------------------------------- endpoints

    async def get_brokerage_authorizations(self) -> list[StBrokerageAuthorization]:
        data = await self._get("/brokerageAuthorizations")
        return [_decode_brokerage_authorization(a) for a in (data or [])]

    async def get_accounts(self) -> list[StAccount]:
        data = await self._get("/accounts")
        return [_decode_account(a) for a in (data or [])]

    async def get_account_balance(self, account_id: str) -> StBalance:
        """Return the USD (or first) balance for an account."""
        data = await self._get(f"/accounts/{account_id}/balances")
        entries: list[dict[str, Any]] = data or []
        # Prefer USD entry; fall back to first
        preferred = next(
            (
                e for e in entries
                if (e.get("currency") or {}).get("code") == "USD"
            ),
            entries[0] if entries else {},
        )
        return _decode_balance(account_id, preferred)

    async def get_positions(self, account_id: str) -> list[StPosition]:
        data = await self._get(f"/accounts/{account_id}/positions")
        return [_decode_position(account_id, p) for p in (data or [])]

    async def get_account_orders(self, account_id: str) -> list[StOrder]:
        """Fetch all orders for one account from ``/accounts/{id}/orders``."""
        data = await self._get(f"/accounts/{account_id}/orders")
        return [_decode_order(account_id, o) for o in (data or [])]

    async def get_activities(
        self,
        start_date: date,
        end_date: date,
        account_id: str | None = None,
    ) -> list[StActivity]:
        """Fetch activities for a date range, paginating via recursive bisection.

        When a response equals the page cap (1000), the range is split in half
        and both halves are fetched and combined.  Bisection continues until the
        range is a single calendar day (``start_date == end_date``), which is
        the smallest indivisible unit — a warning is logged only at that point.
        """
        params: dict[str, str] = {
            "startDate": start_date.isoformat(),
            "endDate": end_date.isoformat(),
        }
        if account_id:
            params["accounts"] = account_id
        data = await self._get("/activities", params)
        activities = [_decode_activity(a) for a in (data or [])]

        if len(activities) >= _PAGE_LIMIT:
            if start_date >= end_date:
                # Single-day window already at minimum granularity — cannot bisect.
                log.warning(
                    "activities_page_limit_hit start=%s end=%s — single-day window; "
                    "some activities may be missing",
                    start_date, end_date,
                )
                return activities

            delta_days = (end_date - start_date).days
            mid = start_date + timedelta(days=delta_days // 2)
            first_half = await self.get_activities(start_date, mid, account_id)
            second_half = await self.get_activities(mid + timedelta(days=1), end_date, account_id)
            return first_half + second_half

        return activities
