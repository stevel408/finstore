# Brokerage Support — Now In Scope via SnapTrade

**Decision revised 2026-06-16** (original 2026-06-03 ruling overturned — see rationale below).

## Why the original ruling no longer holds

The 2026-06-03 decision correctly found that SimpleFIN cannot supply the
investment-specific fields that OFX `INVSTMTRS` requires: shares, unit price,
action type, and a per-transaction security identifier are structurally absent
from SimpleFIN's feed.

**SnapTrade changes this.** SnapTrade is a dedicated brokerage connectivity API
that provides exactly the data SimpleFIN lacks:

| Required OFX field | SimpleFIN | SnapTrade |
|--------------------|-----------|-----------|
| Trade date | — | ✓ |
| Units (shares) | — | ✓ |
| Unit price | — | ✓ |
| Transaction type (BUY/SELL/REINVEST/INCOME/…) | — | ✓ |
| Security identifier (CUSIP/TICKER/ISIN) | — | ✓ |
| Position snapshot (UNITS + MKTVAL) | opaque blob, discarded | ✓ structured |

The constraint in the original decision was a **data-availability** problem, not
an architectural one. With SnapTrade as a second backend, the architectural
framework (normalization seam, storage abstraction, protocol contracts) is
exactly right — we just need to add the investment-specific model vocabulary.

## Scope of this initiative

1. **Extend `finstore.model`** with OFX-aligned investment types: `Security`,
   `Position`, `InvestmentTransaction`, `InvestmentAccount`. These sit
   *alongside* the existing cash-account model; cash accounts are unchanged.

2. **Extend `finstore.storage`** (schema v5) to persist investment accounts,
   position snapshots, and a securities registry in addition to the existing
   cash-account store.

3. **Add `finstore.backends.snaptrade`** as the second backend. The normalization
   seam (`St*` → neutral model) mirrors the SimpleFIN pattern exactly.

4. **Update `finstore_local`** with SnapTrade credentials management (partner key
   in env; per-user secret in the credential blob store), a setup CLI flow, and
   dashboard visibility for investment accounts.

## What is still out of scope

- Connecting SimpleFIN brokerage accounts for investment data. The original
  ruling on SimpleFIN stands — its brokerage feed lacks the required fields and
  should not be connected for investment bookkeeping.
- Real-time or streaming prices. Positions are point-in-time snapshots fetched
  on demand.
- Options / derivatives. SnapTrade returns them but OFX options support is
  complex. Phase 1 covers stocks and mutual funds; options are deferred.
- Multi-user (cloud) credential management. The existing single-tenant model
  applies; per-user SnapTrade secrets are stored as credential blobs under the
  local tenant.

## Practical guidance (updated)

Use SimpleFIN for checking, savings, and credit card accounts.

Use SnapTrade for brokerage and investment accounts. Do **not** connect the same
brokerage accounts through SimpleFIN — the cash-level mirror transactions are
noisy and not meaningful for investment bookkeeping.

For accounts that exist in both (e.g. a Schwab checking account within a
Schwab brokerage), connect the checking account through SimpleFIN and the
investment accounts through SnapTrade only.
