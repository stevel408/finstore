"""SimpleFIN backend — the only place that translates `Sf*` types into the
neutral `finstore.model.*` types. See plan §4.2.

Async-cancellation contract: `fetch_and_persist` propagates `CancelledError`.
Per-account writes inside `FilesystemStorage.merge_chunk` are atomic, so
whatever completed before cancellation stays on disk; the in-flight chunk
is dropped.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

from finstore.backends.simplefin.client import (
    SimpleFinClient,
    _filter_errlist,
    _windows,
)
from finstore.backends.simplefin.models import (
    SfAccount,
    SfConnection,
    SfResponse,
    SfTransaction,
)
from finstore.model import Account, Connection, StorageChunk, Transaction

if TYPE_CHECKING:
    import httpx

    from finstore.protocols import Storage


log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Credentials
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SimpleFINCredentials:
    """SimpleFIN access URL embeds basic-auth username:password@host."""

    access_url: str


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FetchReport:
    chunks: int
    accounts_seen: int
    txns_new: int
    txns_duplicate: int
    errlist: tuple[tuple[str, str], ...]
    duration_secs: float


# ---------------------------------------------------------------------------
# Sf* → neutral conversion (the normalization seam)
# ---------------------------------------------------------------------------


def _to_transaction(t: SfTransaction) -> Transaction:
    return Transaction(
        id=t.id,
        posted=t.posted,
        amount=t.amount,
        description=t.description,
        payee=t.payee,
        memo=t.memo,
        transacted_at=t.transacted_at,
    )


def _to_account(a: SfAccount) -> Account:
    return Account(
        id=a.id,
        name=a.name,
        currency=a.currency,
        balance=a.balance,
        available_balance=a.available_balance,
        balance_date=a.balance_date,
        conn_id=a.conn_id,
        transactions=tuple(_to_transaction(t) for t in a.transactions),
    )


def _to_connection(c: SfConnection) -> Connection:
    return Connection(
        conn_id=c.conn_id,
        org_name=c.org_name,
        org_id=c.org_id,
        org_domain=c.org_domain,
        sfin_url=c.sfin_url,
        org_url=c.org_url,
    )


def _normalize(chunk: SfResponse) -> StorageChunk:
    return StorageChunk(
        accounts=tuple(_to_account(a) for a in chunk.accounts),
        connections=tuple(_to_connection(c) for c in chunk.connections),
    )


# ---------------------------------------------------------------------------
# SimpleFINBackend
# ---------------------------------------------------------------------------


class SimpleFINBackend:
    """Owns the SimpleFIN transport client and Sf* → neutral conversion."""

    def __init__(
        self,
        credentials: SimpleFINCredentials,
        httpx_client: httpx.AsyncClient,
        *,
        chunk_window_days: int = 90,
        max_retries: int = 1,
    ):
        self._chunk_window_days = chunk_window_days
        self._client = SimpleFinClient(
            access_url=credentials.access_url,
            httpx_client=httpx_client,
            max_retries=max_retries,
        )

    async def fetch_and_persist(
        self,
        storage: Storage,
        *,
        tenant_id: str,
        dtstart_epoch: int,
        dtend_epoch: int | None = None,
    ) -> FetchReport:
        t0 = time.monotonic()
        end_anchor = dtend_epoch if dtend_epoch is not None else int(time.time())
        window_secs = self._chunk_window_days * 86400
        wins = _windows(dtstart_epoch, end_anchor, window_secs)

        surfaced_errs: list[tuple[str, str]] = []
        totals = {"new": 0, "dup": 0, "accounts": 0}

        for start, end in wins:
            sf_chunk = await self._client.fetch_chunk(start, end)
            log.info(
                "sf_chunk start=%d end=%d n_accounts=%d n_txns=%d errlist_count=%d",
                start, end,
                len(sf_chunk.accounts),
                sum(len(a.transactions) for a in sf_chunk.accounts),
                len(sf_chunk.errlist),
            )
            stats = storage.merge_chunk(tenant_id, _normalize(sf_chunk))
            totals["new"] += stats.txns_new
            totals["dup"] += stats.txns_duplicate
            totals["accounts"] = max(totals["accounts"], stats.accounts_seen)
            surfaced_errs.extend(_filter_errlist(sf_chunk.errlist))

        return FetchReport(
            chunks=len(wins),
            accounts_seen=totals["accounts"],
            txns_new=totals["new"],
            txns_duplicate=totals["dup"],
            errlist=tuple(surfaced_errs),
            duration_secs=time.monotonic() - t0,
        )


__all__ = ["FetchReport", "SimpleFINBackend", "SimpleFINCredentials"]
