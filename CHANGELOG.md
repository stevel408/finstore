# Changelog

## [Unreleased]

### Added
- Initial extraction from `gnc-sfin-gateway`.
- `finstore` core library: `Tenant`, `fetch()`, `Backend`/`Storage`/`Credentials` protocols,
  `Account`/`Transaction`/`Connection`/`AccountSummary`/`Window` data model,
  `FilesystemStorage` reference implementation, exception hierarchy rooted at `FinstoreError`.
- `finstore[simplefin]` extra: `SimpleFINBackend`, `SimpleFINCredentials`, `FetchReport`.
- `finstore[local]` extra: `finstore_local` self-hosted CLI (`fetch`, `serve`, `accounts`,
  `validate`, `cache reset`) and FastAPI dashboard.
