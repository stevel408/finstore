from __future__ import annotations

import asyncio
import base64
import re
import sys


def run(
    token: str | None = None,
    demo: bool = False,
    env_file: str | None = None,
) -> None:
    import httpx

    from finstore.backends.simplefin import activate
    from finstore.exceptions import BackendError
    from finstore.storage.filesystem import FilesystemStorage
    from finstore_local.config import load_settings, resolve_data_dir

    if demo and token:
        print("ERROR: provide either a setup token or --demo, not both.", file=sys.stderr)
        raise SystemExit(2)

    if demo:
        token = _fetch_demo_token()

    if not token:
        print(
            "ERROR: provide a setup token or use --demo.\n"
            "Get a demo token at: https://beta-bridge.simplefin.org/info/developers",
            file=sys.stderr,
        )
        raise SystemExit(2)

    settings = load_settings(env_file)
    data_dir = resolve_data_dir(settings, create=True)
    storage = FilesystemStorage(root=data_dir)

    secret = token

    print("Exchanging setup token with SimpleFIN...", end=" ", flush=True)

    async def _activate() -> None:
        async with httpx.AsyncClient() as client:
            await activate(secret, storage=storage, tenant_id="local", client=client)

    try:
        asyncio.run(_activate())
    except BackendError as exc:
        print(f"FAILED\nERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)

    print("OK")
    print(f"Credentials saved to: {data_dir}")
    if demo:
        print("Note: demo credentials — transactions are fictional sample data.")
    print("Run 'finstore fetch' to pull data.")


def _fetch_demo_token() -> str:
    """Fetch a fresh demo setup token from the SimpleFIN developer page.

    Demo tokens are regenerated on every page load, so this always returns
    a claimable token. Fails with a clear message if the page format changes.
    """
    import httpx

    url = "https://beta-bridge.simplefin.org/info/developers"
    print("Fetching demo token from SimpleFIN...", end=" ", flush=True)
    try:
        r = httpx.get(url, timeout=10.0)
        r.raise_for_status()
    except httpx.RequestError as exc:
        print(f"FAILED\nERROR: could not reach SimpleFIN: {exc}", file=sys.stderr)
        raise SystemExit(1)

    # Demo tokens appear as base64 blobs on the page. Find the first one that
    # decodes to a https:// URL — that is the claim URL encoded as a setup token.
    for match in re.findall(r"[A-Za-z0-9+/\-_]{40,}={0,2}", r.text):
        candidate: str = match
        for decoder in (base64.b64decode, base64.urlsafe_b64decode):
            try:
                decoded = decoder(candidate + "==").decode("utf-8", errors="strict")
                if decoded.startswith("https://"):
                    print("OK")
                    return candidate
            except Exception:
                continue

    print(
        "FAILED\n"
        "ERROR: could not extract a demo token from the SimpleFIN developer page.\n"
        f"Visit {url} to copy a demo token, then run: finstore setup <token>",
        file=sys.stderr,
    )
    raise SystemExit(1)
