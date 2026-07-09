"""Reference Storage implementation: one user, files on disk.

`FilesystemStorage` is intentionally broader than the `Storage` Protocol in
`finstore.protocols`. The Protocol pins the canonical surface; this class also
exposes the windowed/meta accessors gateway needs for its OFX serve path. Step 2
will decide which extras stay public.

On-disk layout (schema v5, owned entirely by this class):

    <root>/
      meta.json
      accounts/
        <conn_id>/                    # one dir per institution
          <display_id>.json
      investment/
        <conn_id>/                    # one dir per brokerage (normalized slug)
          <display_id>.json           # account metadata + investment_transactions
          <display_id>.positions.json # latest position snapshot (replace-on-write)
      securities.json                 # shared registry; upserted on every merge

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
    AccountType,
    Connection,
    InvestmentAccount,
    InvestmentTransaction,
    Position,
    Security,
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
from finstore.storage.paths import (
    infer_account_type,
    normalize_conn_id,
    sanitize_account_name,
)
from finstore.storage.types import (
    AccountMeta,
    CachedAccount,
    CachedInvestmentAccount,
    CacheMeta,
    InvestmentAccountMeta,
    InvestmentAccountSummary,
    MergeStats,
)

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
                existing_data = _read_json(account_path)
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
                    "account_type": account.account_type.value,
                }
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

        inv_txns_new = 0
        inv_txns_dup = 0
        positions_written = 0

        for inv_account in chunk.investment_accounts:
            n, d = self._merge_investment_account(inv_account)
            inv_txns_new += n
            inv_txns_dup += d
            positions_written += len(inv_account.positions)

        securities_upserted = 0
        if chunk.securities:
            securities_upserted = self._upsert_securities(chunk.securities)

        self._update_meta(chunk)

        return MergeStats(
            accounts_seen=len(chunk.accounts),
            txns_new=txns_new,
            txns_duplicate=txns_duplicate,
            inv_accounts_seen=len(chunk.investment_accounts),
            inv_txns_new=inv_txns_new,
            inv_txns_duplicate=inv_txns_dup,
            positions_written=positions_written,
            securities_upserted=securities_upserted,
        )

    def _merge_investment_account(
        self, account: InvestmentAccount
    ) -> tuple[int, int]:
        """Merge one investment account. Returns (txns_new, txns_duplicate)."""
        display_id = sanitize_account_name(account.name)
        acct_path = self._investment_account_path(account.conn_id, display_id)
        pos_path = self._positions_path(account.conn_id, display_id)
        acct_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)

        if acct_path.exists():
            existing_data = _read_json(acct_path)
            existing_txns: dict[str, Any] = {
                t["id"]: t
                for t in existing_data.get("investment_transactions", [])
            }
            new_txns: list[dict[str, Any]] = []
            accepted_ids: set[str] = set()  # tracks IDs accepted in this batch
            dup_count = 0
            for t in account.investment_transactions:
                if t.id in existing_txns:
                    stored_total = existing_txns[t.id].get("total")
                    if stored_total != str(t.total):
                        log.warning(
                            "inv_txn id=%s already stored with total=%s; "
                            "incoming total=%s — keeping stored",
                            t.id, stored_total, t.total,
                        )
                    dup_count += 1
                elif t.id in accepted_ids:
                    # Duplicate within the incoming batch itself
                    dup_count += 1
                else:
                    accepted_ids.add(t.id)
                    new_txns.append(_inv_txn_to_dict(t))

            merged_data = {
                **existing_data,
                "id": account.id,
                "name": account.name,
                "currency": account.currency,
                "broker_id": account.broker_id,
                "available_cash": (
                    str(account.available_cash)
                    if account.available_cash is not None else None
                ),
                "margin_balance": (
                    str(account.margin_balance)
                    if account.margin_balance is not None else None
                ),
                "balance_date": account.balance_date,
                "conn_id": account.conn_id,
                "investment_transactions": (
                    existing_data.get("investment_transactions", []) + new_txns
                ),
            }
            txns_new = len(new_txns)
        else:
            # First write: dedup within the incoming chunk itself (adjacent
            # window boundaries are inclusive, so the same activity can appear
            # twice in one StorageChunk).
            seen_ids: set[str] = set()
            deduped_txns: list[InvestmentTransaction] = []
            for t in account.investment_transactions:
                if t.id not in seen_ids:
                    seen_ids.add(t.id)
                    deduped_txns.append(t)
            account = InvestmentAccount(
                id=account.id,
                name=account.name,
                currency=account.currency,
                broker_id=account.broker_id,
                available_cash=account.available_cash,
                margin_balance=account.margin_balance,
                balance_date=account.balance_date,
                conn_id=account.conn_id,
                positions=account.positions,
                investment_transactions=tuple(deduped_txns),
            )
            merged_data = _investment_account_to_dict(account)
            txns_new = len(account.investment_transactions)
            dup_count = 0

        _atomic_write_json(acct_path, merged_data)

        # Positions: always replace wholesale (latest snapshot only).
        _atomic_write_json(
            pos_path,
            {"positions": [_position_to_dict(p) for p in account.positions]},
        )

        log.info(
            "store_write_inv display_id=%s txns_new=%d positions=%d",
            display_id[-8:] if len(display_id) > 8 else display_id,
            txns_new,
            len(account.positions),
        )
        return txns_new, dup_count

    def _upsert_securities(self, securities: tuple[Security, ...]) -> int:
        """Upsert securities into the shared registry. Returns count upserted."""
        path = self._securities_path()
        if path.exists():
            try:
                existing = _read_json(path)
            except (json.JSONDecodeError, OSError):
                existing = {}
            registry: dict[str, Any] = {
                f"{s['uniqueid_type']}:{s['uniqueid']}": s
                for s in existing.get("securities", [])
            }
        else:
            registry = {}

        for sec in securities:
            key = f"{sec.uniqueid_type}:{sec.uniqueid}"
            registry[key] = _security_to_dict(sec)

        _atomic_write_json(path, {"securities": list(registry.values())})
        return len(securities)

    def _update_meta(self, chunk: StorageChunk) -> None:
        now = int(time.time())

        if self._meta_path.exists():
            try:
                existing = json.loads(self._meta_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                existing = _fresh_meta(now)
        else:
            existing = _fresh_meta(now)

        # --- connections ---
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

        # --- cash accounts ---
        existing_accts = existing.get("accounts", {})
        for account in chunk.accounts:
            display_id = sanitize_account_name(account.name)
            account_path = self._account_path(account.conn_id, display_id)
            try:
                acct_data = _read_json(account_path)
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

        # --- investment accounts ---
        existing_inv = existing.get("investment_accounts", {})
        for inv_account in chunk.investment_accounts:
            display_id = sanitize_account_name(inv_account.name)
            acct_path = self._investment_account_path(inv_account.conn_id, display_id)
            try:
                acct_data = _read_json(acct_path)
                inv_txns = acct_data.get("investment_transactions", [])
                txn_count = len(inv_txns)
                trade_vals = [t["trade_date"] for t in inv_txns if t.get("trade_date")]
                earliest_trade = min(trade_vals) if trade_vals else None
                latest_trade = max(trade_vals) if trade_vals else None
            except OSError:
                txn_count = 0
                earliest_trade = None
                latest_trade = None

            pos_path = self._positions_path(inv_account.conn_id, display_id)
            try:
                pos_data = _read_json(pos_path)
                position_count = len(pos_data.get("positions", []))
            except OSError:
                position_count = 0

            existing_inv[display_id] = {
                "conn_id": inv_account.conn_id,
                "broker_id": inv_account.broker_id,
                "last_fetch_at": now,
                "txn_count": txn_count,
                "position_count": position_count,
                "earliest_trade": earliest_trade,
                "latest_trade": latest_trade,
            }

        meta = {
            "schema_version": SCHEMA_VERSION,
            "last_fetch_at": now,
            "connections": list(existing_conns.values()),
            "accounts": existing_accts,
            "investment_accounts": existing_inv,
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
        investment_accounts: dict[str, InvestmentAccountMeta] = {
            display_id: InvestmentAccountMeta(
                last_fetch_at=info.get("last_fetch_at", 0),
                txn_count=info.get("txn_count", 0),
                position_count=info.get("position_count", 0),
                earliest_trade=info.get("earliest_trade"),
                latest_trade=info.get("latest_trade"),
                conn_id=info.get("conn_id", ""),
                broker_id=info.get("broker_id", ""),
            )
            for display_id, info in data.get("investment_accounts", {}).items()
        }

        if not accounts and not investment_accounts:
            raise CacheEmptyError("Cache has no accounts")

        return CacheMeta(
            schema_version=schema_v,
            last_fetch_at=data.get("last_fetch_at", 0),
            connections=connections,
            accounts=accounts,
            investment_accounts=investment_accounts,
        )

    def resolve_display_id(self, tenant_id: str, display_id: str) -> str:
        """Confirm `display_id` exists in this tenant's cache and return it."""
        meta = self.read_meta(tenant_id)
        if display_id in meta.accounts:
            return display_id
        raise CacheMissError(display_id)

    def read_account(self, tenant_id: str, account_id: str) -> CachedAccount:
        """Read one full cash account (all transactions)."""
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
        """Read one cash account; transactions filtered to [dtstart, dtend]."""
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
                    account_type=AccountType(
                        data.get("account_type") or infer_account_type(data.get("name", ""))
                    ),
                )
            )
        return tuple(out)

    def read_investment_account(
        self, tenant_id: str, account_id: str
    ) -> CachedInvestmentAccount:
        """Read one full investment account (all transactions + positions)."""
        conn_id = self._conn_id_for_investment(tenant_id, account_id)
        acct_data, pos_list = self._load_investment_account_file(account_id, conn_id)
        account = _dict_to_investment_account(acct_data, pos_list)
        return CachedInvestmentAccount(
            account=account,
            investment_transactions=account.investment_transactions,
        )

    def read_investment_account_window(
        self,
        tenant_id: str,
        account_id: str,
        dtstart_epoch: int,
        dtend_epoch: int | None,
    ) -> CachedInvestmentAccount:
        """Read one investment account; transactions filtered by trade_date."""
        conn_id = self._conn_id_for_investment(tenant_id, account_id)
        acct_data, pos_list = self._load_investment_account_file(account_id, conn_id)
        account = _dict_to_investment_account(acct_data, pos_list)
        filtered = tuple(
            t
            for t in account.investment_transactions
            if t.trade_date >= dtstart_epoch
            and (dtend_epoch is None or t.trade_date <= dtend_epoch)
        )
        return CachedInvestmentAccount(account=account, investment_transactions=filtered)

    def list_investment_accounts(
        self, tenant_id: str = "local"
    ) -> tuple[InvestmentAccountSummary, ...]:
        meta = self.read_meta(tenant_id)
        conn_map = {c.conn_id: c for c in meta.connections}

        out: list[InvestmentAccountSummary] = []
        for display_id, inv_meta in meta.investment_accounts.items():
            conn_id = inv_meta.conn_id
            try:
                acct_data, _ = self._load_investment_account_file(display_id, conn_id)
            except (CacheMissError, CacheCorruptError):
                continue
            connection = conn_map.get(
                conn_id,
                Connection(conn_id=conn_id, org_name=conn_id, org_id=conn_id),
            )
            out.append(
                InvestmentAccountSummary(
                    acctid=display_id,
                    name=acct_data.get("name", ""),
                    currency=acct_data.get("currency", "USD"),
                    broker_id=acct_data.get("broker_id", ""),
                    connection=connection,
                    last_fetch_at=inv_meta.last_fetch_at or None,
                    txn_count=inv_meta.txn_count,
                    position_count=inv_meta.position_count,
                )
            )
        return tuple(out)

    def read_securities(
        self,
        tenant_id: str,
        ids: tuple[tuple[str, str], ...] | None = None,
    ) -> tuple[Security, ...]:
        """Return securities from the shared registry.

        If ``ids`` is None, return all.  Otherwise filter to the given
        ``(uniqueid_type, uniqueid)`` pairs.
        """
        del tenant_id
        path = self._securities_path()
        if not path.exists():
            return ()
        try:
            data = _read_json(path)
        except json.JSONDecodeError as e:
            raise CacheCorruptError(f"securities.json is corrupt: {e}") from e

        securities = tuple(_dict_to_security(s) for s in data.get("securities", []))
        if ids is None:
            return securities
        id_set = set(ids)
        return tuple(s for s in securities if (s.uniqueid_type, s.uniqueid) in id_set)

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

    def clear_cache(self, scope: str = "all") -> None:
        """Delete cached data files, preserving credentials.

        ``scope`` controls which data is removed:
        - ``"all"``        — meta.json + accounts/ + investment/ + securities.json
        - ``"banking"``    — meta.json + accounts/  (SimpleFIN data)
        - ``"investment"`` — meta.json + investment/ + securities.json  (SnapTrade data)

        Credentials under ``tenants/`` are never touched.
        """
        import shutil

        self._meta_path.unlink(missing_ok=True)

        if scope in ("all", "banking"):
            accts = self._root / "accounts"
            if accts.exists():
                shutil.rmtree(accts)

        if scope in ("all", "investment"):
            inv = self._root / "investment"
            if inv.exists():
                shutil.rmtree(inv)
            self._securities_path().unlink(missing_ok=True)

    # -------------------------------------------------------------- internals

    @property
    def root(self) -> Path:
        return self._root

    def _credential_path(self, tenant_id: str, backend_id: str) -> Path:
        return self._root / "tenants" / tenant_id / "credentials" / f"{backend_id}.bin"

    def _account_path(self, conn_id: str, display_id: str) -> Path:
        return self._root / "accounts" / normalize_conn_id(conn_id) / f"{display_id}.json"

    def _investment_account_path(self, conn_id: str, display_id: str) -> Path:
        return (
            self._root / "investment" / normalize_conn_id(conn_id) / f"{display_id}.json"
        )

    def _positions_path(self, conn_id: str, display_id: str) -> Path:
        return (
            self._root
            / "investment"
            / normalize_conn_id(conn_id)
            / f"{display_id}.positions.json"
        )

    def _securities_path(self) -> Path:
        return self._root / "securities.json"

    def _load_account_file(self, display_id: str, conn_id: str) -> dict[str, Any]:
        account_path = self._account_path(conn_id, display_id)
        if not account_path.exists():
            raise CacheMissError(display_id)
        try:
            data: dict[str, Any] = json.loads(account_path.read_text(encoding="utf-8"))
            return data
        except json.JSONDecodeError as e:
            raise CacheCorruptError(f"Account file corrupt for {display_id}: {e}") from e

    def _load_investment_account_file(
        self, display_id: str, conn_id: str
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        acct_path = self._investment_account_path(conn_id, display_id)
        if not acct_path.exists():
            raise CacheMissError(display_id)
        try:
            acct_data: dict[str, Any] = json.loads(acct_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            raise CacheCorruptError(
                f"Investment account file corrupt for {display_id}: {e}"
            ) from e

        pos_path = self._positions_path(conn_id, display_id)
        if pos_path.exists():
            try:
                pos_data = json.loads(pos_path.read_text(encoding="utf-8"))
                positions: list[dict[str, Any]] = pos_data.get("positions", [])
            except json.JSONDecodeError:
                positions = []
        else:
            positions = []

        return acct_data, positions

    def _conn_id_for(self, tenant_id: str, display_id: str) -> str:
        meta = self.read_meta(tenant_id)
        acct_meta = meta.accounts.get(display_id)
        if acct_meta is None:
            raise CacheMissError(display_id)
        return acct_meta.conn_id

    def _conn_id_for_investment(self, tenant_id: str, display_id: str) -> str:
        meta = self.read_meta(tenant_id)
        inv_meta = meta.investment_accounts.get(display_id)
        if inv_meta is None:
            raise CacheMissError(display_id)
        return inv_meta.conn_id


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------


def _fresh_meta(now: int) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "last_fetch_at": now,
        "connections": [],
        "accounts": {},
        "investment_accounts": {},
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


def _read_json(path: Path) -> dict[str, Any]:
    out: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return out


# ---- cash account serialization ----

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
        "account_type": account.account_type.value,
        "transactions": [_txn_to_dict(t) for t in account.transactions],
    }


def _dict_to_account(data: dict[str, Any]) -> Account:
    raw_type = data.get("account_type")
    account_type = AccountType(raw_type) if raw_type else AccountType(
        infer_account_type(data.get("name", ""))
    )
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
        account_type=account_type,
    )


# ---- investment serialization ----

def _security_to_dict(s: Security) -> dict[str, Any]:
    return {
        "uniqueid": s.uniqueid,
        "uniqueid_type": s.uniqueid_type,
        "name": s.name,
        "ticker": s.ticker,
        "security_type": s.security_type,
    }


def _dict_to_security(data: dict[str, Any]) -> Security:
    return Security(
        uniqueid=data["uniqueid"],
        uniqueid_type=data["uniqueid_type"],
        name=data.get("name", ""),
        ticker=data.get("ticker", ""),
        security_type=data.get("security_type", "OTHER"),
    )


def _position_to_dict(p: Position) -> dict[str, Any]:
    return {
        "security_id": p.security_id,
        "security_id_type": p.security_id_type,
        "units": str(p.units),
        "unit_price": str(p.unit_price),
        "market_value": str(p.market_value),
        "cost_basis": str(p.cost_basis) if p.cost_basis is not None else None,
        "held_in_acct": p.held_in_acct,
        "pos_type": p.pos_type,
        "snapshot_date": p.snapshot_date,
    }


def _dict_to_position(data: dict[str, Any]) -> Position:
    return Position(
        security_id=data["security_id"],
        security_id_type=data["security_id_type"],
        units=Decimal(str(data["units"])),
        unit_price=Decimal(str(data["unit_price"])),
        market_value=Decimal(str(data["market_value"])),
        cost_basis=(
            Decimal(str(data["cost_basis"]))
            if data.get("cost_basis") is not None else None
        ),
        held_in_acct=data.get("held_in_acct", "CASH"),
        pos_type=data.get("pos_type", "LONG"),
        snapshot_date=data["snapshot_date"],
    )


def _inv_txn_to_dict(t: InvestmentTransaction) -> dict[str, Any]:
    return {
        "id": t.id,
        "trade_date": t.trade_date,
        "settle_date": t.settle_date,
        "trntype": t.trntype,
        "security_id": t.security_id,
        "security_id_type": t.security_id_type,
        "units": str(t.units) if t.units is not None else None,
        "unit_price": str(t.unit_price) if t.unit_price is not None else None,
        "commission": str(t.commission) if t.commission is not None else None,
        "fees": str(t.fees) if t.fees is not None else None,
        "taxes": str(t.taxes) if t.taxes is not None else None,
        "total": str(t.total),
        "income_type": t.income_type,
        "description": t.description,
        "memo": t.memo,
        "currency": t.currency,
    }


def _dict_to_inv_txn(data: dict[str, Any]) -> InvestmentTransaction:
    return InvestmentTransaction(
        id=data["id"],
        trade_date=data["trade_date"],
        settle_date=data.get("settle_date"),
        trntype=data["trntype"],
        security_id=data.get("security_id"),
        security_id_type=data.get("security_id_type"),
        units=Decimal(str(data["units"])) if data.get("units") is not None else None,
        unit_price=(
            Decimal(str(data["unit_price"])) if data.get("unit_price") is not None else None
        ),
        commission=(
            Decimal(str(data["commission"])) if data.get("commission") is not None else None
        ),
        fees=Decimal(str(data["fees"])) if data.get("fees") is not None else None,
        taxes=Decimal(str(data["taxes"])) if data.get("taxes") is not None else None,
        total=Decimal(str(data["total"])),
        income_type=data.get("income_type"),
        description=data.get("description", ""),
        memo=data.get("memo", ""),
        currency=data.get("currency", "USD"),
    )


def _investment_account_to_dict(account: InvestmentAccount) -> dict[str, Any]:
    return {
        "id": account.id,
        "name": account.name,
        "currency": account.currency,
        "broker_id": account.broker_id,
        "available_cash": (
            str(account.available_cash) if account.available_cash is not None else None
        ),
        "margin_balance": (
            str(account.margin_balance) if account.margin_balance is not None else None
        ),
        "balance_date": account.balance_date,
        "conn_id": account.conn_id,
        "investment_transactions": [_inv_txn_to_dict(t) for t in account.investment_transactions],
    }


def _dict_to_investment_account(
    data: dict[str, Any], positions: list[dict[str, Any]]
) -> InvestmentAccount:
    return InvestmentAccount(
        id=data["id"],
        name=data.get("name", ""),
        currency=data.get("currency", "USD"),
        broker_id=data.get("broker_id", ""),
        available_cash=(
            Decimal(str(data["available_cash"]))
            if data.get("available_cash") is not None else None
        ),
        margin_balance=(
            Decimal(str(data["margin_balance"]))
            if data.get("margin_balance") is not None else None
        ),
        balance_date=data.get("balance_date", 0),
        conn_id=data.get("conn_id", ""),
        positions=tuple(_dict_to_position(p) for p in positions),
        investment_transactions=tuple(
            _dict_to_inv_txn(t) for t in data.get("investment_transactions", [])
        ),
    )


__all__ = ["FilesystemStorage"]
