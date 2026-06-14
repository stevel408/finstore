"""Tests for FilesystemStorage credential persistence methods."""
from __future__ import annotations

from pathlib import Path

from finstore.storage.filesystem import FilesystemStorage


class TestReadBackendCredential:
    def test_returns_none_when_not_written(self, tmp_path: Path) -> None:
        storage = FilesystemStorage(root=tmp_path)
        assert storage.read_backend_credential("local", "simplefin") is None

    def test_roundtrip(self, tmp_path: Path) -> None:
        storage = FilesystemStorage(root=tmp_path)
        data = b"https://user:pass@bridge.simplefin.org/simplefin"
        storage.write_backend_credential("local", "simplefin", data)
        assert storage.read_backend_credential("local", "simplefin") == data

    def test_namespaced_by_tenant(self, tmp_path: Path) -> None:
        storage = FilesystemStorage(root=tmp_path)
        storage.write_backend_credential("alice", "simplefin", b"alice-cred")
        storage.write_backend_credential("bob", "simplefin", b"bob-cred")
        assert storage.read_backend_credential("alice", "simplefin") == b"alice-cred"
        assert storage.read_backend_credential("bob", "simplefin") == b"bob-cred"

    def test_namespaced_by_backend(self, tmp_path: Path) -> None:
        storage = FilesystemStorage(root=tmp_path)
        storage.write_backend_credential("local", "simplefin", b"sf")
        storage.write_backend_credential("local", "other", b"other")
        assert storage.read_backend_credential("local", "simplefin") == b"sf"
        assert storage.read_backend_credential("local", "other") == b"other"


class TestWriteBackendCredential:
    def test_creates_file_mode_0600(self, tmp_path: Path) -> None:
        storage = FilesystemStorage(root=tmp_path)
        storage.write_backend_credential("local", "simplefin", b"secret")
        path = tmp_path / "tenants" / "local" / "credentials" / "simplefin.bin"
        assert path.exists()
        assert oct(path.stat().st_mode & 0o777) == oct(0o600)

    def test_atomic_replace(self, tmp_path: Path) -> None:
        storage = FilesystemStorage(root=tmp_path)
        storage.write_backend_credential("local", "simplefin", b"first")
        storage.write_backend_credential("local", "simplefin", b"second")
        assert storage.read_backend_credential("local", "simplefin") == b"second"

    def test_creates_parent_directories(self, tmp_path: Path) -> None:
        storage = FilesystemStorage(root=tmp_path)
        storage.write_backend_credential("new-tenant", "new-backend", b"x")
        path = tmp_path / "tenants" / "new-tenant" / "credentials" / "new-backend.bin"
        assert path.exists()

    def test_no_tmp_file_left_behind(self, tmp_path: Path) -> None:
        storage = FilesystemStorage(root=tmp_path)
        storage.write_backend_credential("local", "simplefin", b"data")
        cred_dir = tmp_path / "tenants" / "local" / "credentials"
        tmp_files = list(cred_dir.glob("*.tmp"))
        assert tmp_files == []


class TestExistsBackendCredential:
    def test_false_when_not_written(self, tmp_path: Path) -> None:
        storage = FilesystemStorage(root=tmp_path)
        assert not storage.exists_backend_credential("local", "simplefin")

    def test_true_after_write(self, tmp_path: Path) -> None:
        storage = FilesystemStorage(root=tmp_path)
        storage.write_backend_credential("local", "simplefin", b"x")
        assert storage.exists_backend_credential("local", "simplefin")

    def test_false_for_other_tenant(self, tmp_path: Path) -> None:
        storage = FilesystemStorage(root=tmp_path)
        storage.write_backend_credential("alice", "simplefin", b"x")
        assert not storage.exists_backend_credential("bob", "simplefin")


class TestDeleteBackendCredential:
    def test_returns_false_when_not_present(self, tmp_path: Path) -> None:
        storage = FilesystemStorage(root=tmp_path)
        assert storage.delete_backend_credential("local", "simplefin") is False

    def test_returns_true_when_removed(self, tmp_path: Path) -> None:
        storage = FilesystemStorage(root=tmp_path)
        storage.write_backend_credential("local", "simplefin", b"x")
        assert storage.delete_backend_credential("local", "simplefin") is True
        assert not storage.exists_backend_credential("local", "simplefin")

    def test_idempotent(self, tmp_path: Path) -> None:
        storage = FilesystemStorage(root=tmp_path)
        storage.write_backend_credential("local", "simplefin", b"x")
        storage.delete_backend_credential("local", "simplefin")
        # Second call must not raise; just reports "nothing to delete."
        assert storage.delete_backend_credential("local", "simplefin") is False

    def test_other_tenants_untouched(self, tmp_path: Path) -> None:
        storage = FilesystemStorage(root=tmp_path)
        storage.write_backend_credential("alice", "simplefin", b"a")
        storage.write_backend_credential("bob", "simplefin", b"b")
        storage.delete_backend_credential("alice", "simplefin")
        assert storage.read_backend_credential("bob", "simplefin") == b"b"

    def test_missing_root_returns_false(self, tmp_path: Path) -> None:
        # Safe-on-missing-root: construction does no I/O.
        storage = FilesystemStorage(root=tmp_path / "does-not-exist")
        assert storage.delete_backend_credential("local", "simplefin") is False
