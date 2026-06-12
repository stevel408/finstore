# Testing guide

## Overview

The test suite is divided into three layers, each with a distinct purpose and a different cost to run:

| Layer | Location | Speed | Network | Run by default |
|---|---|---|---|---|
| Unit | `tests/unit/` | Fast | No | Yes |
| Architecture | `tests/arch/` | Fast | No | Yes |
| End-to-end | `tests/e2e/` | Slow | Yes | No |

---

## Unit tests (`tests/unit/`)

The bulk of the test suite. Each test covers a single module or component in
isolation — no real network calls, no real filesystem beyond pytest's `tmp_path`.

**Coverage areas:**

- `tests/unit/store/` — `FilesystemStorage` read/write/merge/validate, path
  construction, and account-name sanitisation
- `tests/unit/simplefin/` — SimpleFIN backend: `Sf*` → model normalisation,
  window iteration, errlist filtering, `FetchReport` assembly; HTTP layer via
  `pytest-httpx`
- `tests/unit/api/` — Protocol-level tests using fake `Backend` and `Storage`
  implementations; verify that `finstore.fetch` works end-to-end without any
  real I/O
- `tests/unit/finstore_local/` — Config resolution, job registry, dashboard
  middleware

**Key conventions:**

- Use `pytest-httpx` to mock the SimpleFIN HTTP layer. Never hit the real
  `bridge.simplefin.org` in unit tests.
- The `tmp_cache` fixture (in `tests/conftest.py`) gives a `Path` that does not
  yet exist — use it for tests that create the cache themselves.
- Protocol fakes live in `tests/unit/api/test_protocols.py`. If a fake cannot
  satisfy the protocol, the protocol needs fixing — not the fake.

```bash
pytest tests/unit/          # all unit tests
pytest tests/unit/store/test_writer.py   # single file
pytest tests/unit/ -k "merge"            # filter by name
```

---

## Architecture tests (`tests/arch/`)

AST-walking tests that enforce the import boundary rules without importing any
of the modules under test. They run in milliseconds and catch layering
violations as soon as a file is saved.

**Rules enforced:**

1. `finstore.*` may not import `finstore_local.*`
2. `finstore.model.*` and `finstore.storage.*` may not import `finstore.backends.*`
3. `Sf*` types are confined to `finstore.backends.simplefin.*` — no other
   module may import `finstore.backends.simplefin.models`
4. `finstore_local.web.*` may not import `gateway.*`
5. No public symbol in `finstore.*` references `Sf*` or `finstore_local.*` types

Run these immediately after adding a new module or import:

```bash
pytest tests/arch/
```

---

## End-to-end tests (`tests/e2e/`)

Smoke tests that exercise the real CLI binary against real network calls. Each
test spins up a subprocess, points it at a temporary data directory, and
verifies exit codes and output. Nothing is mocked.

**What they cover (`tests/e2e/test_demo_flow.py`):**

- `finstore setup --demo` fetches a token from SimpleFIN, exchanges it, and
  writes `credentials.json` with mode `0600`
- `finstore fetch` uses saved credentials to pull data and populate storage
- `finstore accounts` lists the fetched accounts
- `finstore fetch` without prior setup fails with a clear error pointing to
  `finstore setup`

**How isolation works:**

Each test gets its own `tmp_path`. The helper passes `GNC_SFIN_CACHE_DIR` and
`--env-file` (pointing at a blank file in `tmp_path`) to the subprocess, so
no real credentials or project `.env` values can bleed in.

**Running:**

```bash
RUN_E2E=1 pytest tests/e2e/ -v
```

Without `RUN_E2E=1`, every test in this directory is skipped — so they never
block a normal `pytest tests/` run or CI.

**When to run:** before a release, after changes to the CLI setup/fetch flow,
or whenever you want confidence that the full user journey works against the
live SimpleFIN demo.

---

## Running everything

```bash
# Fast feedback loop (unit + arch, no network)
pytest tests/unit/ tests/arch/

# Full suite including e2e
RUN_E2E=1 pytest tests/unit/ tests/arch/ tests/e2e/ -v
```

## Linting and type checking

These are not part of the test suite but should be clean before committing:

```bash
ruff check src/ tests/
mypy src/finstore src/finstore_local
```
