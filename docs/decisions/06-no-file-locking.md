# 06 — No OS-level file locking

**Decision:** `FilesystemStorage` does not acquire OS-level file locks.

**Rationale:**

The documented invariant is "the local app is the only writer." `finstore fetch`
is a CLI tool run interactively or from cron — not a long-running server with
concurrent writers. OS-level locks (fcntl, lockfile) add complexity and have
platform-specific failure modes (stale locks after crashes, NFS semantics,
Windows semantics).

Per-account writes are POSIX-atomic (`os.replace`) so a crash mid-write
never leaves a corrupt file, only a possibly-missing `.tmp` file. `meta.json`
is updated last, so readers never see meta pointing at a half-written account.

Cloud storage backends (S3, Postgres) handle concurrency at their own layer
(optimistic locking, transactions); they should not inherit the filesystem's
single-writer assumption.

**Consequence:** Running two concurrent `finstore fetch` invocations against
the same directory is undefined behavior. Document this clearly; don't add
a lock to paper over it.
