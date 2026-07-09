"""Raw SnapTrade response shapes — the ``St*`` type family.

These dataclasses mirror the SnapTrade REST API JSON closely enough to parse
without loss, keeping only the fields the normalization seam actually uses.

**Import boundary (Rule 3b):** nothing outside
``finstore.backends.snaptrade.*`` may import this module.  The
``SnapTradeBackend`` in ``backend.py`` is the only place that converts
``St*`` types into neutral ``finstore.model`` types.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any


# ---------------------------------------------------------------------------
# Supporting shapes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class StCurrency:
    id: str
    code: str  # "USD", "CAD", etc.


@dataclass(frozen=True)
class StSymbol:
    """A tradable security as returned by SnapTrade.

    ``figi_code``, ``cusip``, and ``isin`` may all be None for non-standard
    instruments (e.g. crypto, foreign ETFs).  ``symbol`` (ticker) is always
    present as a last-resort identifier.
    """

    id: str
    symbol: str            # ticker
    description: str
    figi_code: str | None
    cusip: str | None
    isin: str | None
    currency: StCurrency | None


@dataclass(frozen=True)
class StBrokerage:
    id: str
    name: str          # display name, e.g. "Charles Schwab"
    slug: str          # stable identifier, e.g. "SCHWAB"


@dataclass(frozen=True)
class StBrokerageAuthorization:
    id: str
    brokerage: StBrokerage


# ---------------------------------------------------------------------------
# Primary entities
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class StAccount:
    id: str
    name: str
    number: str
    institution_name: str
    brokerage_authorization_id: str


@dataclass(frozen=True)
class StBalance:
    account_id: str
    cash: Decimal | None
    buying_power: Decimal | None
    total_value: Decimal | None
    currency: str


@dataclass(frozen=True)
class StPosition:
    account_id: str
    symbol: StSymbol | None
    units: Decimal
    price: Decimal | None
    market_value: Decimal | None
    average_purchase_price: Decimal | None
    currency: str


@dataclass(frozen=True)
class StActivity:
    """One transaction / activity record from SnapTrade.

    ``action_type`` is mapped from the JSON ``type`` field.
    ``amount`` is the net settlement amount (negative = debit, positive = credit).
    ``trade_date`` and ``settlement_date`` are "YYYY-MM-DD" strings or None.
    """

    id: str
    account_id: str | None
    trade_date: str | None       # "YYYY-MM-DD"
    settlement_date: str | None  # "YYYY-MM-DD"
    action_type: str             # raw SnapTrade type, e.g. "BUY", "DIV"
    units: Decimal | None
    price: Decimal | None
    amount: Decimal | None       # net settlement
    fee: Decimal | None
    currency: str
    description: str
    symbol: StSymbol | None


@dataclass(frozen=True)
class StOptionSymbol:
    """An options contract as returned by the orders endpoint."""

    id: str
    ticker: str                          # OCC ticker, e.g. "USO   260618P00120000"
    option_type: str                     # "CALL" or "PUT"
    strike_price: Decimal | None
    expiration_date: str | None          # "YYYY-MM-DD"
    underlying_symbol: StSymbol | None


@dataclass(frozen=True)
class StOrder:
    """One order record from the ``/accounts/{id}/orders`` endpoint.

    Only orders with ``status == "EXECUTED"`` represent completed transactions.
    Either ``symbol`` (for equities/ETFs) or ``option_symbol`` (for options)
    is set; never both.
    """

    id: str                              # brokerage_order_id
    account_id: str
    status: str                          # "EXECUTED", "CANCELLED", …
    action: str                          # "BUY" or "SELL"
    symbol: StSymbol | None              # equity / ETF
    option_symbol: StOptionSymbol | None # option contract
    filled_quantity: Decimal | None
    execution_price: Decimal | None
    time_executed: str | None            # ISO-8601 datetime
    time_placed: str | None              # ISO-8601 datetime
    currency: str


# ---------------------------------------------------------------------------
# Decode helpers
# ---------------------------------------------------------------------------


def _dec(value: Any) -> Decimal | None:
    """Parse a numeric JSON value to Decimal, or None."""
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except Exception:
        return None


def _decode_currency(data: dict[str, Any] | None) -> StCurrency | None:
    if not data:
        return None
    return StCurrency(
        id=data.get("id", ""),
        code=data.get("code") or data.get("iso_code") or "USD",
    )


def _decode_symbol(data: dict[str, Any] | None) -> StSymbol | None:
    if not data:
        return None
    return StSymbol(
        id=data.get("id", ""),
        symbol=data.get("symbol") or data.get("raw_symbol") or "",
        description=data.get("description") or "",
        figi_code=data.get("figi_code") or None,
        cusip=data.get("cusip") or None,
        isin=data.get("isin") or None,
        currency=_decode_currency(data.get("currency")),
    )


def _decode_brokerage(data: dict[str, Any]) -> StBrokerage:
    return StBrokerage(
        id=data.get("id", ""),
        name=data.get("name") or data.get("display_name") or "",
        slug=data.get("slug") or data.get("id") or "",
    )


def _decode_brokerage_authorization(data: dict[str, Any]) -> StBrokerageAuthorization:
    return StBrokerageAuthorization(
        id=data["id"],
        brokerage=_decode_brokerage(data.get("brokerage") or {}),
    )


def _decode_account(data: dict[str, Any]) -> StAccount:
    meta = data.get("meta") or {}
    return StAccount(
        id=data["id"],
        name=data.get("name") or "",
        number=data.get("number") or "",
        institution_name=(
            meta.get("institution_name")
            or data.get("institution_name")
            or ""
        ),
        brokerage_authorization_id=data.get("brokerage_authorization") or "",
    )


def _decode_balance(account_id: str, data: dict[str, Any]) -> StBalance:
    currency_raw = data.get("currency") or {}
    currency_code = (
        currency_raw.get("code") or currency_raw.get("iso_code")
        if isinstance(currency_raw, dict)
        else str(currency_raw)
    ) or "USD"
    return StBalance(
        account_id=account_id,
        cash=_dec(data.get("cash")),
        buying_power=_dec(data.get("buying_power")),
        total_value=_dec(data.get("total_equity") or data.get("total_value")),
        currency=currency_code,
    )


def _decode_position(account_id: str, data: dict[str, Any]) -> StPosition:
    sym_raw = data.get("symbol")
    # SnapTrade sometimes nests the symbol under a "symbol" key within the symbol object
    if isinstance(sym_raw, dict) and "symbol" in sym_raw and isinstance(sym_raw["symbol"], dict):
        sym_raw = sym_raw["symbol"]
    currency_raw = data.get("currency") or {}
    if isinstance(currency_raw, dict):
        currency = currency_raw.get("code") or "USD"
    else:
        currency = str(currency_raw) if currency_raw else "USD"
    return StPosition(
        account_id=account_id,
        symbol=_decode_symbol(sym_raw),
        units=_dec(data.get("units")) or Decimal("0"),
        price=_dec(data.get("price")),
        market_value=_dec(data.get("market_value")),
        average_purchase_price=_dec(data.get("average_purchase_price")),
        currency=currency,
    )


def _decode_activity(data: dict[str, Any]) -> StActivity:
    account_raw = data.get("account") or {}
    account_id = (
        account_raw.get("id") if isinstance(account_raw, dict) else str(account_raw)
    ) or None
    sym_raw = data.get("symbol")
    if isinstance(sym_raw, dict) and "symbol" in sym_raw and isinstance(sym_raw["symbol"], dict):
        sym_raw = sym_raw["symbol"]
    currency = data.get("currency") or "USD"
    if isinstance(currency, dict):
        currency = currency.get("code") or "USD"
    return StActivity(
        id=data.get("id") or "",
        account_id=account_id,
        trade_date=data.get("trade_date") or data.get("transaction_date"),
        settlement_date=data.get("settlement_date"),
        action_type=data.get("type") or data.get("action_type") or "OTHER",
        units=_dec(data.get("units")),
        price=_dec(data.get("price")),
        amount=_dec(data.get("amount")),
        fee=_dec(data.get("fee")),
        currency=str(currency),
        description=data.get("description") or "",
        symbol=_decode_symbol(sym_raw if isinstance(sym_raw, dict) else None),
    )


def _decode_option_symbol(data: dict[str, Any] | None) -> StOptionSymbol | None:
    if not data:
        return None
    return StOptionSymbol(
        id=data.get("id", ""),
        ticker=data.get("ticker") or "",
        option_type=data.get("option_type") or "",
        strike_price=_dec(data.get("strike_price")),
        expiration_date=data.get("expiration_date"),
        underlying_symbol=_decode_symbol(data.get("underlying_symbol")),
    )


def _decode_order(account_id: str, data: dict[str, Any]) -> StOrder:
    sym_raw = data.get("universal_symbol")
    opt_raw = data.get("option_symbol")
    currency = "USD"
    if isinstance(sym_raw, dict):
        cur = sym_raw.get("currency") or {}
        if isinstance(cur, dict):
            currency = cur.get("code") or "USD"
    return StOrder(
        id=data.get("brokerage_order_id") or "",
        account_id=account_id,
        status=data.get("status") or "",
        action=data.get("action") or "",
        symbol=_decode_symbol(sym_raw if isinstance(sym_raw, dict) else None),
        option_symbol=_decode_option_symbol(opt_raw if isinstance(opt_raw, dict) else None),
        filled_quantity=_dec(data.get("filled_quantity")),
        execution_price=_dec(data.get("execution_price")),
        time_executed=data.get("time_executed"),
        time_placed=data.get("time_placed"),
        currency=currency,
    )
