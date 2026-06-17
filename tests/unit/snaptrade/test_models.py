"""Tests for St* decode helpers in finstore.backends.snaptrade.models."""
from __future__ import annotations

from decimal import Decimal

from finstore.backends.snaptrade.models import (
    _decode_account,
    _decode_activity,
    _decode_balance,
    _decode_brokerage_authorization,
    _decode_position,
    _decode_symbol,
)


class TestDecodeSymbol:
    def test_full_symbol(self) -> None:
        data = {
            "id": "sym-1",
            "symbol": "AAPL",
            "description": "Apple Inc.",
            "figi_code": "BBG000B9XRY4",
            "cusip": "037833100",
            "isin": "US0378331005",
            "currency": {"id": "cur-1", "code": "USD"},
        }
        sym = _decode_symbol(data)
        assert sym is not None
        assert sym.symbol == "AAPL"
        assert sym.figi_code == "BBG000B9XRY4"
        assert sym.cusip == "037833100"
        assert sym.isin == "US0378331005"
        assert sym.currency is not None
        assert sym.currency.code == "USD"

    def test_minimal_symbol(self) -> None:
        sym = _decode_symbol({"id": "x", "symbol": "VTI"})
        assert sym is not None
        assert sym.symbol == "VTI"
        assert sym.figi_code is None
        assert sym.cusip is None

    def test_none_returns_none(self) -> None:
        assert _decode_symbol(None) is None

    def test_empty_string_fields_become_none(self) -> None:
        sym = _decode_symbol({"id": "x", "symbol": "VTI", "figi_code": "", "cusip": ""})
        assert sym is not None
        assert sym.figi_code is None
        assert sym.cusip is None


class TestDecodeBrokerageAuthorization:
    def test_full(self) -> None:
        data = {
            "id": "auth-1",
            "brokerage": {"id": "br-1", "name": "Charles Schwab", "slug": "SCHWAB"},
        }
        auth = _decode_brokerage_authorization(data)
        assert auth.id == "auth-1"
        assert auth.brokerage.slug == "SCHWAB"
        assert auth.brokerage.name == "Charles Schwab"


class TestDecodeAccount:
    def test_full_account(self) -> None:
        data = {
            "id": "acct-1",
            "name": "Margin Account",
            "number": "Q654213",
            "institution_name": "Alpaca",
            "brokerage_authorization": "auth-1",
            "meta": {"institution_name": "Schwab"},
        }
        acct = _decode_account(data)
        assert acct.id == "acct-1"
        assert acct.name == "Margin Account"
        assert acct.brokerage_authorization_id == "auth-1"
        assert acct.institution_name == "Schwab"  # meta takes precedence

    def test_institution_name_fallback(self) -> None:
        data = {
            "id": "acct-1",
            "name": "Acct",
            "number": "",
            "institution_name": "Vanguard",
            "brokerage_authorization": "auth-1",
        }
        acct = _decode_account(data)
        assert acct.institution_name == "Vanguard"


class TestDecodeBalance:
    def test_usd_balance(self) -> None:
        data = {
            "currency": {"id": "cur-1", "code": "USD"},
            "cash": 500.0,
            "buying_power": 1000.0,
            "total_equity": 5000.0,
        }
        bal = _decode_balance("acct-1", data)
        assert bal.account_id == "acct-1"
        assert bal.cash == Decimal("500.0")
        assert bal.buying_power == Decimal("1000.0")
        assert bal.currency == "USD"

    def test_null_values_become_none(self) -> None:
        bal = _decode_balance("a", {"currency": {"code": "CAD"}})
        assert bal.cash is None
        assert bal.buying_power is None


class TestDecodePosition:
    def test_full_position(self) -> None:
        data = {
            "symbol": {
                "id": "sym-1", "symbol": "AAPL",
                "figi_code": "BBG000B9XRY4", "cusip": "037833100",
                "currency": {"id": "c", "code": "USD"},
            },
            "units": 10.0,
            "price": 175.0,
            "market_value": 1750.0,
            "average_purchase_price": 150.0,
        }
        pos = _decode_position("acct-1", data)
        assert pos.units == Decimal("10.0")
        assert pos.price == Decimal("175.0")
        assert pos.average_purchase_price == Decimal("150.0")
        assert pos.symbol is not None
        assert pos.symbol.cusip == "037833100"

    def test_null_price_becomes_none(self) -> None:
        data = {"symbol": {"id": "s", "symbol": "VTI"}, "units": 5.0}
        pos = _decode_position("acct-1", data)
        assert pos.price is None
        assert pos.market_value is None


class TestDecodeActivity:
    def test_buy_activity(self) -> None:
        data = {
            "id": "act-1",
            "account": {"id": "acct-1"},
            "type": "BUY",
            "trade_date": "2024-01-12",
            "settlement_date": "2024-01-15",
            "symbol": {"id": "s", "symbol": "AAPL", "figi_code": "BBG000B9XRY4"},
            "units": 10.0,
            "price": 175.0,
            "amount": -1750.0,
            "fee": 0.0,
            "currency": "USD",
            "description": "BUY 10 AAPL",
        }
        act = _decode_activity(data)
        assert act.id == "act-1"
        assert act.account_id == "acct-1"
        assert act.action_type == "BUY"
        assert act.trade_date == "2024-01-12"
        assert act.settlement_date == "2024-01-15"
        assert act.units == Decimal("10.0")
        assert act.price == Decimal("175.0")
        assert act.amount == Decimal("-1750.0")
        assert act.fee == Decimal("0.0")
        assert act.symbol is not None
        assert act.symbol.symbol == "AAPL"

    def test_contribution_no_symbol(self) -> None:
        data = {
            "id": "act-2",
            "account": {"id": "acct-1"},
            "type": "CONTRIBUTION",
            "trade_date": "2024-01-01",
            "amount": 5000.0,
            "currency": "USD",
            "description": "Cash deposit",
        }
        act = _decode_activity(data)
        assert act.action_type == "CONTRIBUTION"
        assert act.symbol is None
        assert act.amount == Decimal("5000.0")
