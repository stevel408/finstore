# 07 — Credential lookup belongs to the app layer

**Decision:** The core (`finstore.*`) has no credential lookup, no `.env`
reading, no secrets manager integration. `finstore_local.config` provides
`EnvCredentialProvider`-style logic and constructs the credential object
before passing it to the backend constructor.

**Rationale:**

Credential storage differs by deployment: the local app reads from `.env` /
environment variables; a cloud deployment reads from a secrets manager or
a per-user secrets table; a CI test injects a dummy credential directly.

If the core handled credential lookup, every deployment would fight the core's
assumptions about where secrets live. Keeping lookup in the app layer means the
core can be used without `.env` support, without `pydantic-settings`, and
without any particular secret store — just construct a credential object and
hand it to the backend.

**Consequence:** `pydantic-settings` is a `[local]` extra dependency, not a
base dependency. Code in `finstore.*` never calls `os.environ` for credentials.
