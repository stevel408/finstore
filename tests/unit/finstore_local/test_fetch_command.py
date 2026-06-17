"""Tests for the extended fetch command — backend routing and --all flag."""
from __future__ import annotations

import json
import sys
from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from finstore.model import Connection, StorageChunk
from finstore.storage.exceptions import CacheEmptyError
from finstore.storage.filesystem import FilesystemStorage
from finstore.storage.types import MergeStats
from finstore_local.cli.fetch import _resolve_start, run


# ---------------------------------------------------------------------------
# _resolve_start
# ---------------------------------------------------------------------------


class TestResolveStart:
    def test_explicit_date_parsed(self, tmp_path: Path) -> None:
        storage = FilesystemStorage(root=tmp_path)
        epoch = _resolve_start("2024-01-15", 1_700_000_000, storage)
        from datetime import datetime, timezone
        expected = int(datetime(2024, 1, 15, tzinfo=timezone.utc).timestamp())
        assert epoch == expected

    def test_invalid_date_exits(self, tmp_path: Path) -> None:
        storage = FilesystemStorage(root=tmp_path)
        with pytest.raises(SystemExit):
            _resolve_start("not-a-date", 1_700_000_000, storage)

    def test_defaults_to_90_days_when_cache_empty(self, tmp_path: Path) -> None:
        storage = FilesystemStorage(root=tmp_path)
        now = 1_700_000_000
        epoch = _resolve_start(None, now, storage)
        assert epoch == now - 90 * 86400


# ---------------------------------------------------------------------------
# Settings — snaptrade fields
# ---------------------------------------------------------------------------


class TestSnaptradeSettings:
    def test_snaptrade_fields_default_none(self) -> None:
        from finstore_local.config import Settings
        s = Settings(_env_file=None)
        assert s.snaptrade_client_id is None
        assert s.snaptrade_consumer_key is None

    def test_snaptrade_fields_set(self) -> None:
        from finstore_local.config import Settings
        s = Settings(
            _env_file=None,
            snaptrade_client_id="cid",
            snaptrade_consumer_key="ckey",
        )
        assert s.snaptrade_client_id == "cid"
        assert s.snaptrade_consumer_key is not None
        assert s.snaptrade_consumer_key.get_secret_value() == "ckey"


# ---------------------------------------------------------------------------
# Credential blob round-trip
# ---------------------------------------------------------------------------


class TestSnaptradeCredentialBlob:
    def test_write_and_read_blob(self, tmp_path: Path) -> None:
        storage = FilesystemStorage(root=tmp_path)
        blob = json.dumps({"user_id": "uid-1", "user_secret": "sec-1"}).encode()
        storage.write_backend_credential("local", "snaptrade", blob)

        raw = storage.read_backend_credential("local", "snaptrade")
        assert raw is not None
        data = json.loads(raw.decode())
        assert data["user_id"] == "uid-1"
        assert data["user_secret"] == "sec-1"

    def test_missing_blob_returns_none(self, tmp_path: Path) -> None:
        storage = FilesystemStorage(root=tmp_path)
        assert storage.read_backend_credential("local", "snaptrade") is None

    def test_delete_blob(self, tmp_path: Path) -> None:
        storage = FilesystemStorage(root=tmp_path)
        blob = json.dumps({"user_id": "u", "user_secret": "s"}).encode()
        storage.write_backend_credential("local", "snaptrade", blob)
        assert storage.delete_backend_credential("local", "snaptrade") is True
        assert storage.read_backend_credential("local", "snaptrade") is None


# ---------------------------------------------------------------------------
# fetch run() — backend routing
# ---------------------------------------------------------------------------


class TestFetchBackendRouting:
    def _make_settings(
        self,
        *,
        has_simplefin: bool = False,
        has_snaptrade: bool = False,
    ) -> MagicMock:
        s = MagicMock()
        s.simplefin_access_url = (
            MagicMock(get_secret_value=lambda: "https://u:p@h/p") if has_simplefin else None
        )
        s.snaptrade_client_id = "cid" if has_snaptrade else None
        s.snaptrade_consumer_key = (
            MagicMock(get_secret_value=lambda: "ckey") if has_snaptrade else None
        )
        s.simplefin_timeout_secs = 30.0
        s.simplefin_max_retries = 1
        s.chunk_window_days = 90
        s.log_level = "INFO"
        s.debug = False
        return s

    def _patches(self, settings: MagicMock, storage: MagicMock, tmp_path: Path):
        return [
            patch("finstore_local.config.load_settings", return_value=settings),
            patch("finstore_local.config.resolve_data_dir", return_value=tmp_path),
            patch("finstore.storage.filesystem.FilesystemStorage", return_value=storage),
        ]

    def test_unknown_backend_exits(self, tmp_path: Path) -> None:
        storage = MagicMock()
        storage.read_meta.side_effect = CacheEmptyError("empty")
        settings = self._make_settings()
        with pytest.raises(SystemExit) as exc:
            with patch("finstore_local.config.load_settings", return_value=settings):
                with patch("finstore_local.config.resolve_data_dir", return_value=tmp_path):
                    with patch("finstore.storage.filesystem.FilesystemStorage", return_value=storage):
                        run(backend="invalid", env_file=None)
        assert exc.value.code == 2

    def test_no_backends_configured_exits(self, tmp_path: Path) -> None:
        storage = MagicMock()
        storage.read_backend_credential.return_value = None
        storage.read_meta.side_effect = CacheEmptyError("empty")
        settings = self._make_settings()
        with pytest.raises(SystemExit) as exc:
            with patch("finstore_local.config.load_settings", return_value=settings):
                with patch("finstore_local.config.resolve_data_dir", return_value=tmp_path):
                    with patch("finstore.storage.filesystem.FilesystemStorage", return_value=storage):
                        run(env_file=None)
        assert exc.value.code == 2

    def test_snaptrade_missing_blob_returns_error(self, tmp_path: Path) -> None:
        storage = MagicMock()
        storage.read_backend_credential.return_value = None
        storage.read_meta.side_effect = CacheEmptyError("empty")
        settings = self._make_settings(has_snaptrade=True)
        with pytest.raises(SystemExit) as exc:
            with patch("finstore_local.config.load_settings", return_value=settings):
                with patch("finstore_local.config.resolve_data_dir", return_value=tmp_path):
                    with patch("finstore.storage.filesystem.FilesystemStorage", return_value=storage):
                        run(backend="snaptrade", env_file=None)
        assert exc.value.code == 1
