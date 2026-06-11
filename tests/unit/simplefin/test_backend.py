"""Tests for finstore.backends.simplefin.backend.SimpleFINBackend.

Covers the Sf*→neutral conversion seam, single- and multi-window iteration,
errlist filtering, FetchReport assembly, and constructor wiring.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any
from unittest.mock import MagicMock

import pytest

from finstore.backends.simplefin.backend import (
    FetchReport,
    SimpleFINBackend,
    SimpleFINCredentials,
    _normalize,
    _to_account,
    _to_connection,
    _to_transaction,
)
from finstore.backends.simplefin.client import (
    WINDOW_CAP_CODE,
    WINDOW_CAP_MSG_FRAGMENT,
    SimpleFinClient,
)
from finstore.backends.simplefin.models import (
    SfAccount,
    SfConnection,
    SfResponse,
    SfTransaction,
)
from finstore.model import Account, Connection, StorageChunk, Transaction
from finstore.storage.types import MergeStats

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _sf_txn(
    txn_id: str = "t1", amount: str = "10.00", posted: int = 1_700_000_000
) -> SfTransaction:
    return SfTransaction(
        id=txn_id, posted=posted, amount=Decimal(amount),
        description="desc", payee="payee", memo="memo", transacted_at=None,
    )


def _sf_account(
    acct_id: str = "acct-001",
    name: str = "Checking",
    conn_id: str = "conn-a",
    txns: tuple[SfTransaction, ...] = (),
) -> SfAccount:
    return SfAccount(
        id=acct_id, name=name, currency="USD",
        balance=Decimal("100.00"), available_balance=Decimal("95.00"),
        balance_date=1_700_000_000, conn_id=conn_id,
        transactions=txns, org={"name": "Bank"}, holdings=({"sym": "VTI"},),
    )


def _sf_conn(conn_id: str = "conn-a") -> SfConnection:
    return SfConnection(
        conn_id=conn_id, org_name="Bank", org_id="org-a",
        org_domain="bank.example", sfin_url="https://sfin", org_url="https://bank",
    )


def _sf_response(
    accounts: tuple[SfAccount, ...] = (),
    connections: tuple[SfConnection, ...] = (),
    errlist: tuple[tuple[str, str], ...] = (),
) -> SfResponse:
    return SfResponse(
        accounts=accounts, connections=connections, errlist=errlist, x_api_message=(),
    )


class _RecordingStorage:
    """Captures every StorageChunk handed to merge_chunk."""

    def __init__(self, stats_sequence: list[MergeStats] | None = None):
        self.chunks: list[tuple[str, StorageChunk]] = []
        self._stats = list(stats_sequence) if stats_sequence else []

    def merge_chunk(self, tenant_id: str, chunk: StorageChunk) -> MergeStats:
        self.chunks.append((tenant_id, chunk))
        if self._stats:
            return self._stats.pop(0)
        return MergeStats(accounts_seen=0, txns_new=0, txns_duplicate=0)


def _make_backend(
    fetch_results: list[SfResponse], *, chunk_window_days: int = 90
) -> tuple[SimpleFINBackend, list[tuple[int, int]]]:
    backend = SimpleFINBackend.__new__(SimpleFINBackend)
    backend._chunk_window_days = chunk_window_days

    calls: list[tuple[int, int]] = []
    results_iter = iter(fetch_results)

    async def fake_fetch_chunk(start: int, end: int) -> SfResponse:
        calls.append((start, end))
        return next(results_iter)

    client = MagicMock()
    client.fetch_chunk = fake_fetch_chunk
    backend._client = client
    return backend, calls


# ---------------------------------------------------------------------------
# Constructor wiring
# ---------------------------------------------------------------------------


class TestInit:
    def test_constructor_wires_simplefin_client(self, monkeypatch: Any) -> None:
        captured: dict[str, Any] = {}

        class _SpyClient:
            def __init__(self, *, access_url: str, httpx_client: Any, max_retries: int) -> None:
                captured["access_url"] = access_url
                captured["httpx_client"] = httpx_client
                captured["max_retries"] = max_retries

        monkeypatch.setattr(
            "finstore.backends.simplefin.backend.SimpleFinClient", _SpyClient
        )

        creds = SimpleFINCredentials(access_url="https://u:p@bridge.simplefin.org/simplefin")
        httpx_client = MagicMock()
        backend = SimpleFINBackend(
            credentials=creds, httpx_client=httpx_client,
            chunk_window_days=30, max_retries=3,
        )

        assert captured["access_url"] == creds.access_url
        assert captured["httpx_client"] is httpx_client
        assert captured["max_retries"] == 3
        assert backend._chunk_window_days == 30
        assert isinstance(backend._client, _SpyClient)

    def test_simplefin_client_symbol_is_used(self) -> None:
        import finstore.backends.simplefin.backend as backend_mod
        assert backend_mod.SimpleFinClient is SimpleFinClient


# ---------------------------------------------------------------------------
# Conversion helpers
# ---------------------------------------------------------------------------


class TestConversions:
    def test_to_transaction_preserves_fields(self) -> None:
        sf = _sf_txn(txn_id="t-77", amount="-12.34", posted=1_700_001_234)
        out = _to_transaction(sf)
        assert isinstance(out, Transaction)
        assert (out.id, out.amount, out.posted) == ("t-77", Decimal("-12.34"), 1_700_001_234)

    def test_to_connection_preserves_fields(self) -> None:
        out = _to_connection(_sf_conn("conn-z"))
        assert isinstance(out, Connection)
        assert out.conn_id == "conn-z"

    def test_to_account_normalizes_nested_txns(self) -> None:
        sf = _sf_account(txns=(_sf_txn("a"), _sf_txn("b")))
        out = _to_account(sf)
        assert isinstance(out, Account)
        assert len(out.transactions) == 2
        assert all(isinstance(t, Transaction) for t in out.transactions)

    def test_normalize_chunk_drops_errlist_and_x_api_message(self) -> None:
        sf = _sf_response(
            accounts=(_sf_account(),),
            connections=(_sf_conn(),),
            errlist=(("auth.error", "bad creds"),),
        )
        chunk = _normalize(sf)
        assert isinstance(chunk, StorageChunk)
        assert not hasattr(chunk, "errlist")


# ---------------------------------------------------------------------------
# fetch_and_persist orchestration
# ---------------------------------------------------------------------------


class TestFetchAndPersistSingleWindow:
    @pytest.mark.asyncio
    async def test_single_window_calls_storage_once(self) -> None:
        backend, calls = _make_backend(
            fetch_results=[_sf_response(accounts=(_sf_account(),), connections=(_sf_conn(),))]
        )
        storage = _RecordingStorage([MergeStats(accounts_seen=1, txns_new=4, txns_duplicate=1)])

        report = await backend.fetch_and_persist(
            storage,
            tenant_id="local",
            dtstart_epoch=1_700_000_000,
            dtend_epoch=1_700_000_000 + 30 * 86400,
        )

        assert len(calls) == 1
        assert len(storage.chunks) == 1
        tenant_id, chunk = storage.chunks[0]
        assert tenant_id == "local"
        assert isinstance(chunk, StorageChunk)
        assert report.chunks == 1
        assert report.accounts_seen == 1
        assert report.txns_new == 4
        assert report.txns_duplicate == 1

    @pytest.mark.asyncio
    async def test_default_dtend_uses_now(self) -> None:
        import time
        start = int(time.time()) - 86400
        backend, calls = _make_backend(fetch_results=[_sf_response()])
        storage = _RecordingStorage()
        report = await backend.fetch_and_persist(
            storage, tenant_id="local", dtstart_epoch=start, dtend_epoch=None,
        )
        assert len(calls) == 1
        assert calls[0][0] == start
        assert report.chunks == 1


class TestFetchAndPersistMultiWindow:
    @pytest.mark.asyncio
    async def test_multi_window_iterates_oldest_first(self) -> None:
        start = 1_700_000_000
        backend, calls = _make_backend(
            fetch_results=[_sf_response() for _ in range(3)],
            chunk_window_days=30,
        )
        storage = _RecordingStorage(
            [
                MergeStats(accounts_seen=1, txns_new=2, txns_duplicate=0),
                MergeStats(accounts_seen=1, txns_new=3, txns_duplicate=1),
                MergeStats(accounts_seen=2, txns_new=1, txns_duplicate=2),
            ]
        )
        report = await backend.fetch_and_persist(
            storage, tenant_id="local",
            dtstart_epoch=start, dtend_epoch=start + 90 * 86400,
        )
        assert calls[0][0] == start
        assert all(calls[i][1] == calls[i + 1][0] for i in range(len(calls) - 1))
        assert calls[-1][1] == start + 90 * 86400
        assert report.chunks == 3
        assert report.txns_new == 6
        assert report.txns_duplicate == 3
        assert report.accounts_seen == 2


class TestFetchAndPersistErrlist:
    @pytest.mark.asyncio
    async def test_window_cap_errlist_filtered_out(self) -> None:
        backend, _ = _make_backend(
            fetch_results=[
                _sf_response(errlist=(
                    (WINDOW_CAP_CODE, f"req {WINDOW_CAP_MSG_FRAGMENT}"),
                    ("other.code", "bad"),
                ))
            ]
        )
        report = await backend.fetch_and_persist(
            _RecordingStorage(),
            tenant_id="local",
            dtstart_epoch=1_700_000_000, dtend_epoch=1_700_000_000 + 86400,
        )
        assert len(report.errlist) == 1
        assert report.errlist[0][0] == "other.code"

    @pytest.mark.asyncio
    async def test_errlist_concatenated_across_windows(self) -> None:
        start = 1_700_000_000
        backend, _ = _make_backend(
            fetch_results=[
                _sf_response(errlist=(("err.a", "msg a"),)),
                _sf_response(errlist=(("err.b", "msg b"),)),
            ],
            chunk_window_days=30,
        )
        report = await backend.fetch_and_persist(
            _RecordingStorage(), tenant_id="local",
            dtstart_epoch=start, dtend_epoch=start + 60 * 86400,
        )
        assert {c for c, _ in report.errlist} == {"err.a", "err.b"}


class TestFetchAndPersistShape:
    @pytest.mark.asyncio
    async def test_returns_fetch_report(self) -> None:
        backend, _ = _make_backend(fetch_results=[_sf_response()])
        report = await backend.fetch_and_persist(
            _RecordingStorage(), tenant_id="local",
            dtstart_epoch=1_700_000_000, dtend_epoch=1_700_000_000 + 86400,
        )
        assert isinstance(report, FetchReport)
        assert report.duration_secs >= 0

    @pytest.mark.asyncio
    async def test_storage_receives_only_storage_chunks(self) -> None:
        backend, _ = _make_backend(
            fetch_results=[_sf_response(accounts=(_sf_account(),), connections=(_sf_conn(),))]
        )
        storage = _RecordingStorage()
        await backend.fetch_and_persist(
            storage, tenant_id="local",
            dtstart_epoch=1_700_000_000, dtend_epoch=1_700_000_000 + 86400,
        )
        for _, chunk in storage.chunks:
            assert isinstance(chunk, StorageChunk)
            for acct in chunk.accounts:
                assert isinstance(acct, Account)
                for txn in acct.transactions:
                    assert isinstance(txn, Transaction)
