"""Tests for finstore.backends.simplefin.activate."""
from __future__ import annotations

import base64
from dataclasses import dataclass, field

import httpx
import pytest
import pytest_asyncio  # noqa: F401 — ensures asyncio mode is active

from finstore.backends.simplefin.activate import _decode_setup_token, activate
from finstore.exceptions import BackendError

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_CLAIM_URL = "https://bridge.simplefin.org/simplefin/claim/abc123"
_ACCESS_URL = "https://user:pass@bridge.simplefin.org/simplefin"

# Standard-base64 encoded claim URL (no trailing padding).
_SETUP_TOKEN = base64.b64encode(_CLAIM_URL.encode()).decode().rstrip("=")


@dataclass
class _FakeStorage:
    _creds: dict[tuple[str, str], bytes] = field(default_factory=dict)

    def read_backend_credential(self, tenant_id: str, backend_id: str) -> bytes | None:
        return self._creds.get((tenant_id, backend_id))

    def write_backend_credential(
        self, tenant_id: str, backend_id: str, data: bytes
    ) -> None:
        self._creds[(tenant_id, backend_id)] = data

    def exists_backend_credential(self, tenant_id: str, backend_id: str) -> bool:
        return (tenant_id, backend_id) in self._creds


# ---------------------------------------------------------------------------
# _decode_setup_token
# ---------------------------------------------------------------------------


class TestDecodeSetupToken:
    def test_standard_base64(self) -> None:
        token = base64.b64encode(_CLAIM_URL.encode()).decode().rstrip("=")
        assert _decode_setup_token(token) == _CLAIM_URL

    def test_urlsafe_base64(self) -> None:
        token = base64.urlsafe_b64encode(_CLAIM_URL.encode()).decode().rstrip("=")
        assert _decode_setup_token(token) == _CLAIM_URL

    def test_garbage_raises_backend_error(self) -> None:
        with pytest.raises(BackendError):
            _decode_setup_token("not-a-valid-base64-encoded-url")

    def test_base64_non_https_raises_backend_error(self) -> None:
        encoded = base64.b64encode(b"ftp://bad.example/path").decode()
        with pytest.raises(BackendError):
            _decode_setup_token(encoded)


# ---------------------------------------------------------------------------
# activate()
# ---------------------------------------------------------------------------


class TestActivateWithSetupToken:
    @pytest.mark.asyncio
    async def test_exchanges_and_persists(self, httpx_mock: pytest.FixtureRequest) -> None:
        httpx_mock.add_response(url=_CLAIM_URL, method="POST", text=_ACCESS_URL)  # type: ignore[attr-defined]
        storage = _FakeStorage()

        async with httpx.AsyncClient() as client:
            await activate(_SETUP_TOKEN, storage=storage, tenant_id="local", client=client)

        assert storage.read_backend_credential("local", "simplefin") == _ACCESS_URL.encode()

    @pytest.mark.asyncio
    async def test_exchange_http_error_raises_backend_error(
        self, httpx_mock: pytest.FixtureRequest
    ) -> None:
        httpx_mock.add_response(url=_CLAIM_URL, method="POST", status_code=403)  # type: ignore[attr-defined]
        storage = _FakeStorage()

        async with httpx.AsyncClient() as client:
            with pytest.raises(BackendError, match="403"):
                await activate(_SETUP_TOKEN, storage=storage, tenant_id="local", client=client)

    @pytest.mark.asyncio
    async def test_exchange_bad_response_raises_backend_error(
        self, httpx_mock: pytest.FixtureRequest
    ) -> None:
        httpx_mock.add_response(url=_CLAIM_URL, method="POST", text="not-a-url")  # type: ignore[attr-defined]
        storage = _FakeStorage()

        async with httpx.AsyncClient() as client:
            with pytest.raises(BackendError, match="unexpected"):
                await activate(_SETUP_TOKEN, storage=storage, tenant_id="local", client=client)


class TestActivateWithAccessUrl:
    @pytest.mark.asyncio
    async def test_persists_directly_without_exchange(
        self, httpx_mock: pytest.FixtureRequest
    ) -> None:
        storage = _FakeStorage()

        async with httpx.AsyncClient() as client:
            await activate(_ACCESS_URL, storage=storage, tenant_id="local", client=client)

        assert storage.read_backend_credential("local", "simplefin") == _ACCESS_URL.encode()

    @pytest.mark.asyncio
    async def test_replaces_existing_credential(self, httpx_mock: pytest.FixtureRequest) -> None:
        storage = _FakeStorage()
        storage.write_backend_credential("local", "simplefin", b"old-cred")
        new_url = "https://new:cred@bridge.simplefin.org/simplefin"

        async with httpx.AsyncClient() as client:
            await activate(new_url, storage=storage, tenant_id="local", client=client)

        assert storage.read_backend_credential("local", "simplefin") == new_url.encode()


class TestActivateWithNone:
    @pytest.mark.asyncio
    async def test_loads_existing_credential(self, httpx_mock: pytest.FixtureRequest) -> None:
        storage = _FakeStorage()
        storage.write_backend_credential("local", "simplefin", _ACCESS_URL.encode())

        async with httpx.AsyncClient() as client:
            backend = await activate(None, storage=storage, tenant_id="local", client=client)

        assert backend is not None

    @pytest.mark.asyncio
    async def test_no_credential_raises_backend_error(
        self, httpx_mock: pytest.FixtureRequest
    ) -> None:
        storage = _FakeStorage()

        async with httpx.AsyncClient() as client:
            with pytest.raises(BackendError, match="no SimpleFIN credential"):
                await activate(None, storage=storage, tenant_id="local", client=client)
