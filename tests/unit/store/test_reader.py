"""Tests for FilesystemStorage read APIs (was gateway.store.reader)."""
import json
from decimal import Decimal
from pathlib import Path

import pytest

from finstore.model import Connection
from finstore.storage.exceptions import (
    CacheEmptyError,
    CacheMissError,
    CacheSchemaMismatchError,
)
from finstore.storage.filesystem import FilesystemStorage
from finstore.storage.paths import normalize_conn_id

TENANT = "local"


def _write_meta(
    cache_dir: Path,
    accounts: dict,
    schema_version: int = 5,
    connections: list | None = None,
) -> None:
    meta = {
        "schema_version": schema_version,
        "last_fetch_at": 1700000000,
        "connections": connections or [],
        "accounts": accounts,
        "investment_accounts": {},
    }
    (cache_dir / "meta.json").write_text(json.dumps(meta), encoding="utf-8")


def _write_account(
    cache_dir: Path,
    display_id: str,
    name: str = "Checking",
    currency: str = "USD",
    conn_id: str = "conn-a",
    balance: str = "1000.00",
    transactions: list | None = None,
) -> None:
    conn_dir = cache_dir / "accounts" / normalize_conn_id(conn_id)
    conn_dir.mkdir(parents=True, exist_ok=True)
    data = {
        "id": display_id,
        "name": name,
        "currency": currency,
        "balance": balance,
        "available-balance": None,
        "balance-date": 1700000000,
        "conn_id": conn_id,
        "transactions": transactions or [],
        "holdings": [],
    }
    (conn_dir / f"{display_id}.json").write_text(json.dumps(data), encoding="utf-8")

    meta_path = cache_dir / "meta.json"
    if meta_path.exists():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    else:
        meta = {
            "schema_version": 5, "last_fetch_at": 1700000000,
            "connections": [], "accounts": {}, "investment_accounts": {},
        }
    existing = meta.setdefault("accounts", {}).get(display_id) or {
        "last_fetch_at": 1700000000, "txn_count": 0,
        "earliest_posted": None, "latest_posted": None,
    }
    existing["conn_id"] = conn_id
    meta["accounts"][display_id] = existing
    meta_path.write_text(json.dumps(meta), encoding="utf-8")


def _make_txn_dict(txn_id: str, posted: int, amount: str = "10.00") -> dict:
    return {
        "id": txn_id, "posted": posted, "amount": amount,
        "description": "Test", "payee": "Payee", "memo": "", "transacted_at": None,
    }


class TestReadAccountWindow:
    def test_filters_by_dtstart_and_dtend(self, tmp_path):
        txns = [
            _make_txn_dict("t1", 1700000000),
            _make_txn_dict("t2", 1700100000),
            _make_txn_dict("t3", 1700200000),
            _make_txn_dict("t4", 1700300000),
        ]
        _write_account(tmp_path, "acct-001", transactions=txns)

        storage = FilesystemStorage(root=tmp_path)
        result = storage.read_account_window(TENANT, "acct-001", 1700100000, 1700200000)
        assert len(result.transactions) == 2
        assert {t.id for t in result.transactions} == {"t2", "t3"}

    def test_dtstart_inclusive(self, tmp_path):
        txns = [_make_txn_dict("t1", 1700000000), _make_txn_dict("t2", 1700000001)]
        _write_account(tmp_path, "acct-001", transactions=txns)
        storage = FilesystemStorage(root=tmp_path)
        result = storage.read_account_window(TENANT, "acct-001", 1700000000, 1700000001)
        assert len(result.transactions) == 2

    def test_dtend_inclusive(self, tmp_path):
        txns = [_make_txn_dict("t1", 1700000010), _make_txn_dict("t2", 1700000011)]
        _write_account(tmp_path, "acct-001", transactions=txns)
        storage = FilesystemStorage(root=tmp_path)
        result = storage.read_account_window(TENANT, "acct-001", 1700000000, 1700000010)
        assert len(result.transactions) == 1
        assert result.transactions[0].id == "t1"

    def test_dtend_none_returns_all_from_dtstart(self, tmp_path):
        txns = [
            _make_txn_dict("t1", 1699000000),
            _make_txn_dict("t2", 1700000000),
            _make_txn_dict("t3", 1701000000),
            _make_txn_dict("t4", 9999999999),
        ]
        _write_account(tmp_path, "acct-001", transactions=txns)
        storage = FilesystemStorage(root=tmp_path)
        result = storage.read_account_window(TENANT, "acct-001", 1700000000, None)
        assert {t.id for t in result.transactions} == {"t2", "t3", "t4"}

    def test_no_transactions_in_window(self, tmp_path):
        _write_account(tmp_path, "acct-001", transactions=[_make_txn_dict("t1", 1700000000)])
        storage = FilesystemStorage(root=tmp_path)
        result = storage.read_account_window(TENANT, "acct-001", 1800000000, 1900000000)
        assert result.transactions == ()

    def test_account_object_has_full_balance_data(self, tmp_path):
        _write_account(tmp_path, "acct-001", balance="2500.00")
        storage = FilesystemStorage(root=tmp_path)
        result = storage.read_account_window(TENANT, "acct-001", 0, None)
        assert result.account.balance == Decimal("2500.00")
        assert result.account.id == "acct-001"

    def test_transactions_parsed(self, tmp_path):
        _write_account(
            tmp_path, "acct-001", transactions=[_make_txn_dict("t1", 1700000000, "-42.50")],
        )
        storage = FilesystemStorage(root=tmp_path)
        result = storage.read_account_window(TENANT, "acct-001", 0, None)
        assert len(result.transactions) == 1
        txn = result.transactions[0]
        assert txn.amount == Decimal("-42.50")
        assert txn.posted == 1700000000


class TestCacheMissError:
    def test_raises_when_account_file_missing(self, tmp_path):
        _write_meta(tmp_path, accounts={"nonexistent-acct": {
            "conn_id": "conn-a", "last_fetch_at": 1700000000, "txn_count": 0,
            "earliest_posted": None, "latest_posted": None,
        }})
        storage = FilesystemStorage(root=tmp_path)
        with pytest.raises(CacheMissError) as exc_info:
            storage.read_account_window(TENANT, "nonexistent-acct", 0, None)
        assert exc_info.value.acctid == "nonexistent-acct"

    def test_miss_error_stores_acctid(self):
        err = CacheMissError("some-id")
        assert err.acctid == "some-id"


class TestCacheEmptyError:
    def test_raises_when_meta_missing(self, tmp_path):
        storage = FilesystemStorage(root=tmp_path)
        with pytest.raises(CacheEmptyError):
            storage.list_accounts(TENANT)

    def test_raises_when_meta_has_no_accounts(self, tmp_path):
        _write_meta(tmp_path, accounts={})
        storage = FilesystemStorage(root=tmp_path)
        with pytest.raises(CacheEmptyError):
            storage.list_accounts(TENANT)


class TestCacheSchemaMismatchError:
    def test_raises_on_wrong_schema_version(self, tmp_path):
        _write_meta(
            tmp_path,
            accounts={"acct-001": {"last_fetch_at": 1700000000, "txn_count": 0}},
            schema_version=99,
        )
        storage = FilesystemStorage(root=tmp_path)
        with pytest.raises(CacheSchemaMismatchError) as exc_info:
            storage.list_accounts(TENANT)
        assert "99" in str(exc_info.value)
        assert "5" in str(exc_info.value)

    def test_raises_on_version_zero(self, tmp_path):
        _write_meta(
            tmp_path,
            accounts={"acct-001": {"last_fetch_at": 0, "txn_count": 0}},
            schema_version=0,
        )
        storage = FilesystemStorage(root=tmp_path)
        with pytest.raises(CacheSchemaMismatchError):
            storage.list_accounts(TENANT)


class TestListAccounts:
    def _setup(self, cache_dir: Path) -> None:
        conn = {"conn_id": "conn-a", "org_name": "Bank A", "org_id": "org-a"}
        _write_meta(
            cache_dir,
            accounts={
                "Checking": {
                    "last_fetch_at": 1700000000, "txn_count": 5, "conn_id": "conn-a",
                    "earliest_posted": None, "latest_posted": None,
                },
                "Savings": {
                    "last_fetch_at": 1700010000, "txn_count": 3, "conn_id": "conn-a",
                    "earliest_posted": None, "latest_posted": None,
                },
            },
            connections=[conn],
        )
        _write_account(cache_dir, "Checking", name="Checking", conn_id="conn-a")
        _write_account(cache_dir, "Savings", name="Savings", conn_id="conn-a", currency="CAD")

    def test_returns_tuple_of_summaries(self, tmp_path):
        self._setup(tmp_path)
        storage = FilesystemStorage(root=tmp_path)
        stubs = storage.list_accounts(TENANT)
        assert isinstance(stubs, tuple)
        assert len(stubs) == 2

    def test_summary_fields_correct(self, tmp_path):
        self._setup(tmp_path)
        storage = FilesystemStorage(root=tmp_path)
        stubs = storage.list_accounts(TENANT)
        m = {s.acctid: s for s in stubs}
        assert m["Checking"].name == "Checking"
        assert m["Checking"].currency == "USD"
        assert m["Checking"].txn_count == 5
        assert m["Savings"].currency == "CAD"

    def test_connection_joined(self, tmp_path):
        self._setup(tmp_path)
        storage = FilesystemStorage(root=tmp_path)
        for stub in storage.list_accounts(TENANT):
            assert isinstance(stub.connection, Connection)
            assert stub.connection.conn_id == "conn-a"
            assert stub.connection.org_name == "Bank A"

    def test_missing_account_file_skipped(self, tmp_path):
        conn = {"conn_id": "conn-a", "org_name": "Bank A", "org_id": "org-a"}
        _write_meta(
            tmp_path,
            accounts={
                "acct-exists": {
                    "last_fetch_at": 1700000000, "txn_count": 2, "conn_id": "conn-a",
                    "earliest_posted": None, "latest_posted": None,
                },
                "acct-missing": {
                    "last_fetch_at": 1700000000, "txn_count": 0, "conn_id": "conn-a",
                    "earliest_posted": None, "latest_posted": None,
                },
            },
            connections=[conn],
        )
        _write_account(tmp_path, "acct-exists", conn_id="conn-a")
        storage = FilesystemStorage(root=tmp_path)
        stubs = storage.list_accounts(TENANT)
        assert len(stubs) == 1
        assert stubs[0].acctid == "acct-exists"

    def test_unknown_conn_id_uses_fallback(self, tmp_path):
        _write_meta(
            tmp_path,
            accounts={
                "acct-x": {
                    "last_fetch_at": 1700000000, "txn_count": 0, "conn_id": "unknown-conn",
                    "earliest_posted": None, "latest_posted": None,
                },
            },
            connections=[],
        )
        _write_account(tmp_path, "acct-x", conn_id="unknown-conn")
        storage = FilesystemStorage(root=tmp_path)
        stubs = storage.list_accounts(TENANT)
        assert stubs[0].connection.org_name == "SimpleFIN"

    def test_last_fetch_at_none_when_zero(self, tmp_path):
        _write_meta(
            tmp_path,
            accounts={"acct-z": {
                "last_fetch_at": 0, "txn_count": 0, "conn_id": "c",
                "earliest_posted": None, "latest_posted": None,
            }},
            connections=[],
        )
        _write_account(tmp_path, "acct-z", conn_id="c")
        storage = FilesystemStorage(root=tmp_path)
        assert storage.list_accounts(TENANT)[0].last_fetch_at is None
