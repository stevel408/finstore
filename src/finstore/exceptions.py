"""Public exception hierarchy. Anything raised across the `finstore` public API
inherits from `FinstoreError`; consumers can catch the umbrella or the leaves.
"""
from __future__ import annotations


class FinstoreError(Exception):
    """Base class for all finstore exceptions."""


class BackendError(FinstoreError):
    """A backend (SimpleFIN, ...) failed to fetch data."""


class StorageError(FinstoreError):
    """A storage backend (filesystem, ...) failed to read or write."""


class CredentialError(FinstoreError):
    """A backend's credentials were missing, malformed, or rejected."""


class ValidationError(FinstoreError):
    """Data that crossed a public boundary failed validation."""


__all__ = [
    "BackendError",
    "CredentialError",
    "FinstoreError",
    "StorageError",
    "ValidationError",
]
