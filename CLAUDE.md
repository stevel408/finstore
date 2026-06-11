# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Working agreements

- **Do not commit without an explicit request from the user.**
- Commit messages must not include a `Co-Authored-By` tag.

## Commands

```bash
# Install (requires Python 3.11+)
uv venv && source .venv/bin/activate && uv pip install -e ".[dev]"

# Tests
pytest tests/unit/          # unit tests only
pytest tests/arch/          # import boundary invariants
pytest tests/               # everything
pytest tests/unit/store/test_writer.py  # single file

# Lint / type-check
ruff check src/ tests/
mypy src/finstore src/finstore_local
```

## Architecture

Two packages share one `src/` tree:

- **`finstore`** — the public library. Backend-agnostic; no app-layer imports allowed.
- **`finstore_local`** — the self-hosted CLI + dashboard. Imports `finstore`; not importable as API.

Data flow: `SimpleFINBackend` fetches from the SimpleFIN HTTP API → normalizes `Sf*` types into neutral `finstore.model` types → calls `FilesystemStorage.merge_chunk()` to persist atomically per account.

### Import boundaries (enforced by `tests/arch/`)

1. `finstore.*` must not import `finstore_local.*`
2. `finstore.model.*` and `finstore.storage.*` must not import `finstore.backends.*`
3. `Sf*` types are confined to `finstore.backends.simplefin.*` — they never cross the normalization seam in `backend.py`

### Key design points

**Normalization seam** — `SimpleFINBackend` in `backends/simplefin/backend.py` is the only place `Sf*` → model conversion happens. `models.py` holds raw SimpleFIN shapes; `client.py` is pure HTTP and returns `SfResponse`; `backend.py` converts and persists.

**Protocols** — `Backend`, `Storage`, and `Credentials` in `finstore/protocols.py` define the contract. `SimpleFINBackend` and `FilesystemStorage` satisfy them structurally. `Credentials` is an empty marker; each backend defines its own frozen dataclass.

**Tenant scoping** — every `Storage` method accepts `tenant_id: str`. `FilesystemStorage` is single-tenant and ignores it (all data lands under the same root), but the parameter must be threaded through — never hardcode `"local"` outside `finstore_local`.

**`finstore_local` settings** — use `load_settings(env_file)` from `finstore_local.config` in all CLI commands. It returns the cached singleton when `env_file` is `None` and constructs a fresh instance for an alternate env file. Do not call `get_settings()` directly in CLI commands.
