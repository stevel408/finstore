# 12 — Cloud variant is out of scope for 0.1

**Decision:** finstore 0.1 ships only the local self-hosted app. A multi-tenant
cloud variant is designed for (the `tenant_id` seam, the `Storage` protocol,
the credential-lookup boundary) but is not built here and is not mentioned in
the public README.

**Rationale:**

Building both in one repo produces a codebase that is worse at both jobs:
local users pay for tenant-isolation complexity they don't need; cloud
deployment inherits "one user, files on disk" assumptions it has to fight.
A separate cloud repo importing `finstore` as a library gets exactly the seams
it needs without the local-app baggage.

The accepted risk is that designing-for-cloud without building it may produce
one abstraction that turns out to be wrong. The mitigations:
- Only add seams with concrete justification in the current local app.
  `Tenant` justifies itself (retrofitting `tenant_id` into signatures later is
  a breaking change); an `EventBus` for hypothetical audit logging does not.
- The first cloud implementation will surface any protocol misfits quickly,
  and the version is still pre-1.0 so a breaking change is acceptable.

**Consequence:** The public README, CHANGELOG, and issue tracker stay 100%
local self-hosting focused. Cloud architecture questions go in the cloud repo.
