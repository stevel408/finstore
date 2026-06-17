"""Phase 0 model tests — investment types and extensions to existing types."""
from __future__ import annotations

import dataclasses
import pytest
from decimal import Decimal

from finstore.model import (
    Account,
    AccountSummary,
    AccountType,
    Connection,
    InvestmentAccount,
    InvestmentTransaction,
    Position,
    Security,
    StorageChunk,
    Transaction,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_CONN = Connection(conn_id="schwab", org_name="Schwab", org_id="schwab")

_SECURITY = Security(
    uniqueid="037833100",
    uniqueid_type="CUSIP",
    name="Apple Inc.",
    ticker="AAPL",
    security_type="STOCK",
)

_POSITION = Position(
    security_id="037833100",
    security_id_type="CUSIP",
    units=Decimal("10"),
    unit_price=Decimal("175.00"),
    market_value=Decimal("1750.00"),
    cost_basis=Decimal("1500.00"),
    held_in_acct="CASH",
    pos_type="LONG",
    snapshot_date=1_700_000_000,
)

_INV_TXN = InvestmentTransaction(
    id="txn-1",
    trade_date=1_700_000_000,
    settle_date=1_700_172_800,
    trntype="BUY",
    security_id="037833100",
    security_id_type="CUSIP",
    units=Decimal("10"),
    unit_price=Decimal("150.00"),
    commission=Decimal("0.00"),
    fees=None,
    taxes=None,
    total=Decimal("-1500.00"),
    income_type=None,
    description="Buy AAPL",
    memo="",
    currency="USD",
)

_INV_ACCOUNT = InvestmentAccount(
    id="acct-1",
    name="Schwab Brokerage",
    currency="USD",
    broker_id="schwab",
    available_cash=Decimal("500.00"),
    margin_balance=None,
    balance_date=1_700_000_000,
    conn_id="schwab",
    positions=(_POSITION,),
    investment_transactions=(_INV_TXN,),
)


# ---------------------------------------------------------------------------
# AccountType
# ---------------------------------------------------------------------------


def test_account_type_values() -> None:
    assert AccountType.CHECKING.value == "CHECKING"
    assert AccountType.CREDITCARD.value == "CREDITCARD"
    assert AccountType.INVESTMENT.value == "INVESTMENT"


def test_account_type_is_str() -> None:
    assert isinstance(AccountType.SAVINGS, str)
    assert AccountType.SAVINGS == "SAVINGS"


# ---------------------------------------------------------------------------
# Account — account_type default
# ---------------------------------------------------------------------------


def test_account_default_type_is_checking() -> None:
    acct = Account(
        id="a1",
        name="Checking 1234",
        currency="USD",
        balance=Decimal("100"),
        available_balance=None,
        balance_date=1_700_000_000,
        conn_id="bank",
        transactions=(),
    )
    assert acct.account_type is AccountType.CHECKING


def test_account_explicit_creditcard_type() -> None:
    acct = Account(
        id="a2",
        name="Visa Gold",
        currency="USD",
        balance=Decimal("-200"),
        available_balance=None,
        balance_date=1_700_000_000,
        conn_id="bank",
        transactions=(),
        account_type=AccountType.CREDITCARD,
    )
    assert acct.account_type is AccountType.CREDITCARD


def test_account_is_frozen() -> None:
    acct = Account(
        id="a1",
        name="x",
        currency="USD",
        balance=Decimal("0"),
        available_balance=None,
        balance_date=0,
        conn_id="c",
        transactions=(),
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        acct.name = "y"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# AccountSummary — account_type default
# ---------------------------------------------------------------------------


def test_account_summary_default_type_is_checking() -> None:
    stub = AccountSummary(
        acctid="checking-1234",
        name="Checking 1234",
        currency="USD",
        connection=_CONN,
        last_fetch_at=None,
        txn_count=0,
    )
    assert stub.account_type is AccountType.CHECKING


def test_account_summary_explicit_type() -> None:
    stub = AccountSummary(
        acctid="schwab-brokerage",
        name="Schwab Brokerage",
        currency="USD",
        connection=_CONN,
        last_fetch_at=1_700_000_000,
        txn_count=5,
        account_type=AccountType.INVESTMENT,
    )
    assert stub.account_type is AccountType.INVESTMENT


# ---------------------------------------------------------------------------
# Security
# ---------------------------------------------------------------------------


def test_security_fields() -> None:
    assert _SECURITY.uniqueid == "037833100"
    assert _SECURITY.uniqueid_type == "CUSIP"
    assert _SECURITY.ticker == "AAPL"
    assert _SECURITY.security_type == "STOCK"


def test_security_is_frozen() -> None:
    with pytest.raises(dataclasses.FrozenInstanceError):
        _SECURITY.name = "x"  # type: ignore[misc]


def test_security_ticker_as_uniqueid() -> None:
    s = Security(
        uniqueid="VTSAX",
        uniqueid_type="TICKER",
        name="Vanguard Total Stock Market Index Fund",
        ticker="VTSAX",
        security_type="MUTUALFUND",
    )
    assert s.uniqueid == s.ticker


# ---------------------------------------------------------------------------
# InvestmentTransaction
# ---------------------------------------------------------------------------


def test_inv_txn_buy_fields() -> None:
    assert _INV_TXN.trntype == "BUY"
    assert _INV_TXN.units == Decimal("10")
    assert _INV_TXN.total == Decimal("-1500.00")
    assert _INV_TXN.income_type is None
    assert _INV_TXN.fees is None


def test_inv_txn_income_with_income_type() -> None:
    div = InvestmentTransaction(
        id="txn-2",
        trade_date=1_700_100_000,
        settle_date=None,
        trntype="INCOME",
        security_id="037833100",
        security_id_type="CUSIP",
        units=None,
        unit_price=None,
        commission=None,
        fees=None,
        taxes=None,
        total=Decimal("25.00"),
        income_type="DIV",
        description="AAPL dividend",
        memo="",
        currency="USD",
    )
    assert div.trntype == "INCOME"
    assert div.income_type == "DIV"
    assert div.units is None


def test_inv_txn_contribution_no_security() -> None:
    contrib = InvestmentTransaction(
        id="txn-3",
        trade_date=1_700_200_000,
        settle_date=None,
        trntype="CONTRIBUTION",
        security_id=None,
        security_id_type=None,
        units=None,
        unit_price=None,
        commission=None,
        fees=None,
        taxes=None,
        total=Decimal("5000.00"),
        income_type=None,
        description="Cash contribution",
        memo="",
        currency="USD",
    )
    assert contrib.security_id is None
    assert contrib.security_id_type is None


def test_inv_txn_is_frozen() -> None:
    with pytest.raises(dataclasses.FrozenInstanceError):
        _INV_TXN.description = "x"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Position
# ---------------------------------------------------------------------------


def test_position_fields() -> None:
    assert _POSITION.units == Decimal("10")
    assert _POSITION.market_value == Decimal("1750.00")
    assert _POSITION.held_in_acct == "CASH"
    assert _POSITION.pos_type == "LONG"


def test_position_no_cost_basis() -> None:
    p = Position(
        security_id="VTSAX",
        security_id_type="TICKER",
        units=Decimal("50"),
        unit_price=Decimal("120.00"),
        market_value=Decimal("6000.00"),
        cost_basis=None,
        held_in_acct="CASH",
        pos_type="LONG",
        snapshot_date=1_700_000_000,
    )
    assert p.cost_basis is None


def test_position_is_frozen() -> None:
    with pytest.raises(dataclasses.FrozenInstanceError):
        _POSITION.units = Decimal("99")  # type: ignore[misc]


# ---------------------------------------------------------------------------
# InvestmentAccount
# ---------------------------------------------------------------------------


def test_investment_account_fields() -> None:
    assert _INV_ACCOUNT.broker_id == "schwab"
    assert len(_INV_ACCOUNT.positions) == 1
    assert len(_INV_ACCOUNT.investment_transactions) == 1
    assert _INV_ACCOUNT.available_cash == Decimal("500.00")
    assert _INV_ACCOUNT.margin_balance is None


def test_investment_account_empty_positions_and_txns() -> None:
    acct = InvestmentAccount(
        id="acct-empty",
        name="Empty Account",
        currency="USD",
        broker_id="vanguard",
        available_cash=None,
        margin_balance=None,
        balance_date=1_700_000_000,
        conn_id="vanguard",
        positions=(),
        investment_transactions=(),
    )
    assert acct.positions == ()
    assert acct.investment_transactions == ()


def test_investment_account_is_frozen() -> None:
    with pytest.raises(dataclasses.FrozenInstanceError):
        _INV_ACCOUNT.name = "x"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# StorageChunk — backward compat + investment fields
# ---------------------------------------------------------------------------


def test_storage_chunk_cash_only_still_works() -> None:
    """Existing SimpleFIN callers pass only accounts + connections."""
    chunk = StorageChunk(accounts=(), connections=(_CONN,))
    assert chunk.investment_accounts == ()
    assert chunk.securities == ()


def test_storage_chunk_with_investment_data() -> None:
    chunk = StorageChunk(
        accounts=(),
        connections=(_CONN,),
        investment_accounts=(_INV_ACCOUNT,),
        securities=(_SECURITY,),
    )
    assert len(chunk.investment_accounts) == 1
    assert len(chunk.securities) == 1


def test_storage_chunk_is_frozen() -> None:
    chunk = StorageChunk(accounts=(), connections=())
    with pytest.raises(dataclasses.FrozenInstanceError):
        chunk.accounts = (Account(  # type: ignore[misc]
            id="x", name="x", currency="USD",
            balance=Decimal("0"), available_balance=None,
            balance_date=0, conn_id="c", transactions=(),
        ),)
