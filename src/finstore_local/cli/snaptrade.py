"""SnapTrade onboarding CLI commands.

Three subcommands under ``finstore snaptrade``:

  setup   — register a user with SnapTrade, persist the secret, print the OAuth
             link so the user can connect their brokerages in a browser.
             If credentials already exist, skips registration and prints a fresh
             OAuth link (useful for adding a second brokerage).

  status  — confirm the user is registered and list connected accounts.

  delete  — deregister the user from SnapTrade and wipe the credential blob.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import sys
import time
import uuid
from typing import Any

_BASE_URL = "https://api.snaptrade.com/api/v1"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _auth_headers(consumer_key: str) -> dict[str, str]:
    timestamp = str(int(time.time()))
    sig = base64.b64encode(
        hmac.new(consumer_key.encode(), timestamp.encode(), hashlib.sha256).digest()
    ).decode()
    return {"timestamp": timestamp, "Signature": sig}


def _post(
    client_id: str,
    consumer_key: str,
    path: str,
    body: dict[str, Any],
    user_id: str | None = None,
    user_secret: str | None = None,
) -> Any:
    import httpx

    params: dict[str, str] = {"clientId": client_id}
    if user_id:
        params["userId"] = user_id
    if user_secret:
        params["userSecret"] = user_secret
    resp = httpx.post(
        f"{_BASE_URL}{path}",
        params=params,
        headers=_auth_headers(consumer_key),
        json=body,
        timeout=15.0,
    )
    resp.raise_for_status()
    return resp.json()


def _get(
    client_id: str,
    consumer_key: str,
    path: str,
    user_id: str,
    user_secret: str,
) -> Any:
    import httpx

    params = {
        "clientId": client_id,
        "userId": user_id,
        "userSecret": user_secret,
    }
    resp = httpx.get(
        f"{_BASE_URL}{path}",
        params=params,
        headers=_auth_headers(consumer_key),
        timeout=15.0,
    )
    resp.raise_for_status()
    return resp.json()


def _delete(
    client_id: str,
    consumer_key: str,
    path: str,
    user_id: str,
    user_secret: str,
) -> Any:
    import httpx

    params = {
        "clientId": client_id,
        "userId": user_id,
        "userSecret": user_secret,
    }
    resp = httpx.delete(
        f"{_BASE_URL}{path}",
        params=params,
        headers=_auth_headers(consumer_key),
        timeout=15.0,
    )
    resp.raise_for_status()
    return resp.json() if resp.content else None


def _load_partner_credentials(settings: Any) -> tuple[str, str]:
    """Return (client_id, consumer_key) or exit with a helpful message."""
    client_id = settings.snaptrade_client_id
    consumer_key = (
        settings.snaptrade_consumer_key.get_secret_value()
        if settings.snaptrade_consumer_key
        else None
    )
    if not client_id or not consumer_key:
        print(
            "ERROR: SNAPTRADE_CLIENT_ID and SNAPTRADE_CONSUMER_KEY must be set in your .env file.\n"
            "Sign up at https://snaptrade.com to obtain partner credentials.",
            file=sys.stderr,
        )
        raise SystemExit(2)
    return client_id, consumer_key


def _load_user_credentials(storage: Any) -> tuple[str, str] | None:
    """Return (user_id, user_secret) from the credential blob, or None."""
    raw = storage.read_backend_credential("local", "snaptrade")
    if raw is None:
        return None
    try:
        data = json.loads(raw.decode())
        return data["user_id"], data["user_secret"]
    except (json.JSONDecodeError, KeyError):
        return None


# ---------------------------------------------------------------------------
# Public entry points (called from _app.py)
# ---------------------------------------------------------------------------


def run_setup(env_file: str | None = None) -> None:
    import httpx

    from finstore.storage.filesystem import FilesystemStorage
    from finstore_local.config import load_settings, resolve_data_dir

    settings = load_settings(env_file)
    client_id, consumer_key = _load_partner_credentials(settings)
    data_dir = resolve_data_dir(settings, create=True)
    storage = FilesystemStorage(root=data_dir)

    existing = _load_user_credentials(storage)

    if existing is not None:
        user_id, user_secret = existing
        print(f"Credentials already exist for user {user_id!r}.")
        print("Generating a fresh OAuth link to connect an additional brokerage...\n")
    else:
        # Register a new user
        user_id = str(uuid.uuid4())
        print(f"Registering SnapTrade user {user_id!r}...", end=" ", flush=True)
        try:
            result = _post(
                client_id, consumer_key,
                "/snapTrade/registerUser",
                {"userId": user_id},
            )
        except httpx.HTTPError as exc:
            print(f"FAILED\nERROR: {exc}", file=sys.stderr)
            raise SystemExit(1)

        user_secret = result.get("userSecret") or result.get("user_secret", "")
        if not user_secret:
            print(f"FAILED\nERROR: unexpected response: {result}", file=sys.stderr)
            raise SystemExit(1)

        blob = json.dumps({"user_id": user_id, "user_secret": user_secret}).encode()
        storage.write_backend_credential("local", "snaptrade", blob)
        print("OK")
        print(f"Credentials saved to: {data_dir}")

    # Generate OAuth link
    print("Generating brokerage connection link...", end=" ", flush=True)
    try:
        login_result = _post(
            client_id, consumer_key,
            "/snapTrade/login",
            {},
            user_id=user_id,
            user_secret=user_secret,
        )
    except httpx.HTTPError as exc:
        print(f"FAILED\nERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)

    redirect_uri = login_result.get("redirectURI") or login_result.get("redirect_uri", "")
    if not redirect_uri:
        print(f"FAILED\nERROR: no redirectURI in response: {login_result}", file=sys.stderr)
        raise SystemExit(1)

    print("OK\n")
    print("Open this URL in your browser to connect your brokerage account(s):\n")
    print(f"  {redirect_uri}\n")
    print("After connecting, run:  finstore fetch --backend snaptrade")


def run_status(env_file: str | None = None) -> None:
    import httpx

    from finstore.storage.filesystem import FilesystemStorage
    from finstore_local.config import load_settings, resolve_data_dir

    settings = load_settings(env_file)
    client_id, consumer_key = _load_partner_credentials(settings)
    data_dir = resolve_data_dir(settings, create=True)
    storage = FilesystemStorage(root=data_dir)

    creds = _load_user_credentials(storage)
    if creds is None:
        print("SnapTrade: not configured. Run 'finstore snaptrade setup' first.")
        return

    user_id, user_secret = creds
    print(f"SnapTrade user: {user_id}")

    try:
        accounts = _get(client_id, consumer_key, "/accounts", user_id, user_secret)
        authorizations = _get(
            client_id, consumer_key, "/brokerageAuthorizations", user_id, user_secret
        )
    except httpx.HTTPError as exc:
        print(f"ERROR: could not reach SnapTrade API: {exc}", file=sys.stderr)
        raise SystemExit(1)

    print(f"Connected brokerages: {len(authorizations)}")
    for auth in authorizations:
        brokerage = auth.get("brokerage") or {}
        print(f"  - {brokerage.get('name', auth.get('id', '?'))}")

    print(f"Accounts: {len(accounts)}")
    for acct in accounts:
        meta = acct.get("meta") or {}
        name = acct.get("name") or acct.get("number") or acct.get("id")
        institution = meta.get("institution_name") or acct.get("institution_name", "")
        print(f"  - {name}  [{institution}]  (id: {acct.get('id', '?')})")


def run_delete(env_file: str | None = None, yes: bool = False) -> None:
    import httpx

    from finstore.storage.filesystem import FilesystemStorage
    from finstore_local.config import load_settings, resolve_data_dir

    settings = load_settings(env_file)
    client_id, consumer_key = _load_partner_credentials(settings)
    data_dir = resolve_data_dir(settings, create=True)
    storage = FilesystemStorage(root=data_dir)

    creds = _load_user_credentials(storage)
    if creds is None:
        print("No SnapTrade credentials found — nothing to delete.")
        return

    user_id, user_secret = creds

    if not yes:
        confirm = input(
            f"Delete SnapTrade user {user_id!r} and all associated connections? [y/N] "
        ).strip().lower()
        if confirm not in ("y", "yes"):
            print("Aborted.")
            return

    print(f"Deregistering SnapTrade user {user_id!r}...", end=" ", flush=True)
    try:
        _delete(
            client_id, consumer_key,
            f"/snapTrade/deleteUser",
            user_id, user_secret,
        )
    except httpx.HTTPError as exc:
        print(f"FAILED\nERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)

    storage.delete_backend_credential("local", "snaptrade")
    print("OK")
    print("SnapTrade user deregistered and local credentials deleted.")
