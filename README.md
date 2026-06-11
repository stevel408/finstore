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
from finstore import fetch, Tenant
from finstore.backends.simplefin import SimpleFINBackend, SimpleFINCredentials
from finstore.storage.filesystem import FilesystemStorage

tenant  = Tenant(id="local")
backend = SimpleFINBackend()
storage = FilesystemStorage(path="~/.local/share/finstore")
creds   = SimpleFINCredentials(access_url="https://...")

await fetch(tenant, backend, storage, window=(dtstart_epoch, None))
accounts = storage.list_accounts(tenant.id)
```

## License

Apache-2.0
