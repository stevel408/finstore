"""Storage layer.

`FilesystemStorage` is the reference impl shipped in core. The `Storage`
protocol lives in `finstore.protocols`. Storage-layer exceptions
(`CacheMissError`, `CacheEmptyError`, `CacheCorruptError`,
`CacheSchemaMismatchError`) all subclass `finstore.StorageError`.
Return value types live in `finstore.storage.types` and are re-exported here.
"""
from __future__ import annotations

from finstore.storage.exceptions import (
    CacheCorruptError,
    CacheEmptyError,
    CacheMissError,
    CacheSchemaMismatchError,
)
from finstore.storage.filesystem import FilesystemStorage
from finstore.storage.types import (
    AccountMeta,
    CachedAccount,
    CachedInvestmentAccount,
    CacheMeta,
    InvestmentAccountMeta,
    InvestmentAccountSummary,
    MergeStats,
)

__all__ = [
    "AccountMeta",
    "CacheCorruptError",
    "CacheEmptyError",
    "CachedAccount",
    "CachedInvestmentAccount",
    "CacheMeta",
    "CacheMissError",
    "CacheSchemaMismatchError",
    "FilesystemStorage",
    "InvestmentAccountMeta",
    "InvestmentAccountSummary",
    "MergeStats",
]
