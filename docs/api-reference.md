# finstore — Public API Reference (0.2)

Changes to anything listed here require a minor (new symbol) or major
(changed/removed symbol) version bump and a CHANGELOG entry. Everything else
is free to change between patch releases.

---

## Concepts

finstore has three moving parts that you wire together:

**Backend** — knows how to fetch financial data from one provider (e.g. SimpleFIN)
and write normalized chunks into Storage. It owns the provider-specific HTTP
client and credential. All provider details — wire formats, authentication, window
iteration — stay inside the backend; nothing leaks out.

**Storage** — knows how to persist and query the normalized data. The reference
implementation (`FilesystemStorage`) writes JSON files to a local directory.
Storage also persists backend credentials via `read_backend_credential` /
`write_backend_credential`, so the same abstraction covers both financial data and
the secrets needed to fetch it.

**Tenant** — a string identity (`Tenant(id="local")` for single-user deployments)
that scopes every Storage call. All reads and writes carry a `tenant_id`, so the
same Storage instance can in principle hold data for multiple users without
cross-contamination. The reference `FilesystemStorage` is single-tenant and
currently ignores it, but the parameter must always be threaded through.

**Data flow:** `activate()` resolves a credential — either by exchanging a setup
token, validating a directly supplied access URL, or loading one already persisted
— writes it to Storage, and returns a wired Backend. From there, `fetch()` drives
the Backend → Storage pipeline: the backend calls the provider API, converts the
response into neutral `finstore.model` types (the *normalization seam*), and hands
a `StorageChunk` to `storage.merge_chunk()`. Reads (`list_accounts`,
`read_account_window`, etc.) go directly to Storage; the backend is not involved.

---

## Top-level (`finstore`)

```python
from finstore import fetch, Tenant, Window, FinstoreError
from finstore import BackendError, StorageError, CredentialError, ValidationError
```

### `Tenant`

```python
@dataclass(frozen=True)
class Tenant:
    id: str
```

Pure identity token. The local app uses `Tenant(id="local")`. A future
multi-tenant deployment would derive the id from auth. Every storage call is
scoped to a tenant.

### `Window`

```python
Window = tuple[int, int | None]
```

`(dtstart_epoch, dtend_epoch_or_none)`. Epoch seconds UTC. `None` on the upper
bound means "no upper limit." Bounds are inclusive at both the backend and the
storage reader.

### `fetch()`

```python
async def fetch(
    tenant: Tenant,
    backend: Backend,
    storage: Storage,
    *,
    window: Window,
) -> Any
```

Fetch one window of financial data via `backend` and persist it into `storage`
under `tenant`. Returns the backend's report object (today: `FetchReport` from
`SimpleFINBackend`).

**Cancellation:** `asyncio.CancelledError` propagates to the caller. Any
`storage.merge_chunk()` calls that completed before cancellation are kept on
disk; the in-flight chunk is dropped. No rollback is attempted.

### Exception hierarchy

```
FinstoreError
├── BackendError        # backend fetch or activation failed (network, auth, upstream)
├── StorageError        # storage read/write failed
│   ├── CacheMissError          (finstore.storage)
│   ├── CacheEmptyError         (finstore.storage)
│   ├── CacheCorruptError       (finstore.storage)
│   └── CacheSchemaMismatchError (finstore.storage)
├── CredentialError     # credentials missing, malformed, or rejected
└── ValidationError     # data crossing a public boundary failed validation
```

---

## Data model (`finstore.model`)

```python
from finstore.model import Account, Transaction, Connection, AccountSummary, StorageChunk, Window
```

All model types are **frozen dataclasses**. Fields listed here are guaranteed
at 0.1; backends may not populate optional fields (marked below).

### `Account`

| Field | Type | Notes |
|---|---|---|
| `id` | `str` | Backend-assigned identifier (e.g. raw SimpleFIN id) |
| `name` | `str` | Display name |
| `currency` | `str` | ISO 4217 code (e.g. `"USD"`) |
| `balance` | `Decimal` | Ledger balance |
| `available_balance` | `Decimal \| None` | May be absent |
| `balance_date` | `int` | Epoch seconds UTC |
| `conn_id` | `str` | Links to a `Connection` |
| `transactions` | `tuple[Transaction, ...]` | |

### `Transaction`

| Field | Type | Notes |
|---|---|---|
| `id` | `str` | Backend-assigned identifier |
| `posted` | `int` | Epoch seconds UTC |
| `amount` | `Decimal` | Signed; `"0.00"` is valid (fee reversals) |
| `description` | `str` | |
| `payee` | `str` | |
| `memo` | `str` | |
| `transacted_at` | `int \| None` | When the transaction was initiated; may be absent |

### `Connection`

| Field | Type | Notes |
|---|---|---|
| `conn_id` | `str` | Stable identifier (e.g. institution domain) |
| `org_name` | `str` | Human-readable institution name |
| `org_id` | `str` | Backend-assigned institution id |
| `org_domain` | `str` | Default `""` |
| `sfin_url` | `str` | Default `""` |
| `org_url` | `str` | Default `""` |

### `AccountSummary`

Lightweight stub returned by `Storage.list_accounts`. Does not include
transactions.

| Field | Type | Notes |
|---|---|---|
| `acctid` | `str` | Display id (e.g. sanitized account name) |
| `name` | `str` | |
| `currency` | `str` | |
| `connection` | `Connection` | |
| `last_fetch_at` | `int \| None` | `None` if never fetched |
| `txn_count` | `int` | Total stored transactions |

### `StorageChunk`

Unit of normalized data produced by a backend and consumed by `Storage.merge_chunk`.

| Field | Type |
|---|---|
| `accounts` | `tuple[Account, ...]` |
| `connections` | `tuple[Connection, ...]` |

---

## Protocols (`finstore.protocols`)

```python
from finstore.protocols import Backend, Storage, Credentials
```

All three are `@runtime_checkable`.

### `Backend` protocol

```python
async def fetch_and_persist(
    self,
    storage: Storage,
    *,
    tenant_id: str,
    dtstart_epoch: int,
    dtend_epoch: int | None = None,
) -> Any
```

### `Storage` protocol

```python
def merge_chunk(self, tenant_id: str, chunk: StorageChunk) -> MergeStats
def read_meta(self, tenant_id: str = ...) -> CacheMeta
def resolve_display_id(self, tenant_id: str, display_id: str) -> str
def read_account(self, tenant_id: str, account_id: str) -> CachedAccount
def read_account_window(
    self, tenant_id: str, account_id: str,
    dtstart_epoch: int, dtend_epoch: int | None,
) -> CachedAccount
def list_accounts(self, tenant_id: str = ...) -> tuple[AccountSummary, ...]

# Credential persistence (added 0.2.1)
def read_backend_credential(self, tenant_id: str, backend_id: str) -> bytes | None
def write_backend_credential(self, tenant_id: str, backend_id: str, data: bytes) -> None
def exists_backend_credential(self, tenant_id: str, backend_id: str) -> bool
def delete_backend_credential(self, tenant_id: str, backend_id: str) -> bool
```

`backend_id` is a short namespacing string (e.g. `"simplefin"`). The protocol
makes no assumption about the content of `data` — that is the backend's concern.
Implementations must store data with mode 0600 (or equivalent) and atomically
replace any prior value. `delete_backend_credential` returns `True` if a
credential existed and was removed, `False` if nothing was stored for that key.

### `Credentials` protocol

Empty marker. Each backend defines its own frozen dataclass that satisfies it
structurally.

---

## Storage (`finstore.storage`)

```python
from finstore.storage.filesystem import FilesystemStorage
from finstore.storage import (
    CacheMissError, CacheEmptyError, CacheCorruptError, CacheSchemaMismatchError,
    CacheMeta, CachedAccount, AccountMeta, MergeStats,
)
```

### `FilesystemStorage(root: Path)`

Reference `Storage` implementation. Single-writer invariant: only one process
should call `merge_chunk` at a time. Reads are safe to concurrent callers.

On-disk layout under `root`:

```
<root>/
  meta.json
  accounts/<conn_id>/<display_id>.json
  tenants/<tenant_id>/credentials/<backend_id>.bin   # credential blobs
```

### Return types

**`MergeStats`** — returned by `merge_chunk`.

| Field | Type |
|---|---|
| `accounts_seen` | `int` |
| `txns_new` | `int` |
| `txns_duplicate` | `int` |

**`CacheMeta`** — returned by `read_meta`.

| Field | Type |
|---|---|
| `schema_version` | `int` |
| `last_fetch_at` | `int` |
| `connections` | `tuple[Connection, ...]` |
| `accounts` | `dict[str, AccountMeta]` |

**`CachedAccount`** — returned by `read_account` and `read_account_window`.

| Field | Type |
|---|---|
| `account` | `Account` |
| `display_id` | `str` |

**`AccountMeta`**

| Field | Type |
|---|---|
| `last_fetch_at` | `int` |
| `txn_count` | `int` |
| `earliest_posted` | `int \| None` |
| `latest_posted` | `int \| None` |
| `conn_id` | `str` |

---

## SimpleFIN backend (`finstore.backends.simplefin`)

Requires the `[simplefin]` extra (`pip install finstore[simplefin]`).

```python
from finstore.backends.simplefin import activate, SimpleFINBackend, SimpleFINCredentials, FetchReport
```

### `activate()` — recommended entry-point

```python
async def activate(
    secret: str | None,
    *,
    storage: Storage,
    tenant_id: str,
    client: httpx.AsyncClient,
) -> SimpleFINBackend
```

Obtain a `SimpleFINBackend` that is ready to fetch, handling credential
bootstrap and persistence in one call.

**`secret` accepts three forms:**

- **Base64-encoded setup token** — the one-time token from SimpleFIN's bridge.
  `activate` decodes it, POSTs to the claim URL to exchange it for an access
  URL (a one-shot, irreversible operation), persists the access URL via
  `storage.write_backend_credential`, and returns a wired backend. The exchange
  itself serves as proof that the credential is valid, so no extra probe is made.
- **Access URL** (`https://…`) — a previously obtained access URL supplied
  directly (e.g. restored from a backup). `activate` first validates it with a
  lightweight probe (GET `/accounts` with an empty time window) before
  persisting. If the probe fails (non-2xx or network error) `BackendError` is
  raised and the existing persisted credential is left untouched, so a bad
  restored URL cannot overwrite a working one.
- **`None`** — load the previously persisted credential from `storage`. Raises
  `BackendError` if none exists.

On any failure raises `BackendError`. All internal SimpleFIN protocol details
(setup token vs access URL, probe URL construction) are invisible to the caller.

`client` is caller-owned; `activate` neither opens nor closes it.

**Typical usage in an application container:**

```python
import httpx
from finstore.backends.simplefin import activate
from finstore.exceptions import BackendError
from finstore.storage.filesystem import FilesystemStorage

storage = FilesystemStorage(root=data_dir)

async with httpx.AsyncClient() as client:
    # On first run, pass the opaque secret from your env/secrets manager.
    # On subsequent runs, pass None to load the persisted credential.
    secret = os.environ.get("SIMPLEFIN_SECRET")  # None after first activation
    try:
        backend = await activate(secret, storage=storage, tenant_id="local", client=client)
    except BackendError as exc:
        raise RuntimeError("SimpleFIN activation failed") from exc

    await fetch(tenant, backend, storage, window=(dtstart, None))
```

### `SimpleFINCredentials`

```python
@dataclass(frozen=True)
class SimpleFINCredentials:
    access_url: str
```

Structurally satisfies the `Credentials` marker. Pass to `SimpleFINBackend`
directly when you already have an access URL and do not need `activate()`'s
credential persistence (e.g. in tests).

### `SimpleFINBackend`

```python
SimpleFINBackend(
    credentials: SimpleFINCredentials,
    httpx_client: httpx.AsyncClient,
    *,
    chunk_window_days: int = 90,
    max_retries: int = 1,
)
```

Satisfies the `Backend` protocol. Prefer `activate()` over constructing this
directly in production code.

### `FetchReport`

Returned by `fetch()` when the backend is `SimpleFINBackend`.

| Field | Type | Notes |
|---|---|---|
| `chunks` | `int` | Number of time windows fetched |
| `accounts_seen` | `int` | |
| `txns_new` | `int` | |
| `txns_duplicate` | `int` | |
| `errlist` | `tuple[tuple[str, str], ...]` | `(code, message)` pairs from SimpleFIN's error list; empty when clean |
| `duration_secs` | `float` | |

---

## What is NOT public API

- `finstore.backends.simplefin.models` — the `Sf*` types are backend-internal.
  Do not import them; the arch tests will catch violations.
- `finstore_local.*` — the self-hosted app modules. The CLI command shape
  (`finstore fetch`, `finstore serve`, etc.) and dashboard URL paths are
  public surface; the Python modules behind them are not.
- `finstore.storage._schema` — internal schema constants.
- Anything prefixed `_`.
