"""Value types returned by the `Storage` protocol.

Public surface — these appear in `Storage.merge_chunk` / `read_meta` /
`read_account` / `read_account_window` / `read_investment_account` return
types and are re-exported from `finstore.storage`. On-disk schema is owned
by the storage impl (plan §10.1); these dataclasses are the in-memory contract.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from finstore.model import (
    Account,
    Connection,
    InvestmentAccount,
    InvestmentTransaction,
    Transaction,
)


@dataclass(frozen=True)
class AccountMeta:
    last_fetch_at: int
    txn_count: int
    earliest_posted: int | None
    latest_posted: int | None
    conn_id: str = ""
    sfin_id: str = ""  # latest backend-supplied account id (informational only)


@dataclass(frozen=True)
class InvestmentAccountMeta:
    last_fetch_at: int
    txn_count: int
    position_count: int
    earliest_trade: int | None
    latest_trade: int | None
    conn_id: str
    broker_id: str


@dataclass(frozen=True)
class CacheMeta:
    schema_version: int                          # 5 in v5
    last_fetch_at: int                           # epoch seconds UTC
    connections: tuple[Connection, ...]
    accounts: dict[str, AccountMeta]             # keyed by display_id
    investment_accounts: dict[str, InvestmentAccountMeta] = field(default_factory=dict)


@dataclass(frozen=True)
class CachedAccount:
    """Internal: account snapshot + the (possibly window-filtered) txns."""

    account: Account
    transactions: tuple[Transaction, ...]


@dataclass(frozen=True)
class CachedInvestmentAccount:
    """Internal: investment account snapshot + (possibly window-filtered) txns."""

    account: InvestmentAccount
    investment_transactions: tuple[InvestmentTransaction, ...]


@dataclass(frozen=True)
class InvestmentAccountSummary:
    """Lightweight stub — what ``Storage.list_investment_accounts`` returns."""

    acctid: str
    name: str
    currency: str
    broker_id: str
    connection: Connection
    last_fetch_at: int | None
    txn_count: int
    position_count: int


@dataclass(frozen=True)
class MergeStats:
    accounts_seen: int
    txns_new: int
    txns_duplicate: int
    inv_accounts_seen: int = 0
    inv_txns_new: int = 0
    inv_txns_duplicate: int = 0
    positions_written: int = 0
    securities_upserted: int = 0


__all__ = [
    "AccountMeta",
    "CachedAccount",
    "CachedInvestmentAccount",
    "CacheMeta",
    "InvestmentAccountMeta",
    "InvestmentAccountSummary",
    "MergeStats",
]
