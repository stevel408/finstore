"""`finstore.backend_status()` — activation status derived from Storage."""
from __future__ import annotations

from finstore import BACKENDS, backend_status
from tests.unit.api.test_protocols import FakeStorage


def test_backend_status_lists_all_known_backends_unactivated_by_default() -> None:
    storage = FakeStorage()

    statuses = backend_status(storage, "local")

    assert [s.id for s in statuses] == [b.id for b in BACKENDS]
    assert all(not s.activated for s in statuses)


def test_backend_status_reflects_persisted_credential() -> None:
    storage = FakeStorage()
    storage.write_backend_credential("local", "simplefin", b"secret")

    statuses = {s.id: s.activated for s in backend_status(storage, "local")}

    assert statuses["simplefin"] is True
    assert statuses["snaptrade"] is False


def test_backend_status_is_scoped_per_tenant() -> None:
    storage = FakeStorage()
    storage.write_backend_credential("tenant-a", "snaptrade", b"secret")

    statuses = {s.id: s.activated for s in backend_status(storage, "tenant-b")}

    assert statuses["snaptrade"] is False
