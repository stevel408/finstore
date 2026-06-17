"""Backend-agnostic data model — the contract spoken at every public surface.

`gateway.model` is gone; everything imports from here.

Hard rule: no module under `finstore.model.*` may import from
`finstore.storage.*`, `finstore.backends.*`, `finstore.fetch`,
`finstore_local.*`, or `gateway.*`. The model is downstream of nothing.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum

Window = tuple[int, int | None]
"""(dtstart_epoch, dtend_epoch_or_none) — bounds are inclusive at the readers
and emitters that consume them. `None` on the upper bound means "no upper
limit"."""


class AccountType(str, Enum):
    """OFX-aligned account classification used to route statement generation."""

    CHECKING   = "CHECKING"
    SAVINGS    = "SAVINGS"
    CREDITCARD = "CREDITCARD"
    MONEYMRKT  = "MONEYMRKT"
    INVESTMENT = "INVESTMENT"
    OTHER      = "OTHER"


@dataclass(frozen=True)
class Tenant:
    """Pure identity. Local app uses `Tenant(id="local")`; cloud derives from auth."""

    id: str


@dataclass(frozen=True)
class Transaction:
    id: str
    posted: int                 # epoch seconds UTC
    amount: Decimal             # signed; "0.00" is legitimate (fee reversals)
    description: str
    payee: str
    memo: str
    transacted_at: int | None


@dataclass(frozen=True)
class Connection:
    conn_id: str
    org_name: str
    org_id: str
    org_domain: str = ""
    sfin_url: str = ""
    org_url: str = ""


@dataclass(frozen=True)
class Account:
    id: str
    name: str
    currency: str
    balance: Decimal
    available_balance: Decimal | None
    balance_date: int           # epoch seconds UTC
    conn_id: str
    transactions: tuple[Transaction, ...]
    account_type: AccountType = AccountType.CHECKING


@dataclass(frozen=True)
class AccountSummary:
    """Lightweight stub — what `Storage.list_accounts` returns."""

    acctid: str                 # = display_id under FilesystemStorage
    name: str
    currency: str
    connection: Connection
    last_fetch_at: int | None
    txn_count: int
    account_type: AccountType = AccountType.CHECKING


@dataclass(frozen=True)
class Security:
    """A tradable instrument.  Maps to OFX ``SECINFO`` / ``SECID``.

    ``(uniqueid_type, uniqueid)`` is the logical primary key.
    """

    uniqueid: str       # e.g. CUSIP "037833100", ISIN "US0378331005", "AAPL"
    uniqueid_type: str  # "CUSIP" | "ISIN" | "TICKER" | "OTHER"
    name: str
    ticker: str         # may equal uniqueid when uniqueid_type is "TICKER"
    security_type: str  # "STOCK" | "MUTUALFUND" | "DEBT" | "OTHER"


@dataclass(frozen=True)
class InvestmentTransaction:
    """One investment activity.  Maps to OFX ``INVTRAN`` + typed wrappers.

    ``trntype`` well-known values:
      ``BUY`` | ``SELL`` | ``REINVEST`` | ``INCOME`` | ``TRANSFER`` |
      ``CONTRIBUTION`` | ``WITHDRAWAL`` | ``FEE`` | ``TAX`` | ``SPLIT`` |
      ``MARGININTEREST`` | ``RETOFCAP`` | ``OTHER``

    ``income_type`` well-known values (OFX ``INCOMETYPE``):
      ``DIV`` | ``CGLONG`` | ``CGSHORT`` | ``INTEREST`` | ``OTHER``
    """

    id: str
    trade_date: int              # epoch seconds UTC — OFX DTTRADE
    settle_date: int | None      # epoch seconds UTC — OFX DTSETTLE
    trntype: str
    security_id: str | None      # None for cash-only trns (CONTRIBUTION, etc.)
    security_id_type: str | None
    units: Decimal | None        # shares; positive = buy/in, negative = sell/out
    unit_price: Decimal | None
    commission: Decimal | None
    fees: Decimal | None
    taxes: Decimal | None
    total: Decimal               # net settlement amount, signed (negative = debit)
    income_type: str | None      # set only for INCOME and REINVEST
    description: str
    memo: str
    currency: str


@dataclass(frozen=True)
class Position:
    """Point-in-time holding.  Maps to OFX ``INVPOS``.

    Always the *latest* snapshot — historical positions are not stored.
    """

    security_id: str
    security_id_type: str
    units: Decimal          # shares held
    unit_price: Decimal     # price as of snapshot_date
    market_value: Decimal
    cost_basis: Decimal | None
    held_in_acct: str       # "CASH" | "MARGIN" | "SHORT" | "OTHER"
    pos_type: str           # "LONG" | "SHORT"
    snapshot_date: int      # epoch seconds UTC — when this position was fetched


@dataclass(frozen=True)
class InvestmentAccount:
    """A brokerage / investment account.  Maps to OFX ``INVSTMTRS``.

    Kept separate from ``Account`` because the OFX statement type, merge
    semantics (positions replace; transactions append), and on-disk format
    are all different from cash accounts.
    """

    id: str
    name: str
    currency: str
    broker_id: str                       # OFX BROKERID — normalized brokerage_slug
    available_cash: Decimal | None
    margin_balance: Decimal | None
    balance_date: int                    # epoch seconds UTC
    conn_id: str
    positions: tuple[Position, ...]
    investment_transactions: tuple[InvestmentTransaction, ...]


@dataclass(frozen=True)
class StorageChunk:
    """One unit of normalized data ready to be merged into storage.

    Backends produce a stream of ``StorageChunk``s; storage merges them.
    ``investment_accounts`` and ``securities`` default to empty tuples so
    existing SimpleFIN callers need no changes.
    """

    accounts: tuple[Account, ...]
    connections: tuple[Connection, ...]
    investment_accounts: tuple[InvestmentAccount, ...] = ()
    securities: tuple[Security, ...] = ()


__all__ = [
    "Account",
    "AccountSummary",
    "AccountType",
    "Connection",
    "InvestmentAccount",
    "InvestmentTransaction",
    "Position",
    "Security",
    "StorageChunk",
    "Tenant",
    "Transaction",
    "Window",
]
