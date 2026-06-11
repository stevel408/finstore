"""Storage-layer exceptions. All subclass `finstore.StorageError`."""
from __future__ import annotations

from finstore.exceptions import StorageError


class CacheMissError(StorageError):
    """Account file not present in cache."""

    def __init__(self, acctid: str):
        self.acctid = acctid
        super().__init__(f"Account not in cache: {acctid}")


class CacheEmptyError(StorageError):
    """Cache directory exists but has no accounts."""


class CacheCorruptError(StorageError):
    """Cache file exists but cannot be parsed."""


class CacheSchemaMismatchError(StorageError):
    """meta.json schema_version doesn't match expected."""

    def __init__(self, found: int, expected: int):
        self.found = found
        self.expected = expected
        super().__init__(
            f"Cache schema version {found} (expected {expected}). Re-run fetch."
        )


__all__ = [
    "CacheCorruptError",
    "CacheEmptyError",
    "CacheMissError",
    "CacheSchemaMismatchError",
]
