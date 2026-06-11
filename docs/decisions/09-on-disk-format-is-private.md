# 09 — On-disk format is a storage implementation detail

**Decision:** The JSON on-disk layout of `FilesystemStorage` (field names,
directory structure, `meta.json` shape) is **not** public API. It is owned
entirely by `FilesystemStorage` and may change between releases without a major
version bump, as long as `FilesystemStorage` handles its own migration.

**Rationale:**

The Python data model (`Account`, `Transaction`, etc.) is the public contract.
Locking the on-disk format as public API would make every storage layout
decision a breaking change and prevent internal improvements (compression,
index files, alternate encodings).

**Consequence:**

- Do not parse `~/.local/share/finstore/` files outside of `FilesystemStorage`.
- Schema version is tracked in `meta.json` (`schema_version` field). A
  `CacheSchemaMismatchError` is raised on a version mismatch so callers know
  to re-fetch rather than silently reading stale data.
- `FilesystemStorage` is responsible for detecting and running its own
  migrations if it needs to evolve the on-disk format.
