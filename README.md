# finstore

Backend-agnostic local repository of a user's financial data.

finstore serves two audiences:

- **End users** — run the self-hosted CLI and dashboard to view your own finances.
- **Developers** — embed finstore in a larger application (e.g. an OFX server).

---

## For end users

An *end user* is someone who wishes to build a personal environment to fetch and manage their own financial data. Such a user would use this `finstore` Python package to set up data connections to their own bank accounts, then fetch and maintain account and transaction data in a local data store.

Install the CLI and dashboard:

```bash
pipx install 'finstore[local]'
```

**Step 1 — connect SimpleFIN:**

SimpleFIN uses a one-time setup token to grant access. Get yours from
[beta-bridge.simplefin.org](https://beta-bridge.simplefin.org/simplefin/create),
then exchange it for a saved access URL:

```bash
finstore setup <your-setup-token>
```

The SimpleFIN access URL grants full read access to your account and transaction data and should be treated like a password. finstore saves it to a file readable only by your user account (`credentials.json`, mode 0600) and never transmits it anywhere other than to SimpleFIN itself.

To try it first with fictional demo data (no account needed):

```bash
finstore setup --demo
```

**Step 2 — pull data and open the dashboard:**

```bash
finstore fetch --start 2026-01-01   # backfill from a date; omit for incremental
finstore serve                       # dashboard at http://127.0.0.1:8081
```

The access URL is saved locally — you only run `finstore setup` once.
See `finstore --help` for all commands.

---

## For developers

A *developer* is someone building an application that needs to store and query financial data — for example, an OFX server, a budgeting tool, or a reporting pipeline. They use `finstore` as a dependency, wiring up their own backend and storage configuration rather than using the CLI.

Install the core library, optionally with the SimpleFIN backend:

```bash
pip install finstore                 # core only
pip install 'finstore[simplefin]'   # core + SimpleFIN backend
```

```python
import asyncio
import time
from pathlib import Path

import httpx

from finstore import Tenant, fetch
from finstore.backends.simplefin import SimpleFINBackend, SimpleFINCredentials
from finstore.storage.filesystem import FilesystemStorage

tenant  = Tenant(id="local")
storage = FilesystemStorage(root=Path("~/.local/share/finstore").expanduser())
creds   = SimpleFINCredentials(access_url="https://user:pass@bridge.simplefin.org/simplefin")

dtstart = int(time.time()) - 90 * 86400  # last 90 days

async def main() -> None:
    async with httpx.AsyncClient() as http_client:
        backend = SimpleFINBackend(credentials=creds, httpx_client=http_client)
        await fetch(tenant, backend, storage, window=(dtstart, None))

    accounts = storage.list_accounts(tenant.id)

asyncio.run(main())
```

See [docs/api-reference.md](docs/api-reference.md) for the full public API.

---

## For contributors

See [docs/contributing.md](docs/contributing.md) for setup, running tests, linting, and CLI usage.

## License

Apache-2.0
