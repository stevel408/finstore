# 13 — Credentials stored in the data directory via `Storage`, not in `.env`

**Decision:** `finstore setup <token>` exchanges a SimpleFIN setup token for an
access URL and persists it via `Storage.write_backend_credential()`. The reference
`FilesystemStorage` implementation writes it to
`{data_dir}/tenants/{tenant_id}/credentials/simplefin.bin` (mode 0o600).
The access URL is resolved at runtime in the following priority order:

1. `SIMPLEFIN_ACCESS_URL` env var — escape hatch for CI, Docker, and power users.
2. `Storage.read_backend_credential("local", "simplefin")` — written by `finstore setup`.
3. Hard error: no credentials configured.

**Rationale:**

The setup token → access URL exchange is a one-time, irreversible HTTP POST.
The result is a secret the application acquires and must persist — it is not a
value a user edits. Writing it back to `.env` is awkward for two reasons:

- `.env` files are hand-edited config; round-tripping them programmatically
  (preserving comments, avoiding duplicate keys) is fragile.
- `pipx install` users have no project directory and therefore no natural `.env`
  location. The data directory (`platformdirs.user_data_dir`) exists
  unconditionally once `finstore setup` runs.

Using `Storage` as the persistence layer (rather than a separate credentials file)
keeps the abstraction consistent: `FilesystemStorage` owns all persistent state for
a tenant, and downstream consumers (e.g. `gnucash-connect`) can call
`simplefin.activate(secret, storage=..., tenant_id=...)` without knowing how or
where credentials are stored.

The data directory already has `0o700` permissions set by `resolve_data_dir`,
so a credential file with `0o600` permissions is no more exposed than the cached
transaction data sitting beside it.

**Single-tenant constraint (explicitly deferred):**

`finstore_local` always passes `tenant_id="local"`. There is no per-user or
per-tenant credentials slot in the CLI. This mirrors the existing single-tenant
constraint of `FilesystemStorage` (see ADR 04): a single data directory holds one
user's data.

A multi-tenant deployment (e.g. a hosted service where each end-user has their own
SimpleFIN account) would use the same `write_backend_credential` / `read_backend_credential`
API with different `tenant_id` values, backed by a multi-tenant `Storage` implementation.
That design is out of scope for `finstore_local` and would live in a separate
cloud-variant app layer (see ADR 12). The `finstore` core is unaffected: it already
accepts a `Credentials` object at construction time and never looks up secrets itself
(see ADR 07).

**Consequence:** The `finstore setup` command must call `resolve_data_dir` with
`create=True` because it runs before any `fetch` has created the directory.
Existing users with `SIMPLEFIN_ACCESS_URL` in `.env` continue to work
unchanged — the env var takes priority.
