"""finstore — backend-agnostic local repository of a user's financial data.

Public surface at 0.1:

    from finstore import Tenant, fetch, FinstoreError
    from finstore import BACKENDS, BackendInfo, BackendStatus, backend_status
    from finstore.model import Account, Transaction, Connection, Window, AccountSummary
    from finstore.protocols import Backend, Storage, Credentials
    from finstore.storage.filesystem import FilesystemStorage
    from finstore.backends.simplefin import SimpleFINBackend, SimpleFINCredentials

`finstore.backends.simplefin` / `.snaptrade` each require their own extra
(`[simplefin]`, `[snaptrade]`); `finstore.backends` itself (the registry) does
not. `finstore_local.*` is not importable API (it's the self-hosted app); its
CLI command shape and dashboard URL paths are public surface, the Python
modules behind them are not.
"""
from __future__ import annotations

from finstore.backends import BACKENDS, BackendInfo, BackendStatus, backend_status
from finstore.exceptions import (
    BackendError,
    CredentialError,
    FinstoreError,
    StorageError,
    ValidationError,
)
from finstore.fetch import fetch
from finstore.model import Tenant, Window

__all__ = [
    "BACKENDS",
    "BackendError",
    "BackendInfo",
    "BackendStatus",
    "CredentialError",
    "FinstoreError",
    "StorageError",
    "Tenant",
    "ValidationError",
    "Window",
    "backend_status",
    "fetch",
]
