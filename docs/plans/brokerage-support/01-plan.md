# Brokerage Support — Implementation Plan

See `00-intent.md` for the decision context and scope.

## Guiding principles

- **OFX alignment.** The neutral model uses OFX vocabulary (`UNITS`, `UNITPRICE`,
  `INCOMETYPE`, `BROKERID`, etc.) rather than SnapTrade vocabulary. The
  normalization seam translates SnapTrade shapes → OFX-shaped model.
- **No breakage to the cash model.** `Account`, `Transaction`, `Connection`,
  `StorageChunk`, `Storage` keep their current signatures. Investment types are
  additive.
- **Same architectural rules.** `St*` types stay inside
  `finstore.backends.snaptrade.*`. The arch tests gain a new rule mirroring Rule 3.
- **Positions are snapshots; transactions are append-only.** These two have
  different merge semantics and must not be conflated.

## Key design decisions

These were resolved before implementation started; they inform the sections
below.

| # | Decision |
|---|---|
| HTTP client | Raw `httpx` — SnapTrade HMAC signing is ~5 lines; no new dependency needed |
| Activity dedup | Dedup by `id`; warn in log if same ID reappears with a different amount |
| Position history | Latest-only snapshot (replace-on-write); historical snapshots deferred until there is a concrete consumer |
| `account_type` field | Stored explicitly in JSON; heuristic fallback for existing SimpleFIN files that lack it |
| `conn_id` for brokerages | SnapTrade `brokerage_slug` (e.g. `"SCHWAB"`), lowercased via `normalize_conn_id()` — stable across user reconnections |

---

## Phase 0 — Model layer (`finstore.model`)

**Output:** New frozen dataclasses in `finstore/model/__init__.py` (or
`finstore/model/investment.py` if the file grows unwieldy). No storage or
backend changes yet.

### 0.1 — `AccountType`

```python
class AccountType(str, Enum):
    CHECKING   = "CHECKING"
    SAVINGS    = "SAVINGS"
    CREDITCARD = "CREDITCARD"
    MONEYMRKT  = "MONEYMRKT"
    INVESTMENT = "INVESTMENT"   # brokerage / investment account
    OTHER      = "OTHER"
```

Add `account_type: AccountType = AccountType.CHECKING` to the existing `Account`
dataclass. The default means every currently-deserialised `Account` is unchanged.
The OFX gateway uses this field to route to `STMTRS` vs `INVSTMTRS` without
loading the full account file.

Also add `account_type: AccountType = AccountType.CHECKING` to `AccountSummary`
for the same reason.

### 0.2 — `Security`

Maps to OFX `SECINFO` / `SECID`. `(uniqueid_type, uniqueid)` is the logical
primary key.

```python
@dataclass(frozen=True)
class Security:
    uniqueid: str       # e.g. CUSIP "037833100", ISIN "US0378331005", ticker "AAPL"
    uniqueid_type: str  # "CUSIP" | "ISIN" | "TICKER" | "OTHER"
    name: str
    ticker: str         # may equal uniqueid when uniqueid_type is "TICKER"
    security_type: str  # "STOCK" | "MUTUALFUND" | "DEBT" | "OTHER"
```

### 0.3 — `InvestmentTransaction`

Maps to OFX `INVTRAN` + the typed wrappers (`INVBUY`, `INVSELL`, `REINVEST`,
`INCOME`, etc.).

```python
@dataclass(frozen=True)
class InvestmentTransaction:
    id: str
    trade_date: int             # epoch seconds UTC — OFX DTTRADE
    settle_date: int | None     # epoch seconds UTC — OFX DTSETTLE
    trntype: str                # well-known values listed below
    security_id: str | None     # None for cash-only trns (CONTRIBUTION, etc.)
    security_id_type: str | None
    units: Decimal | None       # shares; positive = buy/in, negative = sell/out
    unit_price: Decimal | None
    commission: Decimal | None
    fees: Decimal | None
    taxes: Decimal | None
    total: Decimal              # net settlement amount, signed (negative = debit)
    income_type: str | None     # set only for INCOME and REINVEST transactions
    description: str
    memo: str
    currency: str

# Well-known trntype values (open set — store unknown SnapTrade action_types as "OTHER"):
# "BUY" | "SELL" | "REINVEST" | "INCOME" | "TRANSFER" | "CONTRIBUTION"
# | "WITHDRAWAL" | "FEE" | "TAX" | "SPLIT" | "MARGININTEREST" | "RETOFCAP" | "OTHER"

# Well-known income_type values (OFX INCOMETYPE):
# "DIV" | "CGLONG" | "CGSHORT" | "INTEREST" | "OTHER"
```

### 0.4 — `Position`

Maps to OFX `INVPOS` (base of `POSSTOCK`, `POSMF`, `POSDEBT`).

```python
@dataclass(frozen=True)
class Position:
    security_id: str
    security_id_type: str
    units: Decimal          # shares held
    unit_price: Decimal     # price as of snapshot_date
    market_value: Decimal
    cost_basis: Decimal | None
    held_in_acct: str       # "CASH" | "MARGIN" | "SHORT" | "OTHER"
    pos_type: str           # "LONG" | "SHORT"
    snapshot_date: int      # epoch seconds UTC — when this position was fetched
```

### 0.5 — `InvestmentAccount`

Maps to OFX `INVSTMTRS`. A separate type from `Account` because its OFX
statement type, merge semantics, and on-disk format are all different.

```python
@dataclass(frozen=True)
class InvestmentAccount:
    id: str
    name: str
    currency: str
    broker_id: str                    # OFX BROKERID — maps to brokerage_slug
    available_cash: Decimal | None
    margin_balance: Decimal | None
    balance_date: int                 # epoch seconds UTC
    conn_id: str
    positions: tuple[Position, ...]
    investment_transactions: tuple[InvestmentTransaction, ...]
```

### 0.6 — `StorageChunk` extension

Two optional fields with empty-tuple defaults. Existing SimpleFIN callers need
no changes — they produce no investment data and the defaults hold.

```python
@dataclass(frozen=True)
class StorageChunk:
    accounts: tuple[Account, ...]
    connections: tuple[Connection, ...]
    investment_accounts: tuple[InvestmentAccount, ...] = ()
    securities: tuple[Security, ...] = ()
```

### 0.7 — `__all__` additions

Export from `finstore.model`: `AccountType`, `InvestmentAccount`,
`InvestmentTransaction`, `Position`, `Security`.

### Phase 0 tests

- Instantiate all new dataclasses; verify frozen (assignment raises).
- Verify `StorageChunk()` with only `accounts` + `connections` still works
  (empty tuple defaults).
- Verify `Account` with no `account_type` kwarg deserialises to `CHECKING`.

---

## Phase 1 — Storage layer (`finstore.storage`)

**Input:** Phase 0 model types.
**Output:** Extended `FilesystemStorage`, new `Storage` protocol methods, new
storage types, schema v5.

### 1.1 — Schema v5

Bump `SCHEMA_VERSION` to `5`. Schema v4 data on disk is not automatically
migrated — the user must run `finstore cache reset` and re-fetch.

**Upgrade note (for release):** Users upgrading from a v0.2.x cache will see a
`CacheSchemaMismatchError` on the first run. Fix: run `finstore cache reset`
then `finstore fetch` (and `finstore fetch --backend snaptrade` if SnapTrade is
configured). Investment data is new in v5 and has no v4 equivalent, so only
SimpleFIN history needs to be re-fetched.

### 1.2 — On-disk layout additions

```
<root>/
  meta.json                       # gains "investment_accounts" key (see below)
  accounts/                       # existing cash accounts — unchanged
    <conn_id>/
      <display_id>.json
  investment/                     # new subtree
    <conn_id>/                    # conn_id = normalized brokerage_slug
      <display_id>.json           # account metadata + investment_transactions
      <display_id>.positions.json # latest position snapshot only (replace-on-write)
  securities.json                 # shared registry — upserted on every merge
```

Merge semantics:
- `<display_id>.json` — investment transactions are appended, deduped by `id`.
  Same pattern as cash transactions.
- `<display_id>.positions.json` — **replaced wholesale** on every merge. Always
  the latest snapshot. Historical positions are out of scope.
- `securities.json` — full rewrite on each merge, upserted by
  `(uniqueid_type, uniqueid)`. File stays small (one entry per unique security
  ever seen).
- `meta.json` gains `"investment_accounts": { "<display_id>": { "conn_id",
  "broker_id", "last_fetch_at", "txn_count", "position_count",
  "earliest_trade", "latest_trade" } }` alongside the existing `"accounts"`.

### 1.3 — `account_type` persistence for cash accounts

`FilesystemStorage.merge_chunk` writes `account_type` into each cash account's
JSON file when present on the incoming `Account`. On read (`_dict_to_account`),
the field is read with a heuristic fallback for files written before this
change:

```python
def _infer_account_type(name: str) -> str:
    n = name.lower()
    if "credit" in n:
        return "CREDITCARD"
    if "money market" in n or "moneymrkt" in n:
        return "MONEYMRKT"
    return "CHECKING"
```

This heuristic is applied only when `"account_type"` is absent from the JSON
(i.e. files written by schema v4). Files written by v5 always have the explicit
value. The heuristic lives in `finstore/storage/paths.py` or a new
`finstore/storage/heuristics.py` so it is testable in isolation.

### 1.4 — New storage types

Add to `finstore/storage/types.py`:

```python
@dataclass(frozen=True)
class InvestmentAccountMeta:
    last_fetch_at: int
    txn_count: int
    position_count: int
    earliest_trade: int | None
    latest_trade: int | None
    conn_id: str
    broker_id: str

@dataclass(frozen=True)
class InvestmentAccountSummary:
    acctid: str
    name: str
    currency: str
    broker_id: str
    connection: Connection
    last_fetch_at: int | None
    txn_count: int
    position_count: int

@dataclass(frozen=True)
class CachedInvestmentAccount:
    account: InvestmentAccount
    investment_transactions: tuple[InvestmentTransaction, ...]
```

Extend `MergeStats` with optional investment counters (all default to 0 so
existing callers are unaffected):

```python
@dataclass(frozen=True)
class MergeStats:
    accounts_seen: int
    txns_new: int
    txns_duplicate: int
    inv_accounts_seen: int = 0
    inv_txns_new: int = 0
    inv_txns_duplicate: int = 0
    positions_written: int = 0
    securities_upserted: int = 0
```

### 1.5 — New `Storage` protocol methods

Add to `finstore/protocols.py`:

```python
def read_investment_account(
    self, tenant_id: str, account_id: str,
) -> CachedInvestmentAccount: ...

def read_investment_account_window(
    self, tenant_id: str, account_id: str,
    dtstart_epoch: int, dtend_epoch: int | None,
) -> CachedInvestmentAccount: ...

def list_investment_accounts(
    self, tenant_id: str = ...,
) -> tuple[InvestmentAccountSummary, ...]: ...

def read_securities(
    self, tenant_id: str,
    ids: tuple[tuple[str, str], ...] | None = None,
) -> tuple[Security, ...]: ...
```

`read_securities` with `ids=None` returns the full registry. With ids, it
filters to the given `(uniqueid_type, uniqueid)` pairs — the typical call from
an OFX server that wants only the securities referenced by a specific account's
positions.

### Phase 1 tests

- `merge_chunk` with only `investment_accounts` populated (no cash accounts) —
  verify investment subtree created, meta updated, cash subtree untouched.
- `merge_chunk` called twice for same investment account — verify transactions
  are appended and deduped; positions file is fully replaced, not merged.
- `read_securities` with and without `ids` filter.
- `list_investment_accounts` reflects meta correctly.
- `read_investment_account_window` filters by `trade_date` (not `settle_date`).
- `_infer_account_type` heuristic: "Platinum Visa Credit Card" → CREDITCARD,
  "Money Market Savings" → MONEYMRKT, "Checking 1234" → CHECKING.
- Schema v5 `read_meta` on a fresh store; v4 file raises `CacheSchemaMismatchError`.

---

## Phase 2 — SnapTrade backend (`finstore.backends.snaptrade`)

**Input:** Phase 0 model types + Phase 1 storage methods.
**Output:** A complete second backend, parallel to SimpleFIN.

Package layout:
```
finstore/backends/snaptrade/
  __init__.py   # exports SnapTradeBackend, SnapTradeCredentials
  models.py     # St* raw SnapTrade shapes — must not leak outside this package
  client.py     # StClient — httpx calls, returns St* types, no normalization
  backend.py    # SnapTradeBackend + normalization seam (St* → neutral model)
```

### 2.1 — `SnapTradeCredentials`

```python
@dataclass(frozen=True)
class SnapTradeCredentials:
    client_id: str      # partner-level, from env (SNAPTRADE_CLIENT_ID)
    consumer_key: str   # partner-level, from env (SNAPTRADE_CONSUMER_KEY)
    user_id: str        # per-user, from credential blob
    user_secret: str    # per-user, from credential blob
```

Per-user credentials are stored as `{"user_id": ..., "user_secret": ...}` JSON
in the credential blob under `backend_id = "snaptrade"`. The app layer reads the
blob and constructs this dataclass; the backend never calls into storage for its
own credentials (same pattern as SimpleFIN).

### 2.2 — `St*` types in `models.py`

Thin frozen dataclasses. These mirror SnapTrade REST response shapes closely
enough to parse them without loss, but are not a 1:1 copy — only fields the
normalization seam actually uses are included.

Key types:
- `StAccount` — `id, name, currency, account_type, number, brokerage_slug`
- `StBalance` — `account_id, cash, buying_power, total_value, currency`
- `StSecurity` — `id, symbol, name, figi_code, listing_exchange, security_type`
- `StPosition` — `account_id, security (StSecurity), units, price, market_value, average_purchase_price, currency`
- `StActivity` — `account_id, id, trade_date, settlement_date, action_type, units, price, gross_amount, commission, description, symbol (StSecurity | None), currency`

### 2.3 — `StClient` in `client.py`

Pure HTTP via `httpx.AsyncClient`. No normalization. Handles SnapTrade's
HMAC-SHA256 request signing — every request includes:

```python
import base64, hashlib, hmac, time

timestamp = str(int(time.time()))
sig = base64.b64encode(
    hmac.new(consumer_key.encode(), timestamp.encode(), hashlib.sha256).digest()
).decode()
# headers: {"timestamp": timestamp, "Signature": sig}
```

Key methods (all async):
- `get_accounts() -> list[StAccount]`
- `get_account_balance(account_id: str) -> StBalance`
- `get_positions(account_id: str) -> list[StPosition]`
- `get_activities(account_id: str, start_date: date, end_date: date) -> list[StActivity]`

Activity pagination: SnapTrade returns up to 1000 per call. `get_activities`
iterates date sub-windows until a response is shorter than the page cap or
`end_date` is reached.

### 2.4 — `SnapTradeBackend` in `backend.py` (the normalization seam)

`St*` → neutral model conversion happens here and **nowhere else**.

```python
class SnapTradeBackend:
    def __init__(
        self,
        credentials: SnapTradeCredentials,
        httpx_client: httpx.AsyncClient,
        *,
        activity_window_days: int = 90,
    ): ...

    async def fetch_and_persist(
        self,
        storage: Storage,
        *,
        tenant_id: str,
        dtstart_epoch: int,
        dtend_epoch: int | None = None,
    ) -> SnapTradeFetchReport: ...
```

**`conn_id` derivation:** `normalize_conn_id(account.brokerage_slug)` — e.g.
`"SCHWAB"` → `"schwab"`. This is stable across the user disconnecting and
reconnecting their brokerage, so on-disk data survives re-authentication.

**`action_type` → `trntype` mapping:**

| SnapTrade `action_type` | `trntype` | `income_type` |
|---|---|---|
| `BUY`, `BUY_TO_OPEN` | `BUY` | — |
| `SELL`, `SELL_TO_CLOSE` | `SELL` | — |
| `DIV`, `DIVIDEND` | `INCOME` | `DIV` |
| `REINVEST`, `DRIP` | `REINVEST` | `DIV` |
| `CONTRIBUTION`, `DEPOSIT` | `CONTRIBUTION` | — |
| `WITHDRAWAL` | `WITHDRAWAL` | — |
| `FEE`, `MANAGEMENT_FEE` | `FEE` | — |
| `TAX` | `TAX` | — |
| `TRANSFER`, `JOURNAL` | `TRANSFER` | — |
| `SPLIT` | `SPLIT` | — |
| anything else | `OTHER` | — |

Unknown `action_type` values are mapped to `OTHER` and logged at `WARNING` level
so the mapping table can be extended as real data surfaces new values.

**Security ID precedence:** FIGI (`figi_code`) → CUSIP (exchange-level, if
available) → ticker (`symbol`). `uniqueid_type` is set accordingly. The FIGI is
preferred because it is globally unique and exchange-independent; ticker is the
fallback when no structured ID exists.

**Activity dedup:** Dedup by `id` (same pattern as cash transactions). If an
incoming activity ID already exists in storage with a different `total`, log a
warning — this signals a brokerage correction and the stored entry is kept (the
user must reset the account to pull the corrected version).

**Other field mappings:**
- `StPosition.average_purchase_price` → `Position.cost_basis` (None if absent)
- `StBalance.cash` → `InvestmentAccount.available_cash`
- `StBalance.buying_power - cash` → `InvestmentAccount.margin_balance` (or None)
- Display ID: `sanitize_account_name(account.name)` — same helper as cash accounts

### 2.5 — Architecture rule 3b

Add to `tests/arch/test_imports.py`:

> **Rule 3b:** Outside `finstore.backends.snaptrade.*`, no module may import
> `finstore.backends.snaptrade.models` (the `St*` types).

Enforced with the same AST-walk as Rule 3 for SimpleFIN.

### 2.6 — `pyproject.toml` extras

Add a `snaptrade` optional dependency group (analogous to `simplefin`):

```toml
[project.optional-dependencies]
snaptrade = [
    "httpx>=0.27",
]

local = [
    "httpx>=0.27",
    ...  # existing
]
```

`httpx` is already in `local`; the `snaptrade` extra just makes the backend
installable standalone (`pip install 'finstore[snaptrade]'`) for library
consumers that use their own app layer.

### Phase 2 tests

- Each `action_type` → `trntype` mapping is exercised (one assertion per row in
  the table above, plus the unknown-action `OTHER` fallback).
- Security ID picking: FIGI wins over ticker when both present; ticker used when
  FIGI absent.
- Pagination: mock client returns 1000 activities on first call, 50 on second;
  verify both are included in the chunk.
- Dedup warning: same activity ID, different total → warning logged, stored
  entry unchanged.
- `fetch_and_persist` calls `storage.merge_chunk` with `StorageChunk` containing
  non-empty `investment_accounts` and `securities`, and empty `accounts`.
- HMAC signature header is present on every HTTP request (verified via
  `pytest-httpx` request capture).
- Rule 3b arch test passes.

---

## Phase 3 — `finstore_local` updates

**Input:** All prior phases.
**Output:** SnapTrade credential management, extended fetch command, dashboard
visibility for investment accounts.

### 3.1 — Settings

Add to `finstore_local.config.Settings`:

```python
snaptrade_client_id: str | None = None
snaptrade_consumer_key: SecretStr | None = None
```

Partner-level keys only. Per-user `user_id` / `user_secret` live in the
credential blob, never in settings or env.

### 3.2 — SnapTrade onboarding CLI

```
finstore snaptrade setup    # register user, persist secret, print OAuth link
finstore snaptrade status   # confirm registration and list connected brokerages
finstore snaptrade delete   # deregister user and wipe credential blob
```

**`setup` flow:**
1. Verify `SNAPTRADE_CLIENT_ID` and `SNAPTRADE_CONSUMER_KEY` are set; exit with
   clear message if not.
2. If a credential blob already exists, **skip registration** and jump directly
   to step 5 — this lets users run `setup` again to connect additional
   brokerages without losing their existing connections. (The original plan
   described a confirmation prompt before overwrite; that was revised because
   "add another brokerage" is the dominant re-run use case and silent reuse is
   safer than accidental re-registration.)
3. Call SnapTrade `registerSnapTradeUser` with a generated UUID → receive
   `userId` + `userSecret`.
4. Write `{"user_id": ..., "user_secret": ...}` to credential blob (mode 0600).
5. Call `loginSnapTradeUser` to get the OAuth redirect URL.
6. Print the URL and instruct the user to open it in a browser, authenticate at
   each brokerage, then run `finstore fetch --backend snaptrade`.

Steps 5–6 are synchronous from finstore's side — SnapTrade handles the OAuth
flow in the browser and signals completion there. No webhook receiver needed.
To force a full re-registration (e.g. after credential loss), run
`finstore snaptrade delete` first.

### 3.3 — Fetch command

Extend `finstore fetch` with a `--backend` option:

```
finstore fetch                      # SimpleFIN only (existing behaviour)
finstore fetch --backend simplefin  # explicit
finstore fetch --backend snaptrade  # SnapTrade only
finstore fetch --all                # all configured backends, SimpleFIN first
```

With `--all`, a failure in one backend is logged but does not abort the other.
Each backend reports its own `FetchReport` / `SnapTradeFetchReport`.

### 3.4 — Dashboard updates

- **Accounts list:** call both `storage.list_accounts` and
  `storage.list_investment_accounts`; render them in two sections or a unified
  table with an "Account type" column.
- **Account detail:** if routed to an investment account, render a positions
  table (security, units, unit price, market value, cost basis) and an
  investment transactions table (date, type, security, units, price, total)
  instead of the cash transactions view.
- **Dashboard summary card:** add `investment_account_count` and
  `total_positions` fields.

### Phase 3 tests

- `Settings` with valid `snaptrade_client_id` / `snaptrade_consumer_key`.
- `setup` with no existing blob → writes blob; with existing blob → prompts.
- `finstore fetch --backend snaptrade` constructs `SnapTradeBackend` with
  credentials read from the blob.
- `finstore fetch --all` runs both backends and reports both results even when
  SimpleFIN raises.
