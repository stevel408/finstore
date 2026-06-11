# 03 — `Credentials` as empty marker, not generic

**Decision:** `Credentials` is an empty `@runtime_checkable` `Protocol` (a
marker). Backends accept their specific credential type in `__init__`; the
`fetch_and_persist` method takes no credential argument.

**Rationale:**

Credential shapes differ fundamentally across backends: SimpleFIN uses a
single access URL; Plaid uses client_id + secret + access_token; OAuth
backends need a refresh cycle. A generic `Backend[CredT]` would surface
credential types at the `fetch()` call site, forcing callers to know the
concrete backend type and making the `Backend` protocol itself harder to
satisfy structurally.

By putting credentials on the constructor, each backend encapsulates its
auth state. `finstore_local` resolves credentials from env and passes them
at construction time; the orchestrator (`fetch()`) never touches them.
`isinstance(creds, Credentials)` passes for any object (empty protocol), which
is a mild type-safety loss accepted in exchange for simplicity.

**Consequence:** The generic form (`Backend[CredT]`) is a non-breaking change
later if a second backend makes credential mismatches a real problem in
practice.
