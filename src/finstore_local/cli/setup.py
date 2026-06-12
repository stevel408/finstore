from __future__ import annotations

import base64
import re
import sys


def run(
    token: str | None = None,
    demo: bool = False,
    env_file: str | None = None,
) -> None:
    import httpx

    from finstore_local import credentials
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

    claim_url = _decode_token(token)

    # POST to claim URL — one-shot and irreversible.
    print("Exchanging setup token with SimpleFIN...", end=" ", flush=True)
    try:
        response = httpx.post(claim_url, timeout=15.0)
        response.raise_for_status()
        access_url = response.text.strip()
    except httpx.HTTPStatusError as exc:
        print(f"FAILED\nERROR: SimpleFIN returned HTTP {exc.response.status_code}", file=sys.stderr)
        raise SystemExit(1)
    except httpx.RequestError as exc:
        print(f"FAILED\nERROR: network error: {exc}", file=sys.stderr)
        raise SystemExit(1)

    if not access_url.startswith("https://"):
        print(
            f"FAILED\nERROR: unexpected response from SimpleFIN: {access_url!r}",
            file=sys.stderr,
        )
        raise SystemExit(1)

    settings = load_settings(env_file)
    data_dir = resolve_data_dir(settings, create=True)
    credentials.save(data_dir, access_url)

    print("OK")
    print(f"Credentials saved to: {data_dir / 'credentials.json'}")
    if demo:
        print("Note: demo credentials — transactions are fictional sample data.")
    print("Run 'finstore fetch' to pull data.")


def _decode_token(token: str) -> str:
    """Base64-decode a setup token and return the claim URL."""
    # SimpleFIN tokens may use standard or URL-safe base64; add padding.
    padded = token.strip() + "=="
    try:
        claim_url = base64.b64decode(padded).decode()
    except Exception:
        try:
            claim_url = base64.urlsafe_b64decode(padded).decode()
        except Exception as exc:
            print(f"ERROR: could not decode setup token: {exc}", file=sys.stderr)
            raise SystemExit(2)

    if not claim_url.startswith("https://"):
        print(
            f"ERROR: decoded token is not a valid https claim URL: {claim_url!r}",
            file=sys.stderr,
        )
        raise SystemExit(2)

    return claim_url


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
