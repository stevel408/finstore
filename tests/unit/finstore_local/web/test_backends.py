"""`finstore_local.web.backends.backend_status` — layers deployment-specific
overrides (env-supplied SimpleFIN URL, SnapTrade partner keys) on top of
`finstore.backend_status()`'s persisted-credential signal."""
from __future__ import annotations

from pathlib import Path

import pytest

from finstore.storage.filesystem import FilesystemStorage
from finstore_local.config import Settings
from finstore_local.web.backends import backend_status


@pytest.fixture
def storage(tmp_path: Path) -> FilesystemStorage:
    return FilesystemStorage(root=tmp_path)


def test_both_unconfigured_by_default(storage: FilesystemStorage) -> None:
    settings = Settings(_env_file=None)

    statuses = {b["id"]: b for b in backend_status(storage, "local", settings)}

    assert statuses["simplefin"]["configured"] is False
    assert statuses["snaptrade"]["configured"] is False
    assert statuses["simplefin"]["docs_url"].endswith("#3-simplefin-setup")
    assert statuses["snaptrade"]["docs_url"].endswith("#4-snaptrade-setup")


def test_simplefin_configured_via_persisted_credential(storage: FilesystemStorage) -> None:
    storage.write_backend_credential("local", "simplefin", b"https://access.url")
    settings = Settings(_env_file=None)

    statuses = {b["id"]: b for b in backend_status(storage, "local", settings)}

    assert statuses["simplefin"]["configured"] is True


def test_simplefin_configured_via_env_override_without_persisted_credential(
    storage: FilesystemStorage,
) -> None:
    settings = Settings(
        _env_file=None, simplefin_access_url="https://user:pass@host/path"
    )

    statuses = {b["id"]: b for b in backend_status(storage, "local", settings)}

    assert statuses["simplefin"]["configured"] is True


def test_snaptrade_requires_both_partner_keys_and_persisted_credential(
    storage: FilesystemStorage,
) -> None:
    settings = Settings(
        _env_file=None, snaptrade_client_id="cid", snaptrade_consumer_key="ckey"
    )

    # Partner keys alone are not enough — the user hasn't registered yet.
    statuses = {b["id"]: b for b in backend_status(storage, "local", settings)}
    assert statuses["snaptrade"]["configured"] is False

    storage.write_backend_credential("local", "snaptrade", b'{"type": "personal"}')
    statuses = {b["id"]: b for b in backend_status(storage, "local", settings)}
    assert statuses["snaptrade"]["configured"] is True


def test_snaptrade_credential_without_partner_keys_is_not_configured(
    storage: FilesystemStorage,
) -> None:
    storage.write_backend_credential("local", "snaptrade", b'{"type": "personal"}')
    settings = Settings(_env_file=None)

    statuses = {b["id"]: b for b in backend_status(storage, "local", settings)}

    assert statuses["snaptrade"]["configured"] is False
