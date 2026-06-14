"""Reference Storage implementation: one user, files on disk.

`FilesystemStorage` is intentionally broader than the `Storage` Protocol in
`finstore.protocols`. The Protocol pins the canonical surface; this class also
exposes the windowed/meta accessors gateway needs for its OFX serve path. Step 2
will decide which extras stay public.

On-disk layout (schema v4, owned entirely by this class):

    <root>/
      meta.json
      accounts/
        <conn_id>/                    # one dir per institution
          <display_id>.json

Per-account writes are POSIX-atomic; meta.json is updated last so a crash
mid-fetch never points meta at half-written account files.
"""
from __future__ import annotations

import json
import logging
import os
import time
from decimal import Decimal
from pathlib import Path
from typing import Any

from finstore.model import (
    Account,
    AccountSummary,
    Connection,
    StorageChunk,
    Transaction,
)
from finstore.storage._schema import SCHEMA_VERSION
from finstore.storage.exceptions import (
    CacheCorruptError,
    CacheEmptyError,
    CacheMissError,
    CacheSchemaMismatchError,
)
from finstore.storage.paths import normalize_conn_id, sanitize_account_name
from finstore.storage.types import AccountMeta, CachedAccount, CacheMeta, MergeStats

log = logging.getLogger(__name__)


class FilesystemStorage:
    """A `Storage` implementation backed by files on disk under `root`.

    **Single-tenant only.** The `tenant_id` parameter accepted by every
    `Storage` method is intentionally ignored — all data is written to and
    read from the same flat layout under `root`. Passing different `tenant_id`
    values provides no isolation; both callers will read and write the same
    `meta.json` and account files. For multi-tenant use, construct a separate
    `FilesystemStorage(root=per_tenant_path)` instance per tenant.
    """

    def __init__(self, root: Path):
        self._root = root
        self._meta_path = root / "meta.json"

    # ------------------------------------------------------------------ writes

    def merge_chunk(self, tenant_id: str, chunk: StorageChunk) -> MergeStats:
        """Merge one normalized chunk. Atomic per-account writes; meta last."""
        del tenant_id  # single-tenant: layout is currently tenant-flat
        txns_new = 0
        txns_duplicate = 0

        for account in chunk.accounts:
            display_id = sanitize_account_name(account.name)
            account_path = self._account_path(account.conn_id, display_id)
            account_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)

            if account_path.exists():
                existing_data = _read_account_json(account_path)
                existing_txn_ids = {t["id"] for t in existing_data.get("transactions", [])}
                new_txns = [t for t in account.transactions if t.id not in existing_txn_ids]
                dup_txns = [t for t in account.transactions if t.id in existing_txn_ids]
                txns_new += len(new_txns)
                txns_duplicate += len(dup_txns)

                merged_transactions = existing_data.get("transactions", []) + [
                    _txn_to_dict(t) for t in new_txns
                ]
                merged_data = {
                    **existing_data,
                    "id": account.id,
                    "balance": str(account.balance),
                    "available-balance": (
                        str(account.available_balance)
                        if account.available_balance is not None
                        else None
                    ),
                    "balance-date": account.balance_date,
                    "transactions": merged_transactions,
                    "conn_id": account.conn_id,
                }
                # Strip fields that previous schema versions wrote — `org` info
                # lives on Connection now and `holdings` is brokerage (a 0.1
                # non-goal). Without this, **existing_data carries them
                # forward on every merge.
                for legacy_key in ("org", "holdings"):
                    merged_data.pop(legacy_key, None)
            else:
                txns_new += len(account.transactions)
                merged_data = _account_to_dict(account)

            _atomic_write_json(account_path, merged_data)
            log.info(
                "store_write display_id=%s txns_new=%d",
                display_id[-8:] if len(display_id) > 8 else display_id,
                len(account.transactions),
            )

        self._update_meta(chunk)

        return MergeStats(
            accounts_seen=len(chunk.accounts),
            txns_new=txns_new,
            txns_duplicate=txns_duplicate,
        )

    def _update_meta(self, chunk: StorageChunk) -> None:
        now = int(time.time())

        if self._meta_path.exists():
            try:
                existing = json.loads(self._meta_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                existing = _fresh_meta(now)
        else:
            existing = _fresh_meta(now)

        existing_conns = {c["conn_id"]: c for c in existing.get("connections", [])}
        for conn in chunk.connections:
            if conn.conn_id not in existing_conns or not existing_conns[conn.conn_id].get(
                "org_name"
            ):
                existing_conns[conn.conn_id] = {
                    "conn_id": conn.conn_id,
                    "org_name": conn.org_name,
                    "org_id": conn.org_id,
                    "org_domain": conn.org_domain,
                    "sfin_url": conn.sfin_url,
                    "org_url": conn.org_url,
                }

        existing_accts = existing.get("accounts", {})
        for account in chunk.accounts:
            display_id = sanitize_account_name(account.name)
            account_path = self._account_path(account.conn_id, display_id)
            try:
                acct_data = _read_account_json(account_path)
                txns = acct_data.get("transactions", [])
                txn_count = len(txns)
                posted_vals = [t["posted"] for t in txns if t.get("posted")]
                earliest = min(posted_vals) if posted_vals else None
                latest = max(posted_vals) if posted_vals else None
            except OSError:
                txn_count = 0
                earliest = None
                latest = None

            existing_accts[display_id] = {
                "conn_id": account.conn_id,
                "sfin_id": account.id,
                "last_fetch_at": now,
                "txn_count": txn_count,
                "earliest_posted": earliest,
                "latest_posted": latest,
            }

        meta = {
            "schema_version": SCHEMA_VERSION,
            "last_fetch_at": now,
            "connections": list(existing_conns.values()),
            "accounts": existing_accts,
        }
        _atomic_write_json(self._meta_path, meta)

    # ------------------------------------------------------------------- reads

    def read_meta(self, tenant_id: str = "local") -> CacheMeta:
        del tenant_id
        if not self._meta_path.exists():
            raise CacheEmptyError("meta.json not found")
        try:
            data = json.loads(self._meta_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            raise CacheCorruptError(f"meta.json is corrupt: {e}") from e

        schema_v = data.get("schema_version", 0)
        if schema_v != SCHEMA_VERSION:
            raise CacheSchemaMismatchError(schema_v, SCHEMA_VERSION)

        connections = tuple(
            Connection(
                conn_id=c["conn_id"],
                org_name=c.get("org_name", "SimpleFIN"),
                org_id=c.get("org_id") or "1537",
                org_domain=c.get("org_domain", ""),
                sfin_url=c.get("sfin_url", ""),
                org_url=c.get("org_url", ""),
            )
            for c in data.get("connections", [])
        )
        accounts: dict[str, AccountMeta] = {
            display_id: AccountMeta(
                last_fetch_at=info.get("last_fetch_at", 0),
                txn_count=info.get("txn_count", 0),
                earliest_posted=info.get("earliest_posted"),
                latest_posted=info.get("latest_posted"),
                conn_id=info.get("conn_id", ""),
                sfin_id=info.get("sfin_id", ""),
            )
            for display_id, info in data.get("accounts", {}).items()
        }
        if not accounts:
            raise CacheEmptyError("Cache has no accounts")

        return CacheMeta(
            schema_version=schema_v,
            last_fetch_at=data.get("last_fetch_at", 0),
            connections=connections,
            accounts=accounts,
        )

    def resolve_display_id(self, tenant_id: str, display_id: str) -> str:
        """Confirm `display_id` exists in this tenant's cache and return it."""
        meta = self.read_meta(tenant_id)
        if display_id in meta.accounts:
            return display_id
        raise CacheMissError(display_id)

    def read_account(self, tenant_id: str, account_id: str) -> CachedAccount:
        """Read one full account (all transactions)."""
        conn_id = self._conn_id_for(tenant_id, account_id)
        data = self._load_account_file(account_id, conn_id)
        account = _dict_to_account(data)
        return CachedAccount(account=account, transactions=account.transactions)

    def read_account_window(
        self,
        tenant_id: str,
        account_id: str,
        dtstart_epoch: int,
        dtend_epoch: int | None,
    ) -> CachedAccount:
        """Read one account; transactions filtered to [dtstart, dtend] inclusive."""
        conn_id = self._conn_id_for(tenant_id, account_id)
        data = self._load_account_file(account_id, conn_id)
        account = _dict_to_account(data)
        filtered = tuple(
            t
            for t in account.transactions
            if t.posted >= dtstart_epoch
            and (dtend_epoch is None or t.posted <= dtend_epoch)
        )
        return CachedAccount(account=account, transactions=filtered)

    def list_accounts(self, tenant_id: str = "local") -> tuple[AccountSummary, ...]:
        meta = self.read_meta(tenant_id)
        conn_map = {c.conn_id: c for c in meta.connections}

        out: list[AccountSummary] = []
        for display_id, acct_meta in meta.accounts.items():
            conn_id = acct_meta.conn_id
            try:
                data = self._load_account_file(display_id, conn_id)
            except (CacheMissError, CacheCorruptError):
                continue
            connection = conn_map.get(
                conn_id,
                Connection(conn_id=conn_id, org_name="SimpleFIN", org_id="1537"),
            )
            out.append(
                AccountSummary(
                    acctid=display_id,
                    name=data.get("name", ""),
                    currency=data.get("currency") or "USD",
                    connection=connection,
                    last_fetch_at=acct_meta.last_fetch_at or None,
                    txn_count=acct_meta.txn_count,
                )
            )
        return tuple(out)

    # ------------------------------------------------- backend credential store

    def read_backend_credential(self, tenant_id: str, backend_id: str) -> bytes | None:
        """Return the persisted credential blob, or None if not yet written."""
        path = self._credential_path(tenant_id, backend_id)
        if not path.exists():
            return None
        try:
            return path.read_bytes()
        except OSError:
            return None

    def write_backend_credential(
        self, tenant_id: str, backend_id: str, data: bytes
    ) -> None:
        """Atomically persist a credential blob with mode 0600."""
        path = self._credential_path(tenant_id, backend_id)
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_bytes(data)
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)

    def exists_backend_credential(self, tenant_id: str, backend_id: str) -> bool:
        return self._credential_path(tenant_id, backend_id).exists()

    def delete_backend_credential(self, tenant_id: str, backend_id: str) -> bool:
        """Delete the persisted credential.

        Returns True if a credential was deleted, False if nothing was there
        to begin with. Missing parent directories are not an error.
        """
        path = self._credential_path(tenant_id, backend_id)
        try:
            path.unlink()
        except FileNotFoundError:
            return False
        return True

    # -------------------------------------------------------------- internals

    @property
    def root(self) -> Path:
        return self._root

    def _credential_path(self, tenant_id: str, backend_id: str) -> Path:
        return self._root / "tenants" / tenant_id / "credentials" / f"{backend_id}.bin"

    def _account_path(self, conn_id: str, display_id: str) -> Path:
        return self._root / "accounts" / normalize_conn_id(conn_id) / f"{display_id}.json"

    def _load_account_file(self, display_id: str, conn_id: str) -> dict[str, Any]:
        account_path = self._account_path(conn_id, display_id)
        if not account_path.exists():
            raise CacheMissError(display_id)
        try:
            data: dict[str, Any] = json.loads(account_path.read_text(encoding="utf-8"))
            return data
        except json.JSONDecodeError as e:
            raise CacheCorruptError(f"Account file corrupt for {display_id}: {e}") from e

    def _conn_id_for(self, tenant_id: str, display_id: str) -> str:
        meta = self.read_meta(tenant_id)
        acct_meta = meta.accounts.get(display_id)
        if acct_meta is None:
            raise CacheMissError(display_id)
        return acct_meta.conn_id


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------


def _fresh_meta(now: int) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "last_fetch_at": now,
        "connections": [],
        "accounts": {},
    }


def _atomic_write_json(path: Path, obj: dict[str, Any]) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    data = json.dumps(obj, indent=2)
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)  # POSIX-atomic within one filesystem


def _read_account_json(path: Path) -> dict[str, Any]:
    out: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return out


def _txn_to_dict(t: Transaction) -> dict[str, Any]:
    return {
        "id": t.id,
        "posted": t.posted,
        "amount": str(t.amount),
        "description": t.description,
        "payee": t.payee,
        "memo": t.memo,
        "transacted_at": t.transacted_at,
    }


def _account_to_dict(account: Account) -> dict[str, Any]:
    return {
        "id": account.id,
        "name": account.name,
        "currency": account.currency,
        "balance": str(account.balance),
        "available-balance": (
            str(account.available_balance)
            if account.available_balance is not None
            else None
        ),
        "balance-date": account.balance_date,
        "conn_id": account.conn_id,
        "transactions": [_txn_to_dict(t) for t in account.transactions],
    }


def _dict_to_account(data: dict[str, Any]) -> Account:
    return Account(
        id=data["id"],
        name=data.get("name", ""),
        currency=data.get("currency") or "USD",
        balance=Decimal(str(data.get("balance", "0"))),
        available_balance=(
            Decimal(str(data["available-balance"]))
            if data.get("available-balance") is not None
            else None
        ),
        balance_date=data.get("balance-date", 0),
        conn_id=data.get("conn_id", ""),
        transactions=tuple(
            Transaction(
                id=t["id"],
                posted=t["posted"],
                amount=Decimal(str(t["amount"])),
                description=t.get("description", ""),
                payee=t.get("payee", ""),
                memo=t.get("memo", ""),
                transacted_at=t.get("transacted_at"),
            )
            for t in data.get("transactions", [])
        ),
    )


__all__ = ["FilesystemStorage"]
