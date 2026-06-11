# 11 — Cancellation: propagate `CancelledError`, keep partial writes

**Decision:** `finstore.fetch()` propagates `asyncio.CancelledError` to the
caller without suppression. Any `storage.merge_chunk()` calls that completed
before cancellation remain on disk; the in-flight chunk is dropped. No rollback
is attempted.

**Rationale:**

The alternative — rolling back partial writes on cancellation — requires
either transactional storage (out of scope for `FilesystemStorage`) or
pre-computing the full write set before touching disk (incompatible with the
streaming `fetch_and_persist` model where accounts are merged as they arrive).

Partial writes are safe in practice: each `merge_chunk` call writes
complete, consistent account files. A cancelled fetch leaves storage with
a subset of the intended accounts written — which is correct data, just
incomplete. The next fetch starting from the same window will fill in what
was missed. `last_fetch_at` in `meta.json` is updated inside `merge_chunk`,
so the partially-written state is accurately reflected.

**Consequence:** Callers that cancel `fetch()` will see `CancelledError`.
Storage is left in a valid but possibly incomplete state. This is tested in
`tests/unit/api/test_protocols.py::TestCancellation`.
