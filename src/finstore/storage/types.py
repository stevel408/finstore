"""Value types returned by the `Storage` protocol.

Public surface — these appear in `Storage.merge_chunk` / `read_meta` /
`read_account` / `read_account_window` return types and are re-exported
from `finstore.storage`. On-disk schema is owned by the storage impl
(plan §10.1); these dataclasses are the in-memory contract.
"""
from __future__ import annotations

from dataclasses import dataclass

from finstore.model import Account, Connection, Transaction


@dataclass(frozen=True)
class AccountMeta:
    last_fetch_at: int
    txn_count: int
    earliest_posted: int | None
    latest_posted: int | None
    conn_id: str = ""
    sfin_id: str = ""  # latest backend-supplied account id (informational only)


@dataclass(frozen=True)
class CacheMeta:
    schema_version: int                # 4 in v4
    last_fetch_at: int                  # epoch seconds UTC
    connections: tuple[Connection, ...]
    accounts: dict[str, AccountMeta]   # keyed by display_id


@dataclass(frozen=True)
class CachedAccount:
    """Internal: account snapshot + the (possibly window-filtered) txns."""

    account: Account
    transactions: tuple[Transaction, ...]


@dataclass(frozen=True)
class MergeStats:
    accounts_seen: int
    txns_new: int
    txns_duplicate: int


__all__ = ["AccountMeta", "CacheMeta", "CachedAccount", "MergeStats"]
