"""Backend-agnostic data model — the contract spoken at every public surface.

`gateway.model` is gone; everything imports from here.

Hard rule: no module under `finstore.model.*` may import from
`finstore.storage.*`, `finstore.backends.*`, `finstore.fetch`,
`finstore_local.*`, or `gateway.*`. The model is downstream of nothing.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

Window = tuple[int, int | None]
"""(dtstart_epoch, dtend_epoch_or_none) — bounds are inclusive at the readers
and emitters that consume them. `None` on the upper bound means "no upper
limit"."""


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


@dataclass(frozen=True)
class AccountSummary:
    """Lightweight stub — what `Storage.list_accounts` returns."""

    acctid: str                 # = display_id under FilesystemStorage
    name: str
    currency: str
    connection: Connection
    last_fetch_at: int | None
    txn_count: int


@dataclass(frozen=True)
class StorageChunk:
    """One unit of normalized data ready to be merged into storage.

    Backends produce a stream of `StorageChunk`s; storage merges them.
    """

    accounts: tuple[Account, ...]
    connections: tuple[Connection, ...]


__all__ = [
    "Account",
    "AccountSummary",
    "Connection",
    "StorageChunk",
    "Tenant",
    "Transaction",
    "Window",
]
