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
from urllib.parse import urlencode

_BASE_URL = "https://api.snaptrade.com/api/v1"
# Path prefix used when building the signed path (must include /api/v1).
_API_PATH_PREFIX = "/api/v1"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _make_signature(
    consumer_key: str,
    path: str,
    query_string: str,
    body: dict[str, Any] | None,
) -> str:
    """Compute the SnapTrade HMAC-SHA256 Signature header value.

    The signed message is a compact, key-sorted JSON object containing the
    request body dict, the full API path, and the URL-encoded query string
    (which includes clientId and timestamp).  This matches the official SDK.
    """
    sig_object = {"content": body, "path": path, "query": query_string}
    sig_content = json.dumps(sig_object, separators=(",", ":"), sort_keys=True)
    return base64.b64encode(
        hmac.new(consumer_key.encode(), sig_content.encode(), hashlib.sha256).digest()
    ).decode()


def _post(
    client_id: str,
    consumer_key: str,
    path: str,
    body: dict[str, Any] | None = None,
    user_id: str | None = None,
    user_secret: str | None = None,
) -> Any:
    import httpx

    timestamp = str(int(time.time()))
    params: dict[str, str] = {"clientId": client_id, "timestamp": timestamp}
    if user_id:
        params["userId"] = user_id
    if user_secret:
        params["userSecret"] = user_secret
    full_path = f"{_API_PATH_PREFIX}{path}"
    # Sign with body content if present, otherwise null — matches official SDK behaviour.
    signature = _make_signature(consumer_key, full_path, urlencode(params), body or None)
    resp = httpx.post(
        f"{_BASE_URL}{path}",
        params=params,
        json=body if body else None,
        headers={"Signature": signature},
        timeout=15.0,
    )
    resp.raise_for_status()
    return resp.json()


def _get(
    client_id: str,
    consumer_key: str,
    path: str,
    user_id: str | None = None,
    user_secret: str | None = None,
) -> Any:
    import httpx

    timestamp = str(int(time.time()))
    params: dict[str, str] = {}
    if user_id is not None:
        params["userId"] = user_id
    if user_secret is not None:
        params["userSecret"] = user_secret
    params["clientId"] = client_id
    params["timestamp"] = timestamp
    full_path = f"{_API_PATH_PREFIX}{path}"
    signature = _make_signature(consumer_key, full_path, urlencode(params), None)
    resp = httpx.get(
        f"{_BASE_URL}{path}",
        params=params,
        headers={"Signature": signature},
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

    timestamp = str(int(time.time()))
    params: dict[str, str] = {
        "userId": user_id,
        "userSecret": user_secret,
        "clientId": client_id,
        "timestamp": timestamp,
    }
    full_path = f"{_API_PATH_PREFIX}{path}"
    signature = _make_signature(consumer_key, full_path, urlencode(params), None)
    resp = httpx.delete(
        f"{_BASE_URL}{path}",
        params=params,
        headers={"Signature": signature},
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
    if not client_id:
        print(
            "ERROR: SNAPTRADE_CLIENT_ID is not set in your .env file.",
            file=sys.stderr,
        )
        raise SystemExit(2)
    if not consumer_key:
        print(
            "ERROR: SNAPTRADE_CONSUMER_KEY is not set in your .env file.\n"
            "Find your consumer key in the SnapTrade dashboard under API Keys.",
            file=sys.stderr,
        )
        raise SystemExit(2)
    return client_id, consumer_key


def _load_user_credentials(storage: Any) -> tuple[str, str] | None:
    """Return (user_id, user_secret) from the credential blob, or None.

    Returns None both when no blob exists and when the blob is the personal
    account marker {"type": "personal"} — callers use is_personal() to
    distinguish "not set up" from "personal account, no user creds needed".
    """
    raw = storage.read_backend_credential("local", "snaptrade")
    if raw is None:
        return None
    try:
        data = json.loads(raw.decode())
        if data.get("type") == "personal":
            return None
        return data["user_id"], data["user_secret"]
    except (json.JSONDecodeError, KeyError):
        return None


def _is_configured(storage: Any) -> bool:
    """Return True if SnapTrade setup has been completed (any key type)."""
    raw = storage.read_backend_credential("local", "snaptrade")
    return raw is not None


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

    is_personal = client_id.startswith("PERS-")
    user_id: str | None = None
    user_secret: str | None = None

    if is_personal:
        # Personal keys — the account is identified by clientId alone.
        # registerUser is blocked; userId/userSecret are not used.
        # Overwrite any stale blob (e.g. from a previous failed setup attempt)
        # with the personal marker so status/fetch know setup is complete.
        raw = storage.read_backend_credential("local", "snaptrade")
        try:
            already_done = raw is not None and json.loads(raw.decode()).get("type") == "personal"
        except (json.JSONDecodeError, AttributeError):
            already_done = False

        if already_done:
            print("Personal SnapTrade account already configured.")
        else:
            blob = json.dumps({"type": "personal"}).encode()
            storage.write_backend_credential("local", "snaptrade", blob)
            print("Personal SnapTrade key detected (PERS- prefix).")
            print("No user registration needed — your account is identified by your")
            print(f"clientId.  Credentials marker saved to: {data_dir}")

        # Verify connection by listing accounts (no OAuth portal needed).
        print("Verifying connection...", end=" ", flush=True)
        try:
            accounts = _get(client_id, consumer_key, "/accounts")
        except httpx.HTTPStatusError as exc:
            body = exc.response.text
            print(f"FAILED\nERROR: {exc}\nResponse body: {body}", file=sys.stderr)
            raise SystemExit(1)
        except httpx.HTTPError as exc:
            print(f"FAILED\nERROR: {exc}", file=sys.stderr)
            raise SystemExit(1)
        print("OK")
        print(f"Found {len(accounts)} account(s):")
        for acct in accounts:
            name = acct.get("name") or acct.get("number") or acct.get("id", "?")
            meta = acct.get("meta") or {}
            institution = meta.get("institution_name") or acct.get("institution_name", "")
            suffix = f"  [{institution}]" if institution else ""
            print(f"  - {name}{suffix}")
        print("\nSetup complete. Run:  finstore fetch --backend snaptrade")
    else:
        existing = _load_user_credentials(storage)
        if existing is not None:
            user_id, user_secret = existing
            print(f"Credentials already exist for user {user_id!r}.")
            print("Generating a fresh OAuth link to connect an additional brokerage...\n")
        else:
            # Partner/developer keys — register a new user via the API.
            user_id = str(uuid.uuid4())
            print(f"Registering SnapTrade user {user_id!r}...", end=" ", flush=True)
            try:
                result = _post(
                    client_id, consumer_key,
                    "/snapTrade/registerUser",
                    {"userId": user_id, "rsaPublicKey": None},
                )
            except httpx.HTTPStatusError as exc:
                body = exc.response.text
                print(f"FAILED\nERROR: {exc}\nResponse body: {body}", file=sys.stderr)
                raise SystemExit(1)
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

        print("Generating brokerage connection link...", end=" ", flush=True)
        try:
            login_result = _post(
                client_id, consumer_key,
                "/snapTrade/login",
                user_id=user_id,
                user_secret=user_secret,
            )
        except httpx.HTTPStatusError as exc:
            body = exc.response.text
            print(f"FAILED\nERROR: {exc}\nResponse body: {body}", file=sys.stderr)
            raise SystemExit(1)
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

    if not _is_configured(storage):
        print("SnapTrade: not configured. Run 'finstore snaptrade setup' first.")
        return

    is_personal = client_id.startswith("PERS-")
    creds = _load_user_credentials(storage)  # None for personal accounts

    if is_personal:
        print(f"SnapTrade: personal account (clientId: {client_id})")
        user_id = user_secret = None
    else:
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

    if not _is_configured(storage):
        print("No SnapTrade credentials found — nothing to delete.")
        return

    is_personal = client_id.startswith("PERS-")
    creds = _load_user_credentials(storage)

    if not yes:
        label = f"clientId {client_id!r}" if is_personal else f"user {creds[0]!r}" if creds else "unknown user"
        confirm = input(
            f"Delete SnapTrade credentials for {label}? [y/N] "
        ).strip().lower()
        if confirm not in ("y", "yes"):
            print("Aborted.")
            return

    if not is_personal and creds is not None:
        user_id, user_secret = creds
        print(f"Deregistering SnapTrade user {user_id!r}...", end=" ", flush=True)
        try:
            _delete(
                client_id, consumer_key,
                "/snapTrade/deleteUser",
                user_id, user_secret,
            )
            print("OK")
        except httpx.HTTPError as exc:
            print(f"FAILED\nERROR: {exc}", file=sys.stderr)
            raise SystemExit(1)

    storage.delete_backend_credential("local", "snaptrade")
    print("SnapTrade credentials deleted.")
