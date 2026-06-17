"""Phase 1 storage tests — investment accounts, positions, securities."""
from __future__ import annotations

import json
import logging
import stat
from decimal import Decimal
from pathlib import Path

import pytest

from finstore.model import (
    AccountType,
    Connection,
    InvestmentAccount,
    InvestmentTransaction,
    Position,
    Security,
    StorageChunk,
)
from finstore.storage.exceptions import CacheEmptyError, CacheMissError, CacheSchemaMismatchError
from finstore.storage.filesystem import FilesystemStorage, _atomic_write_json
from finstore.storage.paths import infer_account_type, normalize_conn_id, sanitize_account_name

TENANT = "local"
CONN_SCHWAB = Connection(conn_id="schwab", org_name="Charles Schwab", org_id="schwab")


# ---------------------------------------------------------------------------
# Shared builders
# ---------------------------------------------------------------------------


def _make_security(
    uniqueid: str = "037833100",
    uniqueid_type: str = "CUSIP",
    ticker: str = "AAPL",
    security_type: str = "STOCK",
) -> Security:
    return Security(
        uniqueid=uniqueid,
        uniqueid_type=uniqueid_type,
        name=f"Security {ticker}",
        ticker=ticker,
        security_type=security_type,
    )


def _make_position(
    security_id: str = "037833100",
    security_id_type: str = "CUSIP",
    units: str = "10",
    unit_price: str = "175.00",
    snapshot_date: int = 1_700_000_000,
) -> Position:
    units_d = Decimal(units)
    price_d = Decimal(unit_price)
    return Position(
        security_id=security_id,
        security_id_type=security_id_type,
        units=units_d,
        unit_price=price_d,
        market_value=units_d * price_d,
        cost_basis=None,
        held_in_acct="CASH",
        pos_type="LONG",
        snapshot_date=snapshot_date,
    )


def _make_inv_txn(
    txn_id: str = "itxn-1",
    trade_date: int = 1_700_000_000,
    trntype: str = "BUY",
    total: str = "-1750.00",
) -> InvestmentTransaction:
    return InvestmentTransaction(
        id=txn_id,
        trade_date=trade_date,
        settle_date=None,
        trntype=trntype,
        security_id="037833100",
        security_id_type="CUSIP",
        units=Decimal("10"),
        unit_price=Decimal("175.00"),
        commission=None,
        fees=None,
        taxes=None,
        total=Decimal(total),
        income_type=None,
        description=f"{trntype} AAPL",
        memo="",
        currency="USD",
    )


def _make_inv_account(
    name: str = "Schwab Brokerage",
    conn_id: str = "schwab",
    positions: list[Position] | None = None,
    txns: list[InvestmentTransaction] | None = None,
) -> InvestmentAccount:
    return InvestmentAccount(
        id="inv-acct-001",
        name=name,
        currency="USD",
        broker_id=conn_id,
        available_cash=Decimal("500.00"),
        margin_balance=None,
        balance_date=1_700_000_000,
        conn_id=conn_id,
        positions=tuple(positions or []),
        investment_transactions=tuple(txns or []),
    )


def _inv_chunk(
    inv_accounts: list[InvestmentAccount],
    securities: list[Security] | None = None,
    connections: list[Connection] | None = None,
) -> StorageChunk:
    if connections is None:
        conn_ids = {a.conn_id for a in inv_accounts}
        connections = [Connection(conn_id=cid, org_name=cid, org_id=cid) for cid in conn_ids]
    return StorageChunk(
        accounts=(),
        connections=tuple(connections),
        investment_accounts=tuple(inv_accounts),
        securities=tuple(securities or []),
    )


# ---------------------------------------------------------------------------
# Basic write: investment account + positions
# ---------------------------------------------------------------------------


class TestInvestmentAccountWrite:
    def test_creates_investment_dir(self, tmp_path: Path) -> None:
        storage = FilesystemStorage(root=tmp_path)
        storage.merge_chunk(TENANT, _inv_chunk([_make_inv_account()]))
        assert (tmp_path / "investment").is_dir()

    def test_account_file_written(self, tmp_path: Path) -> None:
        storage = FilesystemStorage(root=tmp_path)
        acct = _make_inv_account(txns=[_make_inv_txn()])
        storage.merge_chunk(TENANT, _inv_chunk([acct]))

        display_id = sanitize_account_name("Schwab Brokerage")
        acct_path = (
            tmp_path / "investment" / normalize_conn_id("schwab") / f"{display_id}.json"
        )
        assert acct_path.exists()
        data = json.loads(acct_path.read_text())
        assert data["broker_id"] == "schwab"
        assert len(data["investment_transactions"]) == 1
        assert data["investment_transactions"][0]["id"] == "itxn-1"

    def test_positions_file_written(self, tmp_path: Path) -> None:
        storage = FilesystemStorage(root=tmp_path)
        acct = _make_inv_account(positions=[_make_position()])
        storage.merge_chunk(TENANT, _inv_chunk([acct]))

        display_id = sanitize_account_name("Schwab Brokerage")
        pos_path = (
            tmp_path
            / "investment"
            / normalize_conn_id("schwab")
            / f"{display_id}.positions.json"
        )
        assert pos_path.exists()
        data = json.loads(pos_path.read_text())
        assert len(data["positions"]) == 1
        assert data["positions"][0]["security_id"] == "037833100"

    def test_files_mode_0o600(self, tmp_path: Path) -> None:
        storage = FilesystemStorage(root=tmp_path)
        acct = _make_inv_account(positions=[_make_position()], txns=[_make_inv_txn()])
        storage.merge_chunk(TENANT, _inv_chunk([acct]))

        display_id = sanitize_account_name("Schwab Brokerage")
        base = tmp_path / "investment" / normalize_conn_id("schwab")
        for fname in [f"{display_id}.json", f"{display_id}.positions.json"]:
            assert stat.S_IMODE((base / fname).stat().st_mode) == 0o600

    def test_merge_stats_investment_fields(self, tmp_path: Path) -> None:
        storage = FilesystemStorage(root=tmp_path)
        acct = _make_inv_account(
            positions=[_make_position()],
            txns=[_make_inv_txn("t1"), _make_inv_txn("t2")],
        )
        stats = storage.merge_chunk(TENANT, _inv_chunk([acct]))

        assert stats.inv_accounts_seen == 1
        assert stats.inv_txns_new == 2
        assert stats.inv_txns_duplicate == 0
        assert stats.positions_written == 1
        assert stats.accounts_seen == 0
        assert stats.txns_new == 0

    def test_meta_investment_accounts_key(self, tmp_path: Path) -> None:
        storage = FilesystemStorage(root=tmp_path)
        acct = _make_inv_account(txns=[_make_inv_txn()])
        storage.merge_chunk(TENANT, _inv_chunk([acct]))

        meta = json.loads((tmp_path / "meta.json").read_text())
        assert "investment_accounts" in meta
        display_id = sanitize_account_name("Schwab Brokerage")
        assert display_id in meta["investment_accounts"]
        inv_meta = meta["investment_accounts"][display_id]
        assert inv_meta["broker_id"] == "schwab"
        assert inv_meta["txn_count"] == 1


# ---------------------------------------------------------------------------
# Transaction dedup for investment accounts
# ---------------------------------------------------------------------------


class TestInvestmentTransactionDedup:
    def test_overlapping_txns_deduped(self, tmp_path: Path) -> None:
        storage = FilesystemStorage(root=tmp_path)
        storage.merge_chunk(TENANT, _inv_chunk([
            _make_inv_account(txns=[_make_inv_txn("t1"), _make_inv_txn("t2")])
        ]))
        stats = storage.merge_chunk(TENANT, _inv_chunk([
            _make_inv_account(txns=[_make_inv_txn("t2"), _make_inv_txn("t3")])
        ]))

        assert stats.inv_txns_new == 1
        assert stats.inv_txns_duplicate == 1

        display_id = sanitize_account_name("Schwab Brokerage")
        acct_path = (
            tmp_path / "investment" / normalize_conn_id("schwab") / f"{display_id}.json"
        )
        data = json.loads(acct_path.read_text())
        ids = {t["id"] for t in data["investment_transactions"]}
        assert ids == {"t1", "t2", "t3"}

    def test_same_id_different_total_warns_and_keeps_stored(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        storage = FilesystemStorage(root=tmp_path)
        storage.merge_chunk(TENANT, _inv_chunk([
            _make_inv_account(txns=[_make_inv_txn("t1", total="-1750.00")])
        ]))

        with caplog.at_level(logging.WARNING, logger="finstore.storage.filesystem"):
            storage.merge_chunk(TENANT, _inv_chunk([
                _make_inv_account(txns=[_make_inv_txn("t1", total="-1800.00")])
            ]))

        assert any("t1" in r.message and "keeping stored" in r.message for r in caplog.records)

        display_id = sanitize_account_name("Schwab Brokerage")
        acct_path = (
            tmp_path / "investment" / normalize_conn_id("schwab") / f"{display_id}.json"
        )
        data = json.loads(acct_path.read_text())
        stored_total = data["investment_transactions"][0]["total"]
        assert stored_total == "-1750.00"


# ---------------------------------------------------------------------------
# Positions are replaced wholesale on every merge
# ---------------------------------------------------------------------------


class TestPositionsReplacedWholesale:
    def test_second_merge_replaces_positions(self, tmp_path: Path) -> None:
        storage = FilesystemStorage(root=tmp_path)

        pos_v1 = _make_position(units="10", unit_price="175.00", snapshot_date=1_700_000_000)
        storage.merge_chunk(TENANT, _inv_chunk([_make_inv_account(positions=[pos_v1])]))

        pos_v2 = _make_position(units="20", unit_price="180.00", snapshot_date=1_700_100_000)
        storage.merge_chunk(TENANT, _inv_chunk([_make_inv_account(positions=[pos_v2])]))

        display_id = sanitize_account_name("Schwab Brokerage")
        pos_path = (
            tmp_path
            / "investment"
            / normalize_conn_id("schwab")
            / f"{display_id}.positions.json"
        )
        data = json.loads(pos_path.read_text())
        assert len(data["positions"]) == 1
        assert data["positions"][0]["units"] == "20"
        assert data["positions"][0]["snapshot_date"] == 1_700_100_000

    def test_positions_count_in_meta_updated(self, tmp_path: Path) -> None:
        storage = FilesystemStorage(root=tmp_path)

        storage.merge_chunk(TENANT, _inv_chunk([
            _make_inv_account(positions=[_make_position("A", "TICKER"), _make_position("B", "TICKER")])
        ]))
        meta = json.loads((tmp_path / "meta.json").read_text())
        display_id = sanitize_account_name("Schwab Brokerage")
        assert meta["investment_accounts"][display_id]["position_count"] == 2

        storage.merge_chunk(TENANT, _inv_chunk([
            _make_inv_account(positions=[_make_position("A", "TICKER")])
        ]))
        meta = json.loads((tmp_path / "meta.json").read_text())
        assert meta["investment_accounts"][display_id]["position_count"] == 1


# ---------------------------------------------------------------------------
# Securities registry
# ---------------------------------------------------------------------------


class TestSecuritiesUpsert:
    def test_securities_file_created(self, tmp_path: Path) -> None:
        storage = FilesystemStorage(root=tmp_path)
        sec = _make_security()
        storage.merge_chunk(TENANT, _inv_chunk([_make_inv_account()], securities=[sec]))
        assert (tmp_path / "securities.json").exists()

    def test_securities_written_correctly(self, tmp_path: Path) -> None:
        storage = FilesystemStorage(root=tmp_path)
        sec = _make_security(ticker="AAPL")
        storage.merge_chunk(TENANT, _inv_chunk([_make_inv_account()], securities=[sec]))

        data = json.loads((tmp_path / "securities.json").read_text())
        assert len(data["securities"]) == 1
        assert data["securities"][0]["ticker"] == "AAPL"

    def test_second_security_appended(self, tmp_path: Path) -> None:
        storage = FilesystemStorage(root=tmp_path)
        storage.merge_chunk(TENANT, _inv_chunk(
            [_make_inv_account()],
            securities=[_make_security("CUSIP-A", "CUSIP", "AAPL")],
        ))
        storage.merge_chunk(TENANT, _inv_chunk(
            [_make_inv_account()],
            securities=[_make_security("CUSIP-B", "CUSIP", "MSFT")],
        ))

        data = json.loads((tmp_path / "securities.json").read_text())
        tickers = {s["ticker"] for s in data["securities"]}
        assert tickers == {"AAPL", "MSFT"}

    def test_existing_security_updated(self, tmp_path: Path) -> None:
        storage = FilesystemStorage(root=tmp_path)
        storage.merge_chunk(TENANT, _inv_chunk(
            [_make_inv_account()],
            securities=[Security("037833100", "CUSIP", "Apple Inc", "AAPL", "STOCK")],
        ))
        storage.merge_chunk(TENANT, _inv_chunk(
            [_make_inv_account()],
            securities=[Security("037833100", "CUSIP", "Apple Inc.", "AAPL", "STOCK")],
        ))

        data = json.loads((tmp_path / "securities.json").read_text())
        assert len(data["securities"]) == 1
        assert data["securities"][0]["name"] == "Apple Inc."

    def test_merge_stats_securities_upserted(self, tmp_path: Path) -> None:
        storage = FilesystemStorage(root=tmp_path)
        stats = storage.merge_chunk(TENANT, _inv_chunk(
            [_make_inv_account()],
            securities=[_make_security("A"), _make_security("B")],
        ))
        assert stats.securities_upserted == 2


# ---------------------------------------------------------------------------
# Read methods
# ---------------------------------------------------------------------------


class TestReadInvestmentAccount:
    def test_read_investment_account(self, tmp_path: Path) -> None:
        storage = FilesystemStorage(root=tmp_path)
        acct = _make_inv_account(
            positions=[_make_position()],
            txns=[_make_inv_txn("t1"), _make_inv_txn("t2")],
        )
        storage.merge_chunk(TENANT, _inv_chunk([acct]))

        display_id = sanitize_account_name("Schwab Brokerage")
        cached = storage.read_investment_account(TENANT, display_id)

        assert cached.account.broker_id == "schwab"
        assert cached.account.available_cash == Decimal("500.00")
        assert len(cached.account.positions) == 1
        assert len(cached.investment_transactions) == 2

    def test_read_investment_account_missing_raises(self, tmp_path: Path) -> None:
        storage = FilesystemStorage(root=tmp_path)
        storage.merge_chunk(TENANT, _inv_chunk([_make_inv_account()]))
        with pytest.raises(CacheMissError):
            storage.read_investment_account(TENANT, "nonexistent")

    def test_read_investment_account_window_filters_by_trade_date(
        self, tmp_path: Path
    ) -> None:
        storage = FilesystemStorage(root=tmp_path)
        txns = [
            _make_inv_txn("t1", trade_date=1_700_000_000),
            _make_inv_txn("t2", trade_date=1_700_100_000),
            _make_inv_txn("t3", trade_date=1_700_200_000),
        ]
        storage.merge_chunk(TENANT, _inv_chunk([_make_inv_account(txns=txns)]))

        display_id = sanitize_account_name("Schwab Brokerage")
        cached = storage.read_investment_account_window(
            TENANT, display_id, 1_700_050_000, 1_700_150_000
        )
        assert len(cached.investment_transactions) == 1
        assert cached.investment_transactions[0].id == "t2"

    def test_read_investment_account_window_no_upper_bound(self, tmp_path: Path) -> None:
        storage = FilesystemStorage(root=tmp_path)
        txns = [_make_inv_txn("t1", trade_date=1_700_000_000),
                _make_inv_txn("t2", trade_date=1_800_000_000)]
        storage.merge_chunk(TENANT, _inv_chunk([_make_inv_account(txns=txns)]))

        display_id = sanitize_account_name("Schwab Brokerage")
        cached = storage.read_investment_account_window(
            TENANT, display_id, 1_700_000_000, None
        )
        assert len(cached.investment_transactions) == 2


class TestListInvestmentAccounts:
    def test_list_returns_summary(self, tmp_path: Path) -> None:
        storage = FilesystemStorage(root=tmp_path)
        acct = _make_inv_account(
            positions=[_make_position()],
            txns=[_make_inv_txn()],
        )
        storage.merge_chunk(TENANT, _inv_chunk([acct], connections=[CONN_SCHWAB]))

        summaries = storage.list_investment_accounts(TENANT)
        assert len(summaries) == 1
        s = summaries[0]
        assert s.broker_id == "schwab"
        assert s.txn_count == 1
        assert s.position_count == 1
        assert s.connection.org_name == "Charles Schwab"

    def test_list_empty_when_no_investment_accounts(self, tmp_path: Path) -> None:
        from finstore.model import Account, Transaction
        from finstore.model import Connection as Conn
        storage = FilesystemStorage(root=tmp_path)
        cash_acct = Account(
            id="a1", name="Checking", currency="USD",
            balance=Decimal("0"), available_balance=None,
            balance_date=0, conn_id="bank", transactions=(),
        )
        storage.merge_chunk(TENANT, StorageChunk(
            accounts=(cash_acct,),
            connections=(Conn(conn_id="bank", org_name="Bank", org_id="bank"),),
        ))
        assert storage.list_investment_accounts(TENANT) == ()


class TestReadSecurities:
    def test_read_all_securities(self, tmp_path: Path) -> None:
        storage = FilesystemStorage(root=tmp_path)
        secs = [_make_security("A", "CUSIP", "AAPL"), _make_security("B", "CUSIP", "MSFT")]
        storage.merge_chunk(TENANT, _inv_chunk([_make_inv_account()], securities=secs))

        result = storage.read_securities(TENANT)
        assert len(result) == 2

    def test_read_securities_filtered(self, tmp_path: Path) -> None:
        storage = FilesystemStorage(root=tmp_path)
        secs = [_make_security("A", "CUSIP", "AAPL"), _make_security("B", "CUSIP", "MSFT")]
        storage.merge_chunk(TENANT, _inv_chunk([_make_inv_account()], securities=secs))

        result = storage.read_securities(TENANT, ids=(("CUSIP", "A"),))
        assert len(result) == 1
        assert result[0].ticker == "AAPL"

    def test_read_securities_returns_empty_when_no_file(self, tmp_path: Path) -> None:
        storage = FilesystemStorage(root=tmp_path)
        storage.merge_chunk(TENANT, _inv_chunk([_make_inv_account()]))
        assert storage.read_securities(TENANT) == ()


# ---------------------------------------------------------------------------
# Meta: investment-only store doesn't raise CacheEmptyError
# ---------------------------------------------------------------------------


class TestCacheMetaWithInvestmentOnly:
    def test_read_meta_investment_only(self, tmp_path: Path) -> None:
        storage = FilesystemStorage(root=tmp_path)
        storage.merge_chunk(TENANT, _inv_chunk([_make_inv_account()]))
        meta = storage.read_meta(TENANT)
        assert meta.accounts == {}
        assert len(meta.investment_accounts) == 1

    def test_read_meta_empty_raises(self, tmp_path: Path) -> None:
        storage = FilesystemStorage(root=tmp_path)
        _atomic_write_json(tmp_path / "meta.json", {
            "schema_version": 5,
            "last_fetch_at": 0,
            "connections": [],
            "accounts": {},
            "investment_accounts": {},
        })
        with pytest.raises(CacheEmptyError):
            storage.read_meta(TENANT)


# ---------------------------------------------------------------------------
# Schema version mismatch
# ---------------------------------------------------------------------------


class TestSchemaVersion:
    def test_v4_meta_raises_mismatch(self, tmp_path: Path) -> None:
        storage = FilesystemStorage(root=tmp_path)
        _atomic_write_json(tmp_path / "meta.json", {
            "schema_version": 4,
            "last_fetch_at": 0,
            "connections": [],
            "accounts": {"some-account": {
                "conn_id": "x", "sfin_id": "x",
                "last_fetch_at": 0, "txn_count": 0,
                "earliest_posted": None, "latest_posted": None,
            }},
        })
        with pytest.raises(CacheSchemaMismatchError):
            storage.read_meta(TENANT)


# ---------------------------------------------------------------------------
# account_type persistence and heuristic fallback
# ---------------------------------------------------------------------------


class TestAccountTypePersistence:
    def test_infer_account_type_credit(self) -> None:
        assert infer_account_type("Platinum Visa Credit Card") == "CREDITCARD"
        assert infer_account_type("credit union checking") == "CREDITCARD"

    def test_infer_account_type_money_market(self) -> None:
        assert infer_account_type("Money Market Savings") == "MONEYMRKT"
        assert infer_account_type("moneymrkt") == "MONEYMRKT"

    def test_infer_account_type_default_checking(self) -> None:
        assert infer_account_type("Checking 1234") == "CHECKING"
        assert infer_account_type("Savings Account") == "CHECKING"

    def test_account_type_written_to_json(self, tmp_path: Path) -> None:
        from finstore.model import Account
        storage = FilesystemStorage(root=tmp_path)
        acct = Account(
            id="a1", name="Visa Gold", currency="USD",
            balance=Decimal("-200"), available_balance=None,
            balance_date=0, conn_id="bank", transactions=(),
            account_type=AccountType.CREDITCARD,
        )
        storage.merge_chunk(TENANT, StorageChunk(
            accounts=(acct,),
            connections=(Connection(conn_id="bank", org_name="Bank", org_id="bank"),),
        ))
        display_id = sanitize_account_name("Visa Gold")
        data = json.loads(
            (tmp_path / "accounts" / normalize_conn_id("bank") / f"{display_id}.json")
            .read_text()
        )
        assert data["account_type"] == "CREDITCARD"

    def test_v4_file_without_account_type_uses_heuristic(self, tmp_path: Path) -> None:
        storage = FilesystemStorage(root=tmp_path)
        acct_name = "Platinum Credit Card"
        display_id = sanitize_account_name(acct_name)
        acct_dir = tmp_path / "accounts" / normalize_conn_id("bank")
        acct_dir.mkdir(parents=True)
        _atomic_write_json(acct_dir / f"{display_id}.json", {
            "id": "a1", "name": acct_name, "currency": "USD",
            "balance": "0", "available-balance": None, "balance-date": 0,
            "conn_id": "bank", "transactions": [],
        })
        _atomic_write_json(tmp_path / "meta.json", {
            "schema_version": 5,
            "last_fetch_at": 0,
            "connections": [{"conn_id": "bank", "org_name": "Bank", "org_id": "bank",
                              "org_domain": "", "sfin_url": "", "org_url": ""}],
            "accounts": {display_id: {
                "conn_id": "bank", "sfin_id": "a1",
                "last_fetch_at": 0, "txn_count": 0,
                "earliest_posted": None, "latest_posted": None,
            }},
            "investment_accounts": {},
        })

        summaries = storage.list_accounts(TENANT)
        assert summaries[0].account_type == AccountType.CREDITCARD
