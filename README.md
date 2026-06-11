# finstore

Backend-agnostic local repository of a user's financial data.

## Install

```bash
# Library only (for custom integrations / the gnc-sfin-gateway OFX server)
pip install finstore

# Library + SimpleFIN backend
pip install finstore[simplefin]

# Self-hosted CLI + dashboard (end users)
pipx install 'finstore[local]'
```

## Quick start

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

## License

Apache-2.0
