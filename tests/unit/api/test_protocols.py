"""Protocol-level API tests — exercise `finstore.fetch` and the `Backend` /
`Storage` protocols against fakes. No filesystem, no httpx. If these pass,
the public surface is sufficient for a non-reference implementation.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from decimal import Decimal

import pytest

from finstore import (
    BackendError,
    CredentialError,
    FinstoreError,
    StorageError,
    Tenant,
    ValidationError,
    Window,
    fetch,
)
from finstore.model import (
    Account,
    AccountSummary,
    Connection,
    StorageChunk,
    Transaction,
)
from finstore.protocols import Backend, Credentials, Storage
from finstore.storage.types import AccountMeta, CachedAccount, CacheMeta, MergeStats

# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


@dataclass
class FakeStorage:
    """In-memory `Storage` impl — satisfies the protocol structurally."""

    chunks: list[tuple[str, StorageChunk]] = field(default_factory=list)
    _credentials: dict[tuple[str, str], bytes] = field(default_factory=dict)

    def merge_chunk(self, tenant_id: str, chunk: StorageChunk) -> MergeStats:
        self.chunks.append((tenant_id, chunk))
        return MergeStats(
            accounts_seen=len(chunk.accounts),
            txns_new=sum(len(a.transactions) for a in chunk.accounts),
            txns_duplicate=0,
        )

    def read_meta(self, tenant_id: str = "local") -> CacheMeta:
        return CacheMeta(
            schema_version=4, last_fetch_at=0, connections=(), accounts={}
        )

    def resolve_display_id(self, tenant_id: str, display_id: str) -> str:
        return display_id

    def read_account(self, tenant_id: str, account_id: str) -> CachedAccount:
        raise NotImplementedError

    def read_account_window(
        self,
        tenant_id: str,
        account_id: str,
        dtstart_epoch: int,
        dtend_epoch: int | None,
    ) -> CachedAccount:
        raise NotImplementedError

    def list_accounts(self, tenant_id: str = "local") -> tuple[AccountSummary, ...]:
        return ()

    def read_backend_credential(self, tenant_id: str, backend_id: str) -> bytes | None:
        return self._credentials.get((tenant_id, backend_id))

    def write_backend_credential(
        self, tenant_id: str, backend_id: str, data: bytes
    ) -> None:
        self._credentials[(tenant_id, backend_id)] = data

    def exists_backend_credential(self, tenant_id: str, backend_id: str) -> bool:
        return (tenant_id, backend_id) in self._credentials


@dataclass(frozen=True)
class FakeCredentials:
    """Empty marker satisfaction — structurally a `Credentials`."""

    token: str = "fake"


@dataclass
class FakeBackend:
    """Backend that emits one StorageChunk per call and records its inputs."""

    seen_tenant_id: str = ""
    seen_window: tuple[int, int | None] = (0, None)

    async def fetch_and_persist(
        self,
        storage: Storage,
        *,
        tenant_id: str,
        dtstart_epoch: int,
        dtend_epoch: int | None = None,
    ) -> dict[str, object]:
        self.seen_tenant_id = tenant_id
        self.seen_window = (dtstart_epoch, dtend_epoch)
        chunk = StorageChunk(
            accounts=(
                Account(
                    id="acct-1",
                    name="Checking",
                    currency="USD",
                    balance=Decimal("100.00"),
                    available_balance=None,
                    balance_date=dtstart_epoch,
                    conn_id="conn-x",
                    transactions=(
                        Transaction(
                            id="t-1",
                            posted=dtstart_epoch + 1,
                            amount=Decimal("1.23"),
                            description="d",
                            payee="p",
                            memo="m",
                            transacted_at=None,
                        ),
                    ),
                ),
            ),
            connections=(
                Connection(conn_id="conn-x", org_name="Bank", org_id="org-x"),
            ),
        )
        stats = storage.merge_chunk(tenant_id, chunk)
        return {"accounts": stats.accounts_seen, "new": stats.txns_new}


# ---------------------------------------------------------------------------
# Protocol satisfaction (runtime isinstance)
# ---------------------------------------------------------------------------


class TestProtocolsAreRuntimeCheckable:
    def test_fake_storage_is_storage(self) -> None:
        assert isinstance(FakeStorage(), Storage)

    def test_fake_backend_is_backend(self) -> None:
        assert isinstance(FakeBackend(), Backend)

    def test_fake_credentials_is_credentials(self) -> None:
        assert isinstance(FakeCredentials(), Credentials)


# ---------------------------------------------------------------------------
# fetch() orchestration
# ---------------------------------------------------------------------------


class TestFetchOrchestration:
    def test_passes_tenant_id_through(self) -> None:
        storage = FakeStorage()
        backend = FakeBackend()
        tenant = Tenant(id="cloud-user-7")
        window: Window = (1_700_000_000, 1_700_900_000)

        report = asyncio.run(fetch(tenant, backend, storage, window=window))

        assert backend.seen_tenant_id == "cloud-user-7"
        assert backend.seen_window == (1_700_000_000, 1_700_900_000)
        assert report == {"accounts": 1, "new": 1}

    def test_storage_receives_normalized_chunk(self) -> None:
        storage = FakeStorage()
        asyncio.run(
            fetch(Tenant(id="local"), FakeBackend(), storage, window=(1_700_000_000, None))
        )
        assert len(storage.chunks) == 1
        tenant_id, chunk = storage.chunks[0]
        assert tenant_id == "local"
        assert chunk.accounts[0].id == "acct-1"
        assert chunk.connections[0].conn_id == "conn-x"

    def test_window_open_upper_bound(self) -> None:
        backend = FakeBackend()
        asyncio.run(
            fetch(Tenant(id="local"), backend, FakeStorage(), window=(1_700_000_000, None))
        )
        assert backend.seen_window == (1_700_000_000, None)


# ---------------------------------------------------------------------------
# Cancellation semantics (§11.d — resolved: propagate, partial writes kept)
# ---------------------------------------------------------------------------


class _CancellingBackend:
    """Writes one chunk, then raises CancelledError before the second."""

    async def fetch_and_persist(
        self,
        storage: Storage,
        *,
        tenant_id: str,
        dtstart_epoch: int,
        dtend_epoch: int | None = None,
    ) -> None:
        chunk = StorageChunk(
            accounts=(
                Account(
                    id="acct-1",
                    name="Checking",
                    currency="USD",
                    balance=Decimal("0.00"),
                    available_balance=None,
                    balance_date=dtstart_epoch,
                    conn_id="conn-x",
                    transactions=(),
                ),
            ),
            connections=(Connection(conn_id="conn-x", org_name="b", org_id="o"),),
        )
        storage.merge_chunk(tenant_id, chunk)
        raise asyncio.CancelledError


class TestCancellation:
    def test_propagates_cancelled_error(self) -> None:
        storage = FakeStorage()

        with pytest.raises(asyncio.CancelledError):
            asyncio.run(
                fetch(
                    Tenant(id="local"),
                    _CancellingBackend(),
                    storage,
                    window=(1_700_000_000, None),
                )
            )

        # Partial write is preserved — the first chunk made it into storage.
        assert len(storage.chunks) == 1


# ---------------------------------------------------------------------------
# Exception hierarchy (§11.e)
# ---------------------------------------------------------------------------


class TestExceptionHierarchy:
    @pytest.mark.parametrize(
        "exc_cls",
        [BackendError, StorageError, CredentialError, ValidationError],
    )
    def test_all_inherit_from_finstore_error(self, exc_cls: type[Exception]) -> None:
        assert issubclass(exc_cls, FinstoreError)

    def test_storage_exceptions_under_storage_error(self) -> None:
        from finstore.storage import (
            CacheCorruptError,
            CacheEmptyError,
            CacheMissError,
            CacheSchemaMismatchError,
        )

        for exc_cls in (
            CacheCorruptError,
            CacheEmptyError,
            CacheMissError,
            CacheSchemaMismatchError,
        ):
            assert issubclass(exc_cls, StorageError)

    def test_simplefin_upstream_error_under_backend_error(self) -> None:
        from finstore.backends.simplefin.client import UpstreamServerError

        assert issubclass(UpstreamServerError, BackendError)


# ---------------------------------------------------------------------------
# Model immutability — public dataclasses are frozen so the contract is stable
# ---------------------------------------------------------------------------


class TestModelImmutability:
    def test_tenant_is_frozen(self) -> None:
        t = Tenant(id="local")
        with pytest.raises(Exception):  # FrozenInstanceError
            t.id = "other"  # type: ignore[misc]

    def test_account_is_frozen(self) -> None:
        a = Account(
            id="i", name="n", currency="USD",
            balance=Decimal("0"), available_balance=None,
            balance_date=0, conn_id="c", transactions=(),
        )
        with pytest.raises(Exception):
            a.id = "x"  # type: ignore[misc]

    def test_transaction_is_frozen(self) -> None:
        t = Transaction(
            id="i", posted=0, amount=Decimal("0"),
            description="", payee="", memo="", transacted_at=None,
        )
        with pytest.raises(Exception):
            t.id = "x"  # type: ignore[misc]

    def test_account_has_no_org_or_holdings_fields(self) -> None:
        """§11.a decision: org/holdings dropped from public Account.

        org info lives on Connection; holdings is brokerage data (a non-goal
        at 0.1 — see plan §2 and docs/plans/brokerage-support/).
        """
        a = Account(
            id="i", name="n", currency="USD",
            balance=Decimal("0"), available_balance=None,
            balance_date=0, conn_id="c", transactions=(),
        )
        assert not hasattr(a, "org")
        assert not hasattr(a, "holdings")


# ---------------------------------------------------------------------------
# StorageChunk / MergeStats / CacheMeta shape — exercised here so a
# downstream Storage impl can rely on these as public types.
# ---------------------------------------------------------------------------


class TestStorageReturnTypes:
    def test_merge_stats_fields(self) -> None:
        stats = MergeStats(accounts_seen=2, txns_new=10, txns_duplicate=1)
        assert (stats.accounts_seen, stats.txns_new, stats.txns_duplicate) == (2, 10, 1)

    def test_cache_meta_carries_connections_and_accounts(self) -> None:
        meta = CacheMeta(
            schema_version=4,
            last_fetch_at=123,
            connections=(Connection(conn_id="c", org_name="o", org_id="i"),),
            accounts={"display-1": AccountMeta(
                last_fetch_at=123, txn_count=5,
                earliest_posted=None, latest_posted=None,
                conn_id="c",
            )},
        )
        assert meta.schema_version == 4
        assert meta.connections[0].conn_id == "c"
        assert meta.accounts["display-1"].txn_count == 5
