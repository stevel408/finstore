# 04 — `tenant_id` in every storage method

**Decision:** Every `Storage` method takes `tenant_id: str` as its first
argument. The local app always passes `Tenant(id="local")`.

**Rationale:**

`FilesystemStorage` currently ignores the tenant_id (single-tenant on-disk
layout), but the signatures are tenant-scoped from day one. Retrofitting
`tenant_id` into an already-published `Storage` protocol signature would be a
breaking API change — every existing `Storage` implementation and every call
site would need updating.

The cost in the local case is exactly one string argument. The benefit is that
a cloud storage backend can provide tenant isolation without any protocol
changes.

**Consequence:** Never hardcode `"local"` in the core or in storage
implementations. `finstore_local` owns the policy of passing `Tenant(id="local")`.
