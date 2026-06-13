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

**Activating a backend** — use `activate()` to handle the SimpleFIN credential
bootstrap in one call. It auto-detects whether the secret is a setup token
(requiring a one-time exchange) or a ready access URL, persists the result via
`Storage`, and returns a wired backend:

```python
import asyncio
import os
import time
from pathlib import Path

import httpx

from finstore import Tenant, fetch
from finstore.backends.simplefin import activate
from finstore.exceptions import BackendError
from finstore.storage.filesystem import FilesystemStorage

tenant  = Tenant(id="local")
storage = FilesystemStorage(root=Path("~/.local/share/finstore").expanduser())
dtstart = int(time.time()) - 90 * 86400  # last 90 days

async def main() -> None:
    async with httpx.AsyncClient() as http_client:
        # Pass the secret on first run; pass None on subsequent runs to load
        # the persisted credential from storage.
        secret = os.environ.get("SIMPLEFIN_SECRET")
        try:
            backend = await activate(
                secret, storage=storage, tenant_id=tenant.id, client=http_client
            )
        except BackendError as exc:
            raise RuntimeError("SimpleFIN activation failed") from exc

        await fetch(tenant, backend, storage, window=(dtstart, None))

    accounts = storage.list_accounts(tenant.id)

asyncio.run(main())
```

`SIMPLEFIN_SECRET` is the base64-encoded setup token from SimpleFIN — see the
[SimpleFIN developer docs](https://beta-bridge.simplefin.org/info/developers)
for how to obtain one. After the first `activate()` call the access URL is
persisted in `storage`; subsequent calls can pass `secret=None`.

See [docs/api-reference.md](docs/api-reference.md) for the full public API.

---

## For contributors

See [docs/contributing.md](docs/contributing.md) for setup, running tests, linting, and CLI usage.

## License

Apache-2.0
