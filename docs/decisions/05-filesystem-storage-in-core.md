# 05 — `FilesystemStorage` ships in core, not `[local]`

**Decision:** `FilesystemStorage` is part of the base `finstore` package, not
the `[local]` extra.

**Rationale:**

Every consumer needs it: the gateway (`pip install finstore`) reads account
data from storage to serve OFX responses; custom integrations want to write
data via their own fetch scripts; `finstore[local]` installs the CLI and
dashboard on top of the same storage implementation.

If `FilesystemStorage` were in `[local]`, the gateway would have to declare a
dependency on `finstore[local]` — pulling in `typer`, `fastapi`, `uvicorn`,
`jinja2`, and the dashboard templates for a process that only serves OFX
requests and never touches a CLI or a web UI.

**Consequence:** `platformdirs` (used by `FilesystemStorage` for path
resolution) is a base dependency, not an extras dependency.
