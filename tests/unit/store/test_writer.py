"""Tests for FilesystemStorage.merge_chunk (was gateway.store.writer.Writer)."""
import json
import stat
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from finstore.model import Account, Connection, StorageChunk, Transaction
from finstore.storage.filesystem import FilesystemStorage, _atomic_write_json
from finstore.storage.paths import normalize_conn_id, sanitize_account_name

TENANT = "local"
CONN_A = Connection(conn_id="conn-a", org_name="Bank A", org_id="org-a")
CONN_B = Connection(conn_id="conn-b", org_name="Bank B", org_id="org-b")


def _make_txn(txn_id: str, posted: int, amount: str = "10.00") -> Transaction:
    return Transaction(
        id=txn_id,
        posted=posted,
        amount=Decimal(amount),
        description="Test transaction",
        payee="Payee",
        memo="",
        transacted_at=None,
    )


def _make_account(
    acctid: str = "acct-001",
    name: str = "Checking",
    conn_id: str = "conn-a",
    balance: str = "1000.00",
    available_balance: str | None = "950.00",
    balance_date: int = 1700000000,
    txns: list[Transaction] | None = None,
) -> Account:
    return Account(
        id=acctid,
        name=name,
        currency="USD",
        balance=Decimal(balance),
        available_balance=Decimal(available_balance) if available_balance is not None else None,
        balance_date=balance_date,
        conn_id=conn_id,
        transactions=tuple(txns or []),
    )


def _make_chunk(
    accounts: list[Account],
    connections: list[Connection] | None = None,
) -> StorageChunk:
    if connections is None:
        conn_ids = {a.conn_id for a in accounts}
        connections = [Connection(conn_id=cid, org_name="Bank", org_id=cid) for cid in conn_ids]
    return StorageChunk(
        accounts=tuple(accounts),
        connections=tuple(connections),
    )


class TestMergeChunkFresh:
    def test_creates_accounts_dir(self, tmp_path):
        storage = FilesystemStorage(root=tmp_path)
        chunk = _make_chunk([_make_account()])
        storage.merge_chunk(TENANT, chunk)
        assert (tmp_path / "accounts").is_dir()

    def test_writes_account_file(self, tmp_path):
        storage = FilesystemStorage(root=tmp_path)
        acct = _make_account(
            acctid="acct-001", name="Checking", txns=[_make_txn("t1", 1700000001)]
        )
        storage.merge_chunk(TENANT, _make_chunk([acct]))

        display_id = sanitize_account_name("Checking")
        account_path = tmp_path / "accounts" / normalize_conn_id("conn-a") / f"{display_id}.json"
        assert account_path.exists()
        data = json.loads(account_path.read_text())
        assert data["id"] == "acct-001"
        assert len(data["transactions"]) == 1
        assert data["transactions"][0]["id"] == "t1"

    def test_writes_meta_json(self, tmp_path):
        storage = FilesystemStorage(root=tmp_path)
        storage.merge_chunk(TENANT, _make_chunk([_make_account(name="Checking")]))

        meta_path = tmp_path / "meta.json"
        assert meta_path.exists()
        meta = json.loads(meta_path.read_text())
        assert meta["schema_version"] == 5
        assert "Checking" in meta["accounts"]

    def test_merge_stats_fresh(self, tmp_path):
        storage = FilesystemStorage(root=tmp_path)
        txns = [_make_txn(f"t{i}", 1700000000 + i) for i in range(3)]
        stats = storage.merge_chunk(TENANT, _make_chunk([_make_account(txns=txns)]))

        assert stats.accounts_seen == 1
        assert stats.txns_new == 3
        assert stats.txns_duplicate == 0


class TestAccountFileMode:
    def test_account_file_mode_0o600(self, tmp_path):
        storage = FilesystemStorage(root=tmp_path)
        storage.merge_chunk(TENANT, _make_chunk([_make_account(name="Checking")]))

        display_id = sanitize_account_name("Checking")
        account_path = tmp_path / "accounts" / normalize_conn_id("conn-a") / f"{display_id}.json"
        assert stat.S_IMODE(account_path.stat().st_mode) == 0o600

    def test_meta_file_mode_0o600(self, tmp_path):
        storage = FilesystemStorage(root=tmp_path)
        storage.merge_chunk(TENANT, _make_chunk([_make_account()]))
        meta_path = tmp_path / "meta.json"
        assert stat.S_IMODE(meta_path.stat().st_mode) == 0o600


class TestTransactionDedup:
    def test_overlapping_txns_deduped(self, tmp_path):
        storage = FilesystemStorage(root=tmp_path)

        txns_first = [_make_txn("t1", 1700000001), _make_txn("t2", 1700000002)]
        stats1 = storage.merge_chunk(TENANT, _make_chunk([_make_account(txns=txns_first)]))
        assert stats1.txns_new == 2
        assert stats1.txns_duplicate == 0

        txns_second = [_make_txn("t2", 1700000002), _make_txn("t3", 1700000003)]
        stats2 = storage.merge_chunk(TENANT, _make_chunk([_make_account(txns=txns_second)]))
        assert stats2.txns_new == 1
        assert stats2.txns_duplicate == 1

        display_id = sanitize_account_name("Checking")
        account_path = tmp_path / "accounts" / normalize_conn_id("conn-a") / f"{display_id}.json"
        data = json.loads(account_path.read_text())
        assert len(data["transactions"]) == 3
        assert {t["id"] for t in data["transactions"]} == {"t1", "t2", "t3"}

    def test_fully_duplicate_chunk(self, tmp_path):
        storage = FilesystemStorage(root=tmp_path)
        txns = [_make_txn("t1", 1700000001), _make_txn("t2", 1700000002)]
        chunk = _make_chunk([_make_account(txns=txns)])
        storage.merge_chunk(TENANT, chunk)
        stats = storage.merge_chunk(TENANT, chunk)
        assert stats.txns_new == 0
        assert stats.txns_duplicate == 2

        display_id = sanitize_account_name("Checking")
        account_path = tmp_path / "accounts" / normalize_conn_id("conn-a") / f"{display_id}.json"
        data = json.loads(account_path.read_text())
        assert len(data["transactions"]) == 2


class TestLegacyFieldCleanup:
    """Pre-Step-2 caches wrote `org` and `holdings` keys to account files.
    The §11.a decision dropped those from the public Account; a subsequent
    merge must strip them from existing files rather than carry them forward.
    """

    def test_existing_org_and_holdings_keys_removed_on_remerge(self, tmp_path):
        storage = FilesystemStorage(root=tmp_path)
        display_id = sanitize_account_name("Checking")
        account_path = tmp_path / "accounts" / normalize_conn_id("conn-a") / f"{display_id}.json"
        account_path.parent.mkdir(parents=True)

        # Simulate a v3-era on-disk file: includes legacy keys.
        _atomic_write_json(account_path, {
            "id": "acct-001",
            "name": "Checking",
            "currency": "USD",
            "balance": "100.00",
            "available-balance": None,
            "balance-date": 1700000000,
            "conn_id": "conn-a",
            "transactions": [],
            "org": {"sfin-id": "old", "name": "Old Bank"},
            "holdings": [{"sym": "VTI"}],
        })

        storage.merge_chunk(
            TENANT, _make_chunk([_make_account(txns=[_make_txn("t1", 1700000001)])])
        )

        data = json.loads(account_path.read_text())
        assert "org" not in data
        assert "holdings" not in data


class TestBalanceSnapshotUpdate:
    def test_balance_fields_updated_on_merge(self, tmp_path):
        storage = FilesystemStorage(root=tmp_path)

        storage.merge_chunk(TENANT, _make_chunk([
            _make_account(balance="1000.00", available_balance="900.00", balance_date=1700000000)
        ]))
        storage.merge_chunk(TENANT, _make_chunk([
            _make_account(balance="1200.00", available_balance="1100.00", balance_date=1700100000)
        ]))

        display_id = sanitize_account_name("Checking")
        account_path = tmp_path / "accounts" / normalize_conn_id("conn-a") / f"{display_id}.json"
        data = json.loads(account_path.read_text())
        assert data["balance"] == "1200.00"
        assert data["available-balance"] == "1100.00"
        assert data["balance-date"] == 1700100000

    def test_available_balance_none_handled(self, tmp_path):
        storage = FilesystemStorage(root=tmp_path)
        storage.merge_chunk(TENANT, _make_chunk([_make_account(available_balance="500.00")]))
        storage.merge_chunk(TENANT, _make_chunk([
            _make_account(balance="1500.00", available_balance=None)
        ]))

        display_id = sanitize_account_name("Checking")
        account_path = tmp_path / "accounts" / normalize_conn_id("conn-a") / f"{display_id}.json"
        data = json.loads(account_path.read_text())
        assert data["balance"] == "1500.00"
        assert data["available-balance"] is None


class TestMetaWrittenAfterAccounts:
    def test_meta_written_last(self, tmp_path):
        storage = FilesystemStorage(root=tmp_path)
        chunk = _make_chunk([_make_account(acctid="acct-order")])

        write_calls: list[Path] = []
        original_write = _atomic_write_json

        def tracking_write(path: Path, obj: dict) -> None:
            write_calls.append(path)
            original_write(path, obj)

        with patch(
            "finstore.storage.filesystem._atomic_write_json",
            side_effect=tracking_write,
        ):
            storage.merge_chunk(TENANT, chunk)

        assert len(write_calls) >= 2
        assert write_calls[-1].name == "meta.json"
        account_writes = [p for p in write_calls if p.name != "meta.json"]
        assert len(account_writes) >= 1

    def test_meta_contains_connection_info(self, tmp_path):
        storage = FilesystemStorage(root=tmp_path)
        storage.merge_chunk(
            TENANT,
            _make_chunk([_make_account(conn_id="conn-a")], connections=[CONN_A]),
        )

        meta = json.loads((tmp_path / "meta.json").read_text())
        conns = {c["conn_id"]: c for c in meta["connections"]}
        assert "conn-a" in conns
        assert conns["conn-a"]["org_name"] == "Bank A"

    def test_meta_txn_counts_accurate(self, tmp_path):
        storage = FilesystemStorage(root=tmp_path)
        txns = [_make_txn(f"t{i}", 1700000000 + i) for i in range(5)]
        storage.merge_chunk(TENANT, _make_chunk([
            _make_account(acctid="acct-cnt", name="Checking", txns=txns)
        ]))

        meta = json.loads((tmp_path / "meta.json").read_text())
        acct_meta = meta["accounts"]["Checking"]
        assert acct_meta["txn_count"] == 5
        assert acct_meta["earliest_posted"] == 1700000000
        assert acct_meta["latest_posted"] == 1700000004
