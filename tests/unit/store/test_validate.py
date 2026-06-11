"""Tests for finstore.storage.validate."""
import json
from pathlib import Path

from finstore.storage.validate import (
    validate_account_file,
    validate_cache,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_BASE_ACCT = {
    "id": "acct-001",
    "name": "Checking",
    "currency": "USD",
    "balance": "1000.00",
    "available-balance": "950.00",
    "balance-date": 1700000000,
    "conn_id": "testbank.example",
    "org": {},
    "transactions": [],
    "holdings": [],
}

_BASE_TXN = {
    "id": "txn-001",
    "posted": 1700000000,
    "amount": "-42.00",
    "description": "Coffee",
    "payee": "Starbucks",
    "memo": "",
    "transacted_at": None,
}


def _acct(**overrides) -> dict:
    return {**_BASE_ACCT, **overrides}


def _txn(**overrides) -> dict:
    return {**_BASE_TXN, **overrides}


def _seed_account_file(cache_dir: Path, acct: dict, conn_id: str = "bank.example") -> Path:
    conn_dir = cache_dir / "accounts" / conn_id
    conn_dir.mkdir(parents=True, exist_ok=True)
    path = conn_dir / "acct-001.json"
    path.write_text(json.dumps(acct), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Account rules
# ---------------------------------------------------------------------------

class TestAccountRules:
    def test_clean_account_has_no_violations(self, tmp_path):
        path = _seed_account_file(tmp_path, _acct())
        assert validate_account_file(path, "bank.example") == []

    def test_empty_id(self, tmp_path):
        path = _seed_account_file(tmp_path, _acct(id=""))
        viols = validate_account_file(path, "bank.example")
        assert any(v.rule == "acct_id_nonempty" for v in viols)

    def test_empty_name(self, tmp_path):
        path = _seed_account_file(tmp_path, _acct(name=""))
        viols = validate_account_file(path, "bank.example")
        assert any(v.rule == "acct_name_nonempty" for v in viols)

    def test_empty_currency_allowed(self, tmp_path):
        path = _seed_account_file(tmp_path, _acct(currency=""))
        viols = validate_account_file(path, "bank.example")
        assert not any(v.rule == "acct_currency_iso" for v in viols)

    def test_lowercase_currency(self, tmp_path):
        path = _seed_account_file(tmp_path, _acct(currency="usd"))
        viols = validate_account_file(path, "bank.example")
        assert any(v.rule == "acct_currency_iso" for v in viols)

    def test_invalid_balance(self, tmp_path):
        path = _seed_account_file(tmp_path, _acct(balance="not-a-number"))
        viols = validate_account_file(path, "bank.example")
        assert any(v.rule == "acct_balance_decimal" for v in viols)

    def test_balance_missing_cents(self, tmp_path):
        path = _seed_account_file(tmp_path, _acct(balance="1000"))
        viols = validate_account_file(path, "bank.example")
        assert any(v.rule == "acct_balance_decimal" for v in viols)

    def test_available_balance_null_ok(self, tmp_path):
        path = _seed_account_file(tmp_path, _acct(**{"available-balance": None}))
        assert validate_account_file(path, "bank.example") == []

    def test_available_balance_invalid(self, tmp_path):
        path = _seed_account_file(tmp_path, _acct(**{"available-balance": "bad"}))
        viols = validate_account_file(path, "bank.example")
        assert any(v.rule == "acct_available_balance_decimal" for v in viols)

    def test_balance_date_out_of_range(self, tmp_path):
        path = _seed_account_file(tmp_path, _acct(**{"balance-date": 1}))
        viols = validate_account_file(path, "bank.example")
        assert any(v.rule == "acct_balance_date_epoch" for v in viols)

    def test_balance_date_not_integer(self, tmp_path):
        path = _seed_account_file(tmp_path, _acct(**{"balance-date": "2026-01-01"}))
        viols = validate_account_file(path, "bank.example")
        assert any(v.rule == "acct_balance_date_epoch" for v in viols)

    def test_missing_conn_id(self, tmp_path):
        path = _seed_account_file(tmp_path, _acct(conn_id=""))
        viols = validate_account_file(path, "bank.example")
        assert any(v.rule == "acct_conn_id_nonempty" for v in viols)


# ---------------------------------------------------------------------------
# Transaction rules
# ---------------------------------------------------------------------------

class TestTransactionRules:
    def _file_with_txn(self, tmp_path, txn_override: dict) -> Path:
        return _seed_account_file(
            tmp_path, _acct(transactions=[_txn(**txn_override)])
        )

    def test_clean_transaction_no_violations(self, tmp_path):
        path = _seed_account_file(tmp_path, _acct(transactions=[_txn()]))
        assert validate_account_file(path, "bank.example") == []

    def test_zero_amount_ok(self, tmp_path):
        path = self._file_with_txn(tmp_path, {"amount": "0.00"})
        assert validate_account_file(path, "bank.example") == []

    def test_positive_amount_ok(self, tmp_path):
        path = self._file_with_txn(tmp_path, {"amount": "1200.00"})
        assert validate_account_file(path, "bank.example") == []

    def test_amount_bad_format(self, tmp_path):
        path = self._file_with_txn(tmp_path, {"amount": "42"})
        viols = validate_account_file(path, "bank.example")
        assert any(v.rule == "txn_amount_decimal" for v in viols)

    def test_amount_three_decimals_rejected(self, tmp_path):
        path = self._file_with_txn(tmp_path, {"amount": "-1.234"})
        viols = validate_account_file(path, "bank.example")
        assert any(v.rule == "txn_amount_decimal" for v in viols)

    def test_posted_out_of_range(self, tmp_path):
        path = self._file_with_txn(tmp_path, {"posted": 1})
        viols = validate_account_file(path, "bank.example")
        assert any(v.rule == "txn_posted_epoch" for v in viols)

    def test_posted_not_integer(self, tmp_path):
        path = self._file_with_txn(tmp_path, {"posted": "2026-01-01"})
        viols = validate_account_file(path, "bank.example")
        assert any(v.rule == "txn_posted_epoch" for v in viols)

    def test_transacted_at_null_ok(self, tmp_path):
        path = self._file_with_txn(tmp_path, {"transacted_at": None})
        assert validate_account_file(path, "bank.example") == []

    def test_transacted_at_out_of_range(self, tmp_path):
        path = self._file_with_txn(tmp_path, {"transacted_at": 1})
        viols = validate_account_file(path, "bank.example")
        assert any(v.rule == "txn_transacted_at_epoch" for v in viols)

    def test_duplicate_txn_ids(self, tmp_path):
        txns = [_txn(id="dup-id"), _txn(id="dup-id")]
        path = _seed_account_file(tmp_path, _acct(transactions=txns))
        viols = validate_account_file(path, "bank.example")
        assert any(v.rule == "txn_ids_unique_within_account" for v in viols)

    def test_violation_carries_txn_id(self, tmp_path):
        path = self._file_with_txn(tmp_path, {"amount": "bad"})
        viols = validate_account_file(path, "bank.example")
        txn_viols = [v for v in viols if v.rule == "txn_amount_decimal"]
        assert txn_viols[0].txn_id == "txn-001"


# ---------------------------------------------------------------------------
# validate_cache integration
# ---------------------------------------------------------------------------

class TestValidateCache:
    def test_empty_cache_dir_returns_no_violations(self, tmp_path):
        assert validate_cache(tmp_path) == []

    def test_missing_accounts_dir_returns_no_violations(self, tmp_path):
        assert validate_cache(tmp_path) == []

    def test_clean_cache_returns_no_violations(self, tmp_path):
        _seed_account_file(tmp_path, _acct())
        assert validate_cache(tmp_path) == []

    def test_violations_across_multiple_files(self, tmp_path):
        _seed_account_file(tmp_path, _acct(id="a1", currency="usd"), "bank-a")
        _seed_account_file(tmp_path, _acct(id="a2", currency="usd"), "bank-b")
        viols = validate_cache(tmp_path)
        assert len(viols) == 2
        conn_ids = {v.conn_id for v in viols}
        assert conn_ids == {"bank-a", "bank-b"}

    def test_corrupt_json_reported_as_violation(self, tmp_path):
        conn_dir = tmp_path / "accounts" / "bank.example"
        conn_dir.mkdir(parents=True)
        (conn_dir / "bad.json").write_text("{invalid json", encoding="utf-8")
        viols = validate_cache(tmp_path)
        assert any(v.rule == "json_parse" for v in viols)
