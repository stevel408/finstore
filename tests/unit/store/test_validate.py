"""Tests for finstore.storage.validate."""
import json
from pathlib import Path

from finstore.storage.validate import (
    EXPECTED_SCHEMA_VERSION,
    validate_account_file,
    validate_cache,
    validate_investment_account_file,
    validate_positions_file,
    validate_securities_file,
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


# ---------------------------------------------------------------------------
# Schema version constant
# ---------------------------------------------------------------------------

def test_expected_schema_version_is_5() -> None:
    assert EXPECTED_SCHEMA_VERSION == 5


# ---------------------------------------------------------------------------
# Investment account validation
# ---------------------------------------------------------------------------

_BASE_INV_ACCT = {
    "id": "inv-001",
    "name": "Schwab Brokerage",
    "broker_id": "schwab",
    "conn_id": "schwab",
    "currency": "USD",
    "balance_date": 1700000000,
    "investment_transactions": [],
}

_BASE_INV_TXN = {
    "id": "itxn-001",
    "trade_date": 1700000000,
    "trntype": "BUY",
    "total": "-1750.00",
    "currency": "USD",
    "description": "Buy AAPL",
    "memo": "",
}


def _seed_inv_account(tmp_path: Path, data: dict, conn_id: str = "schwab") -> Path:
    conn_dir = tmp_path / "investment" / conn_id
    conn_dir.mkdir(parents=True, exist_ok=True)
    path = conn_dir / "schwab-brokerage.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


class TestInvestmentAccountValidation:
    def test_clean_investment_account_no_violations(self, tmp_path):
        path = _seed_inv_account(tmp_path, {**_BASE_INV_ACCT})
        assert validate_investment_account_file(path, "schwab") == []

    def test_missing_id_flagged(self, tmp_path):
        path = _seed_inv_account(tmp_path, {**_BASE_INV_ACCT, "id": ""})
        viols = validate_investment_account_file(path, "schwab")
        assert any("id" in v.rule for v in viols)

    def test_missing_broker_id_flagged(self, tmp_path):
        path = _seed_inv_account(tmp_path, {**_BASE_INV_ACCT, "broker_id": ""})
        viols = validate_investment_account_file(path, "schwab")
        assert any("broker_id" in v.rule for v in viols)

    def test_transactions_not_list_flagged(self, tmp_path):
        path = _seed_inv_account(tmp_path, {**_BASE_INV_ACCT, "investment_transactions": None})
        viols = validate_investment_account_file(path, "schwab")
        assert any(v.rule == "inv_acct_transactions_is_list" for v in viols)

    def test_txn_missing_id_flagged(self, tmp_path):
        txn = {**_BASE_INV_TXN, "id": ""}
        path = _seed_inv_account(tmp_path, {**_BASE_INV_ACCT, "investment_transactions": [txn]})
        viols = validate_investment_account_file(path, "schwab")
        assert any(v.rule == "inv_txn_id_nonempty" for v in viols)

    def test_txn_missing_trntype_flagged(self, tmp_path):
        txn = {**_BASE_INV_TXN, "trntype": ""}
        path = _seed_inv_account(tmp_path, {**_BASE_INV_ACCT, "investment_transactions": [txn]})
        viols = validate_investment_account_file(path, "schwab")
        assert any(v.rule == "inv_txn_trntype_nonempty" for v in viols)

    def test_txn_trade_date_not_int_flagged(self, tmp_path):
        txn = {**_BASE_INV_TXN, "trade_date": "2024-01-12"}
        path = _seed_inv_account(tmp_path, {**_BASE_INV_ACCT, "investment_transactions": [txn]})
        viols = validate_investment_account_file(path, "schwab")
        assert any(v.rule == "inv_txn_trade_date_int" for v in viols)

    def test_duplicate_txn_ids_flagged(self, tmp_path):
        txns = [_BASE_INV_TXN, {**_BASE_INV_TXN}]
        path = _seed_inv_account(tmp_path, {**_BASE_INV_ACCT, "investment_transactions": txns})
        viols = validate_investment_account_file(path, "schwab")
        assert any(v.rule == "inv_txn_ids_unique" for v in viols)

    def test_corrupt_json_reported(self, tmp_path):
        conn_dir = tmp_path / "investment" / "schwab"
        conn_dir.mkdir(parents=True)
        path = conn_dir / "bad.json"
        path.write_text("{invalid", encoding="utf-8")
        viols = validate_investment_account_file(path, "schwab")
        assert any(v.rule == "json_parse" for v in viols)


class TestPositionsValidation:
    def test_clean_positions_no_violations(self, tmp_path):
        path = tmp_path / "schwab-brokerage.positions.json"
        path.write_text(json.dumps({"positions": [
            {"security_id": "037833100", "security_id_type": "CUSIP",
             "units": "10", "unit_price": "175.00", "market_value": "1750.00",
             "held_in_acct": "CASH", "pos_type": "LONG", "snapshot_date": 1700000000}
        ]}), encoding="utf-8")
        assert validate_positions_file(path, "schwab", "schwab-brokerage") == []

    def test_positions_not_list_flagged(self, tmp_path):
        path = tmp_path / "x.positions.json"
        path.write_text(json.dumps({"positions": "oops"}), encoding="utf-8")
        viols = validate_positions_file(path, "schwab", "acct")
        assert any(v.rule == "positions_is_list" for v in viols)

    def test_position_missing_security_id_flagged(self, tmp_path):
        path = tmp_path / "x.positions.json"
        path.write_text(json.dumps({"positions": [{"security_id": "", "security_id_type": "CUSIP"}]}),
                        encoding="utf-8")
        viols = validate_positions_file(path, "schwab", "acct")
        assert any(v.rule == "pos_security_id_nonempty" for v in viols)


class TestSecuritiesValidation:
    def test_clean_securities_no_violations(self, tmp_path):
        path = tmp_path / "securities.json"
        path.write_text(json.dumps({"securities": [
            {"uniqueid": "037833100", "uniqueid_type": "CUSIP",
             "name": "Apple Inc.", "ticker": "AAPL", "security_type": "STOCK"}
        ]}), encoding="utf-8")
        assert validate_securities_file(path) == []

    def test_securities_not_list_flagged(self, tmp_path):
        path = tmp_path / "securities.json"
        path.write_text(json.dumps({"securities": {}}), encoding="utf-8")
        viols = validate_securities_file(path)
        assert any(v.rule == "securities_is_list" for v in viols)

    def test_security_missing_uniqueid_flagged(self, tmp_path):
        path = tmp_path / "securities.json"
        path.write_text(json.dumps({"securities": [{"uniqueid": "", "uniqueid_type": "CUSIP"}]}),
                        encoding="utf-8")
        viols = validate_securities_file(path)
        assert any(v.rule == "sec_uniqueid_nonempty" for v in viols)

    def test_security_missing_uniqueid_type_flagged(self, tmp_path):
        path = tmp_path / "securities.json"
        path.write_text(json.dumps({"securities": [{"uniqueid": "X", "uniqueid_type": ""}]}),
                        encoding="utf-8")
        viols = validate_securities_file(path)
        assert any(v.rule == "sec_uniqueid_type_nonempty" for v in viols)


class TestValidateCacheInvestment:
    def test_validate_cache_includes_investment_subtree(self, tmp_path):
        conn_dir = tmp_path / "investment" / "schwab"
        conn_dir.mkdir(parents=True)
        (conn_dir / "acct.json").write_text(
            json.dumps({**_BASE_INV_ACCT, "broker_id": ""}), encoding="utf-8"
        )
        viols = validate_cache(tmp_path)
        assert any("broker_id" in v.rule for v in viols)

    def test_validate_cache_validates_positions_files(self, tmp_path):
        conn_dir = tmp_path / "investment" / "schwab"
        conn_dir.mkdir(parents=True)
        (conn_dir / "acct.positions.json").write_text(
            json.dumps({"positions": [{"security_id": "", "security_id_type": "CUSIP"}]}),
            encoding="utf-8",
        )
        viols = validate_cache(tmp_path)
        assert any(v.rule == "pos_security_id_nonempty" for v in viols)

    def test_validate_cache_validates_securities_json(self, tmp_path):
        (tmp_path / "securities.json").write_text(
            json.dumps({"securities": [{"uniqueid": "", "uniqueid_type": "CUSIP"}]}),
            encoding="utf-8",
        )
        viols = validate_cache(tmp_path)
        assert any(v.rule == "sec_uniqueid_nonempty" for v in viols)
