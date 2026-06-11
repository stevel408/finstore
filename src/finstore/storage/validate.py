"""Cache validation rules.

All tuneable thresholds are defined in the CONSTANTS block below. Rules are
plain functions: each takes a dict and returns a (possibly empty) list of
violation strings. Collect new rules by appending to ACCOUNT_RULES or
TRANSACTION_RULES at the bottom of this file.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Constants — adjust these to relax or tighten rules
# ---------------------------------------------------------------------------

EPOCH_MIN = 946684800    # 2000-01-01 00:00:00 UTC — oldest plausible transaction
EPOCH_MAX = 4102444800   # 2100-01-01 00:00:00 UTC — upper sanity bound
CURRENCY_RE = re.compile(r"^[A-Z]{3}$")
AMOUNT_RE = re.compile(r"^-?\d+\.\d{2}$")
EXPECTED_SCHEMA_VERSION = 4
PAYEE_MAX_LEN = 200      # SimpleFIN payee field; OFX NAME is 32 but full payee is longer
DESCRIPTION_MAX_LEN = 500
MEMO_MAX_LEN = 500


# ---------------------------------------------------------------------------
# Violation record
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Violation:
    conn_id: str
    acctid: str
    txn_id: str | None   # None for account-level violations
    rule: str
    message: str

    def __str__(self) -> str:
        loc = f"{self.conn_id}/{self.acctid}"
        if self.txn_id:
            loc += f" txn={self.txn_id}"
        return f"[{loc}] {self.rule}: {self.message}"


# ---------------------------------------------------------------------------
# Account-level rules
# Each takes an account dict and returns list[str] of violation messages.
# ---------------------------------------------------------------------------

def acct_id_nonempty(acct: dict[str, Any]) -> list[str]:
    """id must be a non-empty string."""
    return [] if acct.get("id", "") else ["id is empty or missing"]


def acct_name_nonempty(acct: dict[str, Any]) -> list[str]:
    """name must be a non-empty string."""
    return [] if acct.get("name", "") else ["name is empty or missing"]


def acct_currency_iso(acct: dict[str, Any]) -> list[str]:
    """currency must be a 3-letter uppercase ISO code (e.g. USD), or empty/absent.

    Convention: empty currency is treated as USD by the OFX emitter. Only
    non-empty values that don't conform to [A-Z]{3} are flagged.
    """
    v = acct.get("currency", "")
    if not v:
        return []  # empty → defaults to USD at serve time
    return [] if CURRENCY_RE.match(v) else [f"currency {v!r} does not match [A-Z]{{3}}"]


def acct_balance_decimal(acct: dict[str, Any]) -> list[str]:
    """balance must be a signed decimal string with exactly 2 decimal places."""
    v = acct.get("balance", "")
    return [] if AMOUNT_RE.match(str(v)) else [f"balance {v!r} does not match -?\\d+\\.\\d{{2}}"]


def acct_available_balance_decimal(acct: dict[str, Any]) -> list[str]:
    """available-balance must be null or a signed decimal string with 2 decimal places."""
    v = acct.get("available-balance")
    if v is None:
        return []
    return [] if AMOUNT_RE.match(str(v)) else [
        f"available-balance {v!r} does not match -?\\d+\\.\\d{{2}}"
    ]


def acct_balance_date_epoch(acct: dict[str, Any]) -> list[str]:
    """balance-date must be an integer epoch in [{EPOCH_MIN}, {EPOCH_MAX}]."""
    v = acct.get("balance-date")
    if not isinstance(v, int):
        return [f"balance-date {v!r} is not an integer"]
    if not (EPOCH_MIN <= v <= EPOCH_MAX):
        return [f"balance-date {v} out of range [{EPOCH_MIN}, {EPOCH_MAX}]"]
    return []


def acct_conn_id_nonempty(acct: dict[str, Any]) -> list[str]:
    """conn_id must be a non-empty string."""
    return [] if acct.get("conn_id", "") else ["conn_id is empty or missing"]


def acct_transactions_is_list(acct: dict[str, Any]) -> list[str]:
    """transactions must be a list."""
    v = acct.get("transactions")
    return [] if isinstance(v, list) else [f"transactions is {type(v).__name__}, expected list"]


# ---------------------------------------------------------------------------
# Transaction-level rules
# Each takes a transaction dict and returns list[str] of violation messages.
# ---------------------------------------------------------------------------

def txn_id_nonempty(txn: dict[str, Any]) -> list[str]:
    """id must be a non-empty string."""
    return [] if txn.get("id", "") else ["id is empty or missing"]


def txn_posted_epoch(txn: dict[str, Any]) -> list[str]:
    """posted must be an integer epoch in [{EPOCH_MIN}, {EPOCH_MAX}]."""
    v = txn.get("posted")
    if not isinstance(v, int):
        return [f"posted {v!r} is not an integer"]
    if not (EPOCH_MIN <= v <= EPOCH_MAX):
        return [f"posted {v} out of range [{EPOCH_MIN}, {EPOCH_MAX}]"]
    return []


def txn_amount_decimal(txn: dict[str, Any]) -> list[str]:
    """amount must be a signed decimal string with exactly 2 decimal places."""
    v = txn.get("amount", "")
    return [] if AMOUNT_RE.match(str(v)) else [
        f"amount {v!r} does not match -?\\d+\\.\\d{{2}}"
    ]


def txn_description_string(txn: dict[str, Any]) -> list[str]:
    """description must be a string no longer than DESCRIPTION_MAX_LEN characters."""
    v = txn.get("description")
    if not isinstance(v, str):
        return [f"description is {type(v).__name__}, expected str"]
    if len(v) > DESCRIPTION_MAX_LEN:
        return [f"description length {len(v)} exceeds {DESCRIPTION_MAX_LEN}"]
    return []


def txn_payee_string(txn: dict[str, Any]) -> list[str]:
    """payee must be a string no longer than PAYEE_MAX_LEN characters."""
    v = txn.get("payee")
    if not isinstance(v, str):
        return [f"payee is {type(v).__name__}, expected str"]
    if len(v) > PAYEE_MAX_LEN:
        return [f"payee length {len(v)} exceeds {PAYEE_MAX_LEN}"]
    return []


def txn_memo_string(txn: dict[str, Any]) -> list[str]:
    """memo must be a string no longer than MEMO_MAX_LEN characters."""
    v = txn.get("memo")
    if not isinstance(v, str):
        return [f"memo is {type(v).__name__}, expected str"]
    if len(v) > MEMO_MAX_LEN:
        return [f"memo length {len(v)} exceeds {MEMO_MAX_LEN}"]
    return []


def txn_transacted_at_epoch(txn: dict[str, Any]) -> list[str]:
    """transacted_at must be null or an integer epoch in [{EPOCH_MIN}, {EPOCH_MAX}]."""
    v = txn.get("transacted_at")
    if v is None:
        return []
    if not isinstance(v, int):
        return [f"transacted_at {v!r} is not an integer"]
    if not (EPOCH_MIN <= v <= EPOCH_MAX):
        return [f"transacted_at {v} out of range [{EPOCH_MIN}, {EPOCH_MAX}]"]
    return []


def txn_ids_unique_within_account(txn: dict[str, Any]) -> list[str]:
    """(checked at account level — placeholder so rule appears in TRANSACTION_RULES)"""
    return []  # enforced in validate_account_file, not per-txn


# ---------------------------------------------------------------------------
# Rule registries — add new rules here
# ---------------------------------------------------------------------------

ACCOUNT_RULES: list[Any] = [
    acct_id_nonempty,
    acct_name_nonempty,
    acct_currency_iso,
    acct_balance_decimal,
    acct_available_balance_decimal,
    acct_balance_date_epoch,
    acct_conn_id_nonempty,
    acct_transactions_is_list,
]

TRANSACTION_RULES: list[Any] = [
    txn_id_nonempty,
    txn_posted_epoch,
    txn_amount_decimal,
    txn_description_string,
    txn_payee_string,
    txn_memo_string,
    txn_transacted_at_epoch,
]


# ---------------------------------------------------------------------------
# Validator
# ---------------------------------------------------------------------------

def validate_account_file(path: Path, conn_id: str) -> list[Violation]:
    """Run all rules against one account JSON file. Returns violations (empty = clean)."""
    try:
        acct = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        return [Violation(conn_id=conn_id, acctid=path.stem, txn_id=None,
                          rule="json_parse", message=str(e))]

    acctid = acct.get("id") or path.stem
    violations: list[Violation] = []

    for rule_fn in ACCOUNT_RULES:
        for msg in rule_fn(acct):
            violations.append(Violation(
                conn_id=conn_id, acctid=acctid, txn_id=None,
                rule=rule_fn.__name__, message=msg,
            ))

    txns = acct.get("transactions", []) if isinstance(acct.get("transactions"), list) else []
    seen_ids: set[str] = set()
    for txn in txns:
        txn_id = txn.get("id") or ""
        if txn_id and txn_id in seen_ids:
            violations.append(Violation(
                conn_id=conn_id, acctid=acctid, txn_id=txn_id,
                rule="txn_ids_unique_within_account",
                message=f"duplicate transaction id {txn_id!r}",
            ))
        if txn_id:
            seen_ids.add(txn_id)

        for rule_fn in TRANSACTION_RULES:
            for msg in rule_fn(txn):
                violations.append(Violation(
                    conn_id=conn_id, acctid=acctid, txn_id=txn_id or None,
                    rule=rule_fn.__name__, message=msg,
                ))

    return violations


def validate_cache(cache_dir: Path) -> list[Violation]:
    """Validate all account files in cache_dir. Returns all violations found."""
    accounts_dir = cache_dir / "accounts"
    if not accounts_dir.exists():
        return []

    all_violations: list[Violation] = []
    for conn_dir in sorted(accounts_dir.iterdir()):
        if not conn_dir.is_dir():
            continue
        for acct_file in sorted(conn_dir.glob("*.json")):
            all_violations.extend(validate_account_file(acct_file, conn_dir.name))

    return all_violations
