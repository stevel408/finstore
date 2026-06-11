# finstore — Public API Reference (0.1)

Changes to anything listed here require a minor (new symbol) or major
(changed/removed symbol) version bump and a CHANGELOG entry. Everything else
is free to change between patch releases.

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
├── BackendError        # backend fetch failed (network, auth, upstream error)
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

All three are `@runtime_checkable`. See `docs/architecture.md` for the
full method signatures and rationale.

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

Constructor argument `root` is the storage directory (e.g.
`~/.local/share/finstore`). The directory and `accounts/` subdirectory must
exist before the first write; `finstore_local.config` creates them.

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
from finstore.backends.simplefin import SimpleFINBackend, SimpleFINCredentials, FetchReport
```

### `SimpleFINCredentials`

```python
@dataclass(frozen=True)
class SimpleFINCredentials:
    access_url: str
```

Structurally satisfies the `Credentials` marker.

### `SimpleFINBackend`

```python
SimpleFINBackend(
    credentials: SimpleFINCredentials,
    httpx_client: httpx.AsyncClient | None = None,
)
```

Satisfies the `Backend` protocol. `httpx_client` is optional; if omitted the
backend creates and closes its own client per `fetch_and_persist` call.

### `FetchReport`

Returned by `fetch()` when the backend is `SimpleFINBackend`.

| Field | Type |
|---|---|
| `chunks` | `int` |
| `accounts_seen` | `int` |
| `txns_new` | `int` |
| `txns_duplicate` | `int` |
| `errors` | `list[str]` |

---

## What is NOT public API

- `finstore.backends.simplefin.models` — the `Sf*` types are backend-internal.
  Do not import them; the arch tests will catch violations.
- `finstore_local.*` — the self-hosted app modules. The CLI command shape
  (`finstore fetch`, `finstore serve`, etc.) and dashboard URL paths are
  public surface; the Python modules behind them are not.
- `finstore.storage._schema` — internal schema constants.
- Anything prefixed `_`.
