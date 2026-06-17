"""Tests for SnapTradeBackend normalization — action_type mapping, security ID
picking, date windowing, and merge_chunk call shape.

The ``StClient`` is mocked directly so these tests exercise only the
normalization seam, not the HTTP transport.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from finstore.backends.snaptrade.backend import (
    SnapTradeBackend,
    SnapTradeCredentials,
    _ACTION_MAP,
    _normalize_activity,
    _pick_security_id,
    _symbol_to_security,
    _windows,
)
from finstore.backends.snaptrade.models import (
    StAccount,
    StActivity,
    StBalance,
    StBrokerage,
    StBrokerageAuthorization,
    StPosition,
    StSymbol,
)
from finstore.model import StorageChunk
from finstore.storage.types import MergeStats


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _sym(
    symbol: str = "AAPL",
    figi: str | None = "BBG000B9XRY4",
    cusip: str | None = "037833100",
    isin: str | None = None,
) -> StSymbol:
    return StSymbol(
        id="sym-1",
        symbol=symbol,
        description=f"{symbol} Inc.",
        figi_code=figi,
        cusip=cusip,
        isin=isin,
        currency=None,
    )


def _activity(
    action_type: str = "BUY",
    account_id: str = "acct-1",
    units: str = "10",
    price: str = "175.00",
    amount: str = "-1750.00",
    symbol: StSymbol | None = None,
    trade_date: str = "2024-01-12",
    txn_id: str = "act-1",
) -> StActivity:
    return StActivity(
        id=txn_id,
        account_id=account_id,
        trade_date=trade_date,
        settlement_date=None,
        action_type=action_type,
        units=Decimal(units),
        price=Decimal(price),
        amount=Decimal(amount),
        fee=Decimal("0"),
        currency="USD",
        description=f"{action_type} {units}",
        symbol=symbol or _sym(),
    )


def _balance(account_id: str = "acct-1") -> StBalance:
    return StBalance(
        account_id=account_id,
        cash=Decimal("500"),
        buying_power=Decimal("500"),
        total_value=Decimal("5500"),
        currency="USD",
    )


def _st_account(
    acct_id: str = "acct-1",
    name: str = "Schwab Brokerage",
    auth_id: str = "auth-1",
) -> StAccount:
    return StAccount(
        id=acct_id,
        name=name,
        number="Q654",
        institution_name="Schwab",
        brokerage_authorization_id=auth_id,
    )


def _auth(auth_id: str = "auth-1", slug: str = "SCHWAB") -> StBrokerageAuthorization:
    return StBrokerageAuthorization(
        id=auth_id,
        brokerage=StBrokerage(id="br-1", name="Charles Schwab", slug=slug),
    )


def _make_mock_storage(inv_accounts_seen: int = 1) -> MagicMock:
    storage = MagicMock()
    storage.merge_chunk.return_value = MergeStats(
        accounts_seen=0,
        txns_new=0,
        txns_duplicate=0,
        inv_accounts_seen=inv_accounts_seen,
        inv_txns_new=1,
        inv_txns_duplicate=0,
        positions_written=1,
        securities_upserted=1,
    )
    return storage


def _make_mock_client(
    auth_list: list[StBrokerageAuthorization] | None = None,
    accounts: list[StAccount] | None = None,
    activities: list[StActivity] | None = None,
    positions: list[StPosition] | None = None,
    balance: StBalance | None = None,
) -> AsyncMock:
    client = AsyncMock()
    client.get_brokerage_authorizations.return_value = auth_list or [_auth()]
    client.get_accounts.return_value = accounts or [_st_account()]
    client.get_activities.return_value = activities or []
    client.get_positions.return_value = positions or []
    client.get_account_balance.return_value = balance or _balance()
    return client


# ---------------------------------------------------------------------------
# _pick_security_id
# ---------------------------------------------------------------------------


class TestPickSecurityId:
    def test_figi_wins_over_cusip(self) -> None:
        uid, uid_type = _pick_security_id(_sym(figi="BBG000B9XRY4", cusip="037833100"))
        assert uid == "BBG000B9XRY4"
        assert uid_type == "FIGI"

    def test_cusip_when_no_figi(self) -> None:
        uid, uid_type = _pick_security_id(_sym(figi=None, cusip="037833100"))
        assert uid == "037833100"
        assert uid_type == "CUSIP"

    def test_isin_when_no_figi_or_cusip(self) -> None:
        uid, uid_type = _pick_security_id(_sym(figi=None, cusip=None, isin="US0378331005"))
        assert uid == "US0378331005"
        assert uid_type == "ISIN"

    def test_ticker_fallback(self) -> None:
        uid, uid_type = _pick_security_id(_sym(figi=None, cusip=None, isin=None))
        assert uid == "AAPL"
        assert uid_type == "TICKER"


# ---------------------------------------------------------------------------
# action_type → trntype mapping
# ---------------------------------------------------------------------------


class TestActionTypeMapping:
    @pytest.mark.parametrize("action_type,expected_trntype,expected_income", [
        ("BUY",           "BUY",          None),
        ("BUY_TO_OPEN",   "BUY",          None),
        ("SELL",          "SELL",         None),
        ("SELL_TO_CLOSE", "SELL",         None),
        ("DIV",           "INCOME",       "DIV"),
        ("DIVIDEND",      "INCOME",       "DIV"),
        ("REINVEST",      "REINVEST",     "DIV"),
        ("DRIP",          "REINVEST",     "DIV"),
        ("CONTRIBUTION",  "CONTRIBUTION", None),
        ("DEPOSIT",       "CONTRIBUTION", None),
        ("WITHDRAWAL",    "WITHDRAWAL",   None),
        ("FEE",           "FEE",          None),
        ("MANAGEMENT_FEE","FEE",          None),
        ("TAX",           "TAX",          None),
        ("TRANSFER",      "TRANSFER",     None),
        ("JOURNAL",       "TRANSFER",     None),
        ("SPLIT",         "SPLIT",        None),
    ])
    def test_known_action_type(
        self, action_type: str, expected_trntype: str, expected_income: str | None
    ) -> None:
        act = _activity(action_type=action_type)
        txn = _normalize_activity(act)
        assert txn.trntype == expected_trntype
        assert txn.income_type == expected_income

    def test_unknown_action_type_maps_to_other(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        act = _activity(action_type="EXOTIC_OPTION_EXERCISE")
        with caplog.at_level(logging.WARNING, logger="finstore.backends.snaptrade.backend"):
            txn = _normalize_activity(act)
        assert txn.trntype == "OTHER"
        assert any("EXOTIC_OPTION_EXERCISE" in r.message for r in caplog.records)

    def test_action_type_case_insensitive(self) -> None:
        act = _activity(action_type="buy")
        txn = _normalize_activity(act)
        assert txn.trntype == "BUY"


# ---------------------------------------------------------------------------
# _normalize_activity field mapping
# ---------------------------------------------------------------------------


class TestNormalizeActivity:
    def test_security_id_from_figi(self) -> None:
        act = _activity(symbol=_sym(figi="BBG000B9XRY4"))
        txn = _normalize_activity(act)
        assert txn.security_id == "BBG000B9XRY4"
        assert txn.security_id_type == "FIGI"

    def test_trade_date_converted_to_epoch(self) -> None:
        act = _activity(trade_date="2024-01-12")
        txn = _normalize_activity(act)
        assert txn.trade_date > 0

    def test_contribution_no_security(self) -> None:
        act = StActivity(
            id="act-c",
            account_id="acct-1",
            trade_date="2024-01-01",
            settlement_date=None,
            action_type="CONTRIBUTION",
            units=None,
            price=None,
            amount=Decimal("5000"),
            fee=None,
            currency="USD",
            description="deposit",
            symbol=None,
        )
        txn = _normalize_activity(act)
        assert txn.security_id is None
        assert txn.security_id_type is None
        assert txn.total == Decimal("5000")


# ---------------------------------------------------------------------------
# _windows helper
# ---------------------------------------------------------------------------


class TestWindows:
    def test_single_window(self) -> None:
        wins = _windows(0, 100, 200)
        assert wins == [(0, 100)]

    def test_exact_fit(self) -> None:
        wins = _windows(0, 200, 100)
        assert wins == [(0, 100), (100, 200)]

    def test_partial_last_window(self) -> None:
        wins = _windows(0, 250, 100)
        assert len(wins) == 3
        assert wins[-1] == (200, 250)

    def test_empty_when_start_equals_end(self) -> None:
        assert _windows(100, 100, 50) == []


# ---------------------------------------------------------------------------
# SnapTradeBackend.fetch_and_persist — integration with mocked StClient
# ---------------------------------------------------------------------------


class TestFetchAndPersist:
    def _make_backend(self, mock_client: AsyncMock) -> SnapTradeBackend:
        creds = SnapTradeCredentials(
            client_id="cid", consumer_key="ckey",
            user_id="uid", user_secret="usec",
        )
        backend = SnapTradeBackend(creds, MagicMock(), activity_window_days=90)
        backend._client = mock_client
        return backend

    @pytest.mark.asyncio
    async def test_calls_merge_chunk_with_investment_accounts_and_securities(
        self,
    ) -> None:
        activity = _activity(symbol=_sym())
        mock_client = _make_mock_client(activities=[activity])
        storage = _make_mock_storage()
        backend = self._make_backend(mock_client)

        await backend.fetch_and_persist(
            storage,
            tenant_id="local",
            dtstart_epoch=1_700_000_000,
            dtend_epoch=1_700_000_000 + 86400,
        )

        assert storage.merge_chunk.call_count == 1
        _, chunk = storage.merge_chunk.call_args[0]
        assert isinstance(chunk, StorageChunk)
        assert len(chunk.investment_accounts) == 1
        assert len(chunk.securities) >= 1
        assert chunk.accounts == ()

    @pytest.mark.asyncio
    async def test_activities_accumulate_across_windows(self) -> None:
        """Two date windows → client.get_activities called twice; all activities merged."""
        # Each call returns 50 activities, simulating two non-paginated windows
        call_count = 0

        async def _get_activities(
            start_date: date, end_date: date, account_id: str | None = None
        ) -> list[StActivity]:
            nonlocal call_count
            call_count += 1
            return [_activity(txn_id=f"act-{call_count}-{i}") for i in range(50)]

        mock_client = _make_mock_client()
        mock_client.get_activities.side_effect = _get_activities
        storage = _make_mock_storage()
        backend = self._make_backend(mock_client)
        # 200 days → 3 windows at 90-day default
        backend._activity_window_days = 90

        await backend.fetch_and_persist(
            storage,
            tenant_id="local",
            dtstart_epoch=1_700_000_000,
            dtend_epoch=1_700_000_000 + 200 * 86400,
        )

        assert mock_client.get_activities.call_count >= 2
        _, chunk = storage.merge_chunk.call_args[0]
        total_txns = sum(
            len(a.investment_transactions) for a in chunk.investment_accounts
        )
        # 3 windows × 50 activities each
        assert total_txns == 3 * 50

    @pytest.mark.asyncio
    async def test_conn_id_derived_from_brokerage_slug(self) -> None:
        mock_client = _make_mock_client(
            auth_list=[_auth(auth_id="auth-1", slug="SCHWAB")],
            accounts=[_st_account(auth_id="auth-1")],
        )
        storage = _make_mock_storage()
        backend = self._make_backend(mock_client)

        await backend.fetch_and_persist(
            storage, tenant_id="local",
            dtstart_epoch=1_700_000_000, dtend_epoch=1_700_000_000 + 86400,
        )

        _, chunk = storage.merge_chunk.call_args[0]
        assert chunk.investment_accounts[0].conn_id == "schwab"
        assert chunk.connections[0].conn_id == "schwab"

    @pytest.mark.asyncio
    async def test_report_reflects_merge_stats(self) -> None:
        mock_client = _make_mock_client()
        storage = _make_mock_storage(inv_accounts_seen=1)
        backend = self._make_backend(mock_client)

        report = await backend.fetch_and_persist(
            storage, tenant_id="local",
            dtstart_epoch=1_700_000_000, dtend_epoch=1_700_000_000 + 86400,
        )

        assert report.accounts_seen == 1
        assert report.duration_secs >= 0
