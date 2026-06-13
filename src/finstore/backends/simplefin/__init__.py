"""SimpleFIN backend — installed via the `[simplefin]` extra.

Public API: `activate`, `SimpleFINBackend`, `SimpleFINCredentials`, `FetchReport`.
The `Sf*` types in `.models` are backend-internal; do not import them
outside this package.
"""
from __future__ import annotations

from finstore.backends.simplefin.activate import activate
from finstore.backends.simplefin.backend import (
    FetchReport,
    SimpleFINBackend,
    SimpleFINCredentials,
)

__all__ = ["FetchReport", "SimpleFINBackend", "SimpleFINCredentials", "activate"]
