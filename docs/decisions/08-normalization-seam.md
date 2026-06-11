# 08 — Backend is the only normalization boundary

**Decision:** `SimpleFINBackend.fetch_and_persist` is the single place where
raw SimpleFIN JSON (`Sf*` types) is converted to the neutral `Account` /
`Transaction` / `Connection` model. Nothing outside `finstore.backends.simplefin.*`
may import `finstore.backends.simplefin.models`.

**Rationale:**

Without this constraint, `Sf*` types leak into storage, the model layer, and
downstream consumers. Once leaked, renaming or removing an `Sf*` field requires
touching every consumer — the extraction becomes cosmetic rather than real.

The arch test (`test_simplefin_models_only_imported_inside_simplefin_package`)
enforces this via AST-walking so violations break CI without needing a full
import cycle.

**Consequence:**

```
SimpleFIN JSON
  → SfResponse        (backend-internal)
  → StorageChunk      (public model)
  → storage.merge_chunk(...)
```

The conversion functions (`_normalize`, `_to_account`, etc.) in `backend.py`
are private. Tests may import them directly to unit-test the conversion, but
they are not public API.
