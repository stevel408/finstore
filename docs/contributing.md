# Contributing to finstore

## Setup

```bash
git clone https://github.com/you/finstore
cd finstore
uv venv
source .venv/bin/activate
uv pip install -e ".[dev]"
```

Python 3.11+ required.

## Running tests

```bash
# Unit tests (no network, no disk I/O beyond tmp dirs)
pytest tests/unit/

# Architecture invariant tests (AST-walking import rules)
pytest tests/arch/

# All unit + arch tests
pytest tests/unit/ tests/arch/

# End-to-end smoke tests (requires network; hits real SimpleFIN demo)
RUN_E2E=1 pytest tests/e2e/ -v
```

See [docs/testing.md](testing.md) for a full description of the three test layers and their conventions.

## Linting and type checking

```bash
ruff check src/ tests/
mypy src/finstore src/finstore_local
```

## Running locally

The `[dev]` extra already includes everything needed.

**First-time setup** — exchange a SimpleFIN setup token for an access URL:

```bash
finstore setup <your-setup-token>   # real account
finstore setup --demo               # fictional demo data, no account needed
```

The access URL is saved to `{data_dir}/credentials.json` (not `.env`). You can
also override it at any time by setting `SIMPLEFIN_ACCESS_URL` in `.env`, which
takes priority over the saved file.

Populate the local cache, then start the dashboard:

```bash
finstore fetch --start 2026-01-01   # pull data from SimpleFIN
finstore serve                       # start dashboard at http://127.0.0.1:8081
```

Other commands:

```bash
finstore accounts    # list cached accounts
finstore validate    # check cache for violations
finstore cache reset # wipe cache (or --account <id> for one entry)
```

---

## Code discipline

### `__all__` and `py.typed`

finstore is a typed library (`py.typed` marker is present). Every public
module must define `__all__`. If a symbol isn't in `__all__` it's private,
even if it has no leading underscore. The arch test `test_public_surface_has_no_sf_or_finstore_local_types`
enforces this: anything in `__all__` that starts with `Sf` or is defined in
`finstore_local.*` is a violation.

When adding a new public symbol:
1. Add it to `__all__` in the module.
2. Re-export it from the relevant package `__init__.py` if it's part of the
   package's public surface.
3. Add it to `docs/api-reference.md`.

### Import boundary rules

Five rules are enforced by `tests/arch/test_imports.py`. A brief summary:

1. `finstore.*` may not import `finstore_local.*`
2. `finstore.model.*` and `finstore.storage.*` may not import `finstore.backends.*`
3. `Sf*` types (`finstore.backends.simplefin.models`) are confined to the
   `finstore.backends.simplefin.*` package
5. `finstore_local.web.*` may not import `gateway.*`
6. No public symbol references `Sf*` or `finstore_local.*` types

If you add a new module, run `pytest tests/arch/` immediately. The tests
walk the actual source tree so they catch violations without needing to
import anything.

### The normalization seam

`SimpleFINBackend` is the **only** constructor of normalized `Account` /
`Transaction` / `Connection` from `Sf*` types. If you're touching the
SimpleFIN backend:

- `models.py` — raw SimpleFIN shapes (`SfAccount`, `SfTransaction`, etc.).
  These never leave the package.
- `backend.py` — converts `Sf*` → model types. The conversion functions
  (`_normalize`, `_to_account`, `_to_connection`, `_to_transaction`) are
  the seam. Keep them pure (no I/O).
- `client.py` — HTTP layer. Returns `SfResponse`; has no knowledge of the
  normalized model.

### Credentials

Backends take credentials in their constructor, not in `fetch()`. `finstore_local.config`
resolves credentials from env and passes them at construction time. The core
never sees the lookup mechanism. If you're adding a backend, define a frozen
dataclass that structurally satisfies `Credentials` (empty marker, so any
dataclass does) and accept it in `__init__`.

### Tenant

Every storage call takes `tenant_id: str`. `FilesystemStorage` currently
ignores it (single-tenant layout), but the signatures must stay tenant-scoped
— removing the parameter would be a breaking API change and breaks the
design-for-cloud contract. Always pass `tenant.id` through; never hardcode
`"local"` outside `finstore_local`.

### Adding a new backend

1. Create `finstore/backends/<name>/` with `__init__.py`, `models.py`,
   `backend.py`, `client.py` (or fewer files if simpler).
2. `backend.py` must satisfy the `Backend` protocol structurally.
3. Credentials go in a frozen dataclass in `backend.py` or a separate
   `credentials.py`.
4. Add `[<name>]` extra to `pyproject.toml`.
5. `models.py` is backend-internal — do not export `Sf*`-style types.
6. The first second backend may require a small breaking change to `Backend`
   if the coarse `fetch_and_persist` surface is insufficient. That's
   accepted risk; see `docs/decisions/02-backend-protocol-coarse-surface.md`.

---

## Testing conventions

- Unit tests go under `tests/unit/`. No network, no real filesystem beyond
  `tmp_path`.
- Arch tests go under `tests/arch/`. They AST-walk source files; don't import
  the modules under test.
- Protocol-level tests (`tests/unit/api/test_protocols.py`) use fake
  `Storage` and `Backend` implementations. If the fake can't satisfy the
  protocol, the protocol needs fixing.
- `pytest.fixture tmp_cache` (in `conftest.py`) gives a `Path` that doesn't
  exist yet — it's for tests that create the cache themselves.
- Use `pytest-httpx` to mock the SimpleFIN HTTP layer in backend tests; never
  hit the real `bridge.simplefin.org` in unit tests.

## Versioning

finstore follows semantic versioning.

- **Patch** — bug fixes, internal refactors, adding optional fields to existing
  model types.
- **Minor** — new public symbols, new optional constructor parameters,
  non-breaking additions to the `Storage` or `Backend` protocol surface.
- **Major** — removing or renaming public symbols, changing method signatures,
  restructuring the model, adding required parameters.

The CLI command shape (`finstore <subcommand> --flag`) and dashboard URL paths
are public surface and follow the same rules.
