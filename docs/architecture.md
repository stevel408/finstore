# finstore — Architecture

## Layers

```
┌────────────────────────────────────────────────────────────┐
│                   finstore_local (app)                     │
│   CLI · FastAPI dashboard · EnvCredentialProvider          │
│   Tenant("local") · reads FINSTORE_DATA_DIR                │
└────────────────────────┬───────────────────────────────────┘
                         │ calls
┌────────────────────────▼───────────────────────────────────┐
│                   finstore (core)                          │
│                                                            │
│  finstore.fetch(tenant, backend, storage, window=...)      │
│      thin orchestrator — delegates, doesn't iterate        │
│                                                            │
│  ┌─────────────────┐       ┌──────────────────────────┐   │
│  │  Backend proto  │       │   Storage proto          │   │
│  │  (async)        │       │   (sync)                 │   │
│  └────────┬────────┘       └────────────┬─────────────┘   │
│           │ normalizes to               │ speaks only      │
│           ▼                             ▼                  │
│  finstore.backends.*       finstore.storage.filesystem     │
│  (SimpleFINBackend)        (FilesystemStorage)             │
│           │                                                │
│           └──── finstore.model ────────┘                   │
│                 Account · Transaction · Connection          │
│                 AccountSummary · StorageChunk · Window      │
└────────────────────────────────────────────────────────────┘
                         ▲
                         │ imports finstore only
┌────────────────────────┴───────────────────────────────────┐
│             gnc-sfin-gateway (downstream consumer)         │
│   OFX serve path · reads storage via public API            │
└────────────────────────────────────────────────────────────┘
```

## Three protocols

Defined in `finstore.protocols`. All are `@runtime_checkable`.

### `Credentials`

Empty marker. Each backend defines its own credential dataclass (e.g.
`SimpleFINCredentials(access_url=...)`); credentials are passed to the
backend constructor, not to `fetch()`. The orchestrator never sees them.
Keeping credentials out of `fetch()` means the core has no opinion on how
credentials are stored or rotated — that belongs to the app layer.

### `Backend`

```python
async def fetch_and_persist(
    self,
    storage: Storage,
    *,
    tenant_id: str,
    dtstart_epoch: int,
    dtend_epoch: int | None = None,
) -> Any: ...
```

Async. Backends are I/O-bound; sync would force `run_in_executor` everywhere.
The backend owns its window iteration and merges into storage directly via
`storage.merge_chunk()`. This coarse surface is intentional for 0.1 — a
per-account `fetch_accounts` / `fetch_transactions` split is a non-breaking
addition once a second backend lands.

### `Storage`

```python
def merge_chunk(self, tenant_id: str, chunk: StorageChunk) -> MergeStats: ...
def read_meta(self, tenant_id: str = ...) -> CacheMeta: ...
def resolve_display_id(self, tenant_id: str, display_id: str) -> str: ...
def read_account(self, tenant_id: str, account_id: str) -> CachedAccount: ...
def read_account_window(self, tenant_id: str, account_id: str,
                        dtstart_epoch: int, dtend_epoch: int | None) -> CachedAccount: ...
def list_accounts(self, tenant_id: str = ...) -> tuple[AccountSummary, ...]: ...
```

Sync. `FilesystemStorage` is sync and the gateway's request handlers are sync.
Async storage is a non-breaking later addition (separate method set or subclass).

## The normalization seam

`SimpleFINBackend` is the **only** place where raw SimpleFIN JSON (`Sf*` types)
becomes the neutral `Account` / `Transaction` / `Connection` model. Nothing
outside `finstore.backends.simplefin.*` may import `finstore.backends.simplefin.models`.
The enforcement is in `tests/arch/test_imports.py`.

```
SimpleFIN JSON
  → SfResponse        (finstore.backends.simplefin.models — backend-internal)
  → StorageChunk      (finstore.model — public contract)
  → storage.merge_chunk(tenant_id, chunk)
```

## Import boundary rules

Enforced by AST-walking in `tests/arch/test_imports.py`:

| Rule | Constraint |
|---|---|
| 1 | `finstore.*` may not import `finstore_local.*` |
| 2 | `finstore.model.*` and `finstore.storage.*` may not import `finstore.backends.*` |
| 3 | Outside `finstore.backends.simplefin.*`, no module may import `finstore.backends.simplefin.models` |
| 5 | `finstore_local.web.*` may not import `gateway.*` |
| 6 | No public symbol in any `__all__` references `Sf*` or `finstore_local.*` types |

Rule 4 (gateway-side) lives in `gnc-sfin-gateway/tests/arch/test_imports.py`.

## The `Tenant` seam

Every storage call takes a `tenant_id: str`. The local app always passes
`Tenant(id="local")`; a future cloud variant would derive the id from auth.
`FilesystemStorage` currently ignores the tenant_id (single-tenant layout), but
the signatures are tenant-scoped from day one — retrofitting this later would
be a breaking API change.

## Async/sync split

| Layer | Style | Reason |
|---|---|---|
| `Backend.fetch_and_persist` | `async` | Network I/O via `httpx.AsyncClient` |
| `Storage.*` | sync | File I/O; gateway request handlers are sync |
| `finstore.fetch()` | `async` | Awaits the backend |

## `FilesystemStorage` on-disk layout

Schema version: 4 (owned by `FilesystemStorage`; the Python model is the
public contract, not the file format).

```
<root>/
  meta.json                 # index: schema_version, connections, account stubs
  accounts/
    <conn_id>/              # one directory per institution
      <display_id>.json     # full account + transactions
```

`display_id` is derived from the account name by `sanitize_account_name()` in
`finstore.storage.paths`. Per-account writes are POSIX-atomic (write to a
`.tmp` file, then `os.replace`). `meta.json` is updated last so a crash
mid-fetch never leaves meta pointing at a half-written account file.

## What `finstore_local` adds

`finstore_local` is the self-hosted application layer. It is **not** importable
API — the CLI subcommand shape and dashboard URL paths are public surface; the
Python modules are not.

- `finstore_local.config` — reads `FINSTORE_DATA_DIR`, `SIMPLEFIN_ACCESS_URL`,
  and other env vars. Constructs `SimpleFINCredentials` and `FilesystemStorage`
  with the right path. This is the credential-lookup boundary: the core never
  sees it.
- `finstore_local.cli` — `finstore fetch / serve / accounts / validate / cache reset`
- `finstore_local.web` — FastAPI dashboard: per-account status, fetch trigger,
  validate, cache reset, login screen.
