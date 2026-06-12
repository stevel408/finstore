# 13 — Credentials stored in the data directory, not in `.env`

**Decision:** `finstore setup <token>` exchanges a SimpleFIN setup token for an
access URL and writes it to `{data_dir}/credentials.json` (mode 0o600). The
access URL is resolved at runtime in the following priority order:

1. `SIMPLEFIN_ACCESS_URL` env var — escape hatch for CI, Docker, and power users.
2. `{data_dir}/credentials.json` — written by `finstore setup`.
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

The data directory already has `0o700` permissions set by `resolve_data_dir`,
so a `credentials.json` file with `0o600` permissions is no more exposed than
the cached transaction data sitting beside it.

**Single-tenant constraint (explicitly deferred):**

`credentials.json` stores one set of credentials — one SimpleFIN access URL.
There is no per-user or per-tenant credentials slot. This mirrors the existing
single-tenant constraint of `FilesystemStorage` (see ADR 04): a single data
directory holds one user's data.

A multi-tenant deployment (e.g. a hosted service where each end-user has their
own SimpleFIN account) would need a different credentials store — one record
per `tenant_id`, backed by a secrets manager or a per-user encrypted store.
That design is out of scope for `finstore_local` and would live in a separate
cloud-variant app layer (see ADR 12). The `finstore` core is unaffected: it
already accepts a `Credentials` object at construction time and never looks up
secrets itself (see ADR 07).

**Consequence:** The `finstore setup` command must call `resolve_data_dir` with
`create=True` because it runs before any `fetch` has created the directory.
Existing users with `SIMPLEFIN_ACCESS_URL` in `.env` continue to work
unchanged — the env var takes priority.
