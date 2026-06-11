from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any


@dataclass(frozen=True)
class SfTransaction:
    id: str
    posted: int           # epoch seconds UTC
    amount: Decimal       # signed; "0.00" is legitimate (fee reversals)
    description: str
    payee: str
    memo: str
    transacted_at: int | None


@dataclass(frozen=True)
class SfAccount:
    id: str
    name: str
    currency: str
    balance: Decimal
    available_balance: Decimal | None
    balance_date: int             # epoch seconds UTC
    conn_id: str
    transactions: tuple[SfTransaction, ...]
    org: dict[str, Any] = field(default_factory=dict)
    holdings: tuple[dict[str, Any], ...] = ()


@dataclass(frozen=True)
class SfConnection:
    conn_id: str
    org_name: str
    org_id: str
    org_domain: str = ""
    sfin_url: str = ""
    org_url: str = ""


@dataclass(frozen=True)
class SfResponse:
    accounts: tuple[SfAccount, ...]
    connections: tuple[SfConnection, ...]
    errlist: tuple[tuple[str, str], ...]   # normalized (code, msg) pairs
    x_api_message: tuple[str, ...]


def _decode(data: dict[str, Any]) -> SfResponse:
    """Parse the raw SimpleFIN JSON (as returned by response.json()) into an SfResponse."""
    # Parse connections from the org entries inside accounts
    conn_map: dict[str, SfConnection] = {}
    accounts_raw = data.get("accounts", [])
    for acct in accounts_raw:
        org = acct.get("org", {})
        sfin_id = org.get("sfin-id", "")
        domain = org.get("domain", "")
        conn_id = sfin_id or domain or ""
        if conn_id and conn_id not in conn_map:
            conn_map[conn_id] = SfConnection(
                conn_id=conn_id,
                org_name=org.get("name", ""),
                org_id=org.get("id") or sfin_id or domain or "",
                org_domain=domain,
                sfin_url=org.get("sfin-url", ""),
                org_url=org.get("url", ""),
            )

    # Parse accounts
    accounts: list[SfAccount] = []
    for acct in accounts_raw:
        org = acct.get("org", {})
        sfin_id = org.get("sfin-id", "")
        domain = org.get("domain", "")
        conn_id = sfin_id or domain or ""

        avail_raw = acct.get("available-balance")
        available_balance = Decimal(avail_raw.strip()) if avail_raw is not None else None

        txns_raw = acct.get("transactions", [])
        transactions: list[SfTransaction] = []
        for txn in txns_raw:
            transactions.append(
                SfTransaction(
                    id=txn["id"],
                    posted=int(txn["posted"]),
                    amount=Decimal(txn["amount"].strip()),
                    description=txn.get("description", ""),
                    payee=txn.get("payee", ""),
                    memo=txn.get("memo", ""),
                    transacted_at=(
                        int(txn["transacted_at"])
                        if txn.get("transacted_at") is not None
                        else None
                    ),
                )
            )

        # Strip trailing slash from access URL path
        access_url = acct.get("url", "")
        if access_url:
            from urllib.parse import urlparse, urlunparse
            p = urlparse(access_url)
            access_url = urlunparse(p._replace(path=p.path.rstrip("/")))

        accounts.append(
            SfAccount(
                id=acct["id"],
                name=acct.get("name", ""),
                currency=acct.get("currency", ""),
                balance=Decimal(acct["balance"].strip()),
                available_balance=available_balance,
                balance_date=int(acct["balance-date"]),
                conn_id=conn_id,
                transactions=tuple(transactions),
                org=acct.get("org", {}),
                holdings=tuple(acct.get("holdings", [])),
            )
        )

    # Parse errlist — entries may be dicts or plain strings
    errlist_raw = data.get("errors", [])
    errlist: list[tuple[str, str]] = []
    for entry in errlist_raw:
        if isinstance(entry, dict):
            errlist.append((str(entry.get("code", "unknown")), str(entry.get("msg", ""))))
        else:
            errlist.append(("unknown", str(entry)))

    # Parse x-api-message (hyphenated key, may be null or absent)
    x_api_message_raw = data.get("x-api-message")
    if x_api_message_raw is None:
        x_api_message: tuple[str, ...] = ()
    elif isinstance(x_api_message_raw, list):
        x_api_message = tuple(str(m) for m in x_api_message_raw)
    else:
        x_api_message = (str(x_api_message_raw),)

    return SfResponse(
        accounts=tuple(accounts),
        connections=tuple(conn_map.values()),
        errlist=tuple(errlist),
        x_api_message=x_api_message,
    )
