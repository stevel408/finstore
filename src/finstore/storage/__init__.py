"""Storage layer.

`FilesystemStorage` is the reference impl shipped in core. The `Storage`
protocol lives in `finstore.protocols`. Storage-layer exceptions
(`CacheMissError`, `CacheEmptyError`, `CacheCorruptError`,
`CacheSchemaMismatchError`) all subclass `finstore.StorageError`.
Return value types (`CacheMeta`, `CachedAccount`, `MergeStats`,
`AccountMeta`) live in `finstore.storage.types`.
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
    CacheMeta,
    MergeStats,
)

__all__ = [
    "AccountMeta",
    "CacheCorruptError",
    "CacheEmptyError",
    "CacheMeta",
    "CacheMissError",
    "CacheSchemaMismatchError",
    "CachedAccount",
    "FilesystemStorage",
    "MergeStats",
]
