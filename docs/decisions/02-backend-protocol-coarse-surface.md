# 02 — `fetch_and_persist` coarse surface for 0.1

**Decision:** `Backend` exposes one method, `fetch_and_persist(storage, *, tenant_id,
dtstart_epoch, dtend_epoch)`, which owns its own window iteration and merges
into storage directly. A finer `fetch_accounts` / `fetch_transactions` split is
deferred.

**Rationale:**

SimpleFIN's API returns all accounts and their transactions in a single
response. Splitting into per-account calls would require the orchestrator to
manage chunking, retry, and partial-failure logic — complexity that the backend
already handles and that has no concrete second backend to validate against.

The coarse surface is shaped against two conceptual backends (SimpleFIN and a
hypothetical CSV import) to ensure the abstraction isn't entirely SimpleFIN-shaped,
but only SimpleFIN ships at 0.1.

**Consequence:** The first second backend may require a breaking change to the
`Backend` protocol if its fetch model genuinely doesn't fit `fetch_and_persist`.
This is accepted risk, mitigated by keeping the return type `Any` so the
orchestrator can remain ignorant of backend-specific report shapes.
