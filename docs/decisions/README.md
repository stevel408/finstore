# Design decisions

These records capture settled decisions so future maintainers don't relitigate
them. Each file names the decision, the rationale, and the consequence.

| # | Decision |
|---|---|
| [01](01-async-backends-sync-storage.md) | Async backends, sync storage |
| [02](02-backend-protocol-coarse-surface.md) | `fetch_and_persist` coarse surface for 0.1 |
| [03](03-credentials-as-empty-marker.md) | `Credentials` as empty marker, not generic |
| [04](04-tenant-in-every-storage-call.md) | `tenant_id` in every storage method |
| [05](05-filesystem-storage-in-core.md) | `FilesystemStorage` ships in core, not `[local]` |
| [06](06-no-file-locking.md) | No OS-level file locking |
| [07](07-no-credential-lookup-in-core.md) | Credential lookup belongs to the app layer |
| [08](08-normalization-seam.md) | Backend is the only normalization boundary |
| [09](09-on-disk-format-is-private.md) | On-disk format is a storage implementation detail |
| [10](10-apache-2-license.md) | Apache-2.0 license |
| [11](11-cancellation-propagate-partial-writes-kept.md) | Cancellation semantics |
| [12](12-cloud-variant-not-in-this-repo.md) | Cloud variant is out of scope for 0.1 |
