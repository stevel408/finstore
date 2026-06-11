# 01 — Async backends, sync storage

**Decision:** `Backend.fetch_and_persist` is `async def`. `Storage` methods are
all synchronous.

**Rationale:**

Backends perform network I/O. The existing gateway is async end-to-end via
`httpx.AsyncClient`. A sync backend interface would force every consumer to
wrap calls in `asyncio.run` or `loop.run_in_executor`, which loses the
concurrency benefit and adds boilerplate.

Storage is file I/O on a local disk. `FilesystemStorage` is inherently
synchronous (standard `open` / `os.replace`), and the gateway's OFX request
handlers are sync. Async storage is a non-breaking addition later (separate
method set or subclass) if a storage backend with genuine async I/O (S3,
Postgres) is added.

**Consequence:** `finstore.fetch()` is `async def` because it awaits the
backend. Callers must `await fetch(...)` or use `asyncio.run(fetch(...))`.
