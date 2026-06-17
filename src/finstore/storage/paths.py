"""Path-shape helpers shared by every filesystem storage call.

Default-path resolution (platformdirs etc.) is the *app layer's* job — see
`finstore_local.config.resolve_data_dir`. Core only handles mechanics.
"""
from __future__ import annotations

import re


def normalize_conn_id(conn_id: str) -> str:
    """Return a filesystem-safe directory name for a connection id.

    conn_id values from SimpleFIN are domain names (e.g. "www.wellsfargo.com")
    which are already safe. This replaces any character outside [A-Za-z0-9._-]
    with an underscore as a defensive measure, and falls back to "_unknown" for
    empty conn_ids.
    """
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", conn_id.strip().lower())
    return safe or "_unknown"


def sanitize_account_name(name: str) -> str:
    """Convert an account name to a stable, filesystem-safe display id.

    Transformation steps:
    1. Find all (digits) groups; remove those digit sequences from elsewhere
       in the string (deduplicates patterns like "...882 (882)").
    2. Replace non-alphanumeric runs with a single underscore.
    3. Strip leading/trailing underscores.
    4. If > 40 chars: first_19 + "__" + last_19 (preserves both ends).
    """
    paren_digits = re.findall(r'\((\d+)\)', name)
    working = name
    for digits in paren_digits:
        working = re.sub(r'(?<!\()' + re.escape(digits) + r'(?!\))', '', working)
    result = re.sub(r'[^A-Za-z0-9]+', '_', working).strip('_')
    if len(result) > 40:
        result = result[:19] + '__' + result[-19:]
    return result


def infer_account_type(name: str) -> str:
    """Heuristic account-type classification for files that lack an explicit field.

    Applied only when reading schema-v4 cash-account files written before
    ``account_type`` was persisted.  New writes always store the field explicitly.

    Returns one of the ``AccountType`` string values.
    """
    n = name.lower()
    if "credit" in n:
        return "CREDITCARD"
    if "money market" in n or "moneymrkt" in n:
        return "MONEYMRKT"
    return "CHECKING"


__all__ = ["infer_account_type", "normalize_conn_id", "sanitize_account_name"]
