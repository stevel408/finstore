"""Tests for StClient — HMAC signing and endpoint shapes."""
from __future__ import annotations

import base64
import hashlib
import hmac

import httpx
import pytest
from pytest_httpx import HTTPXMock

from finstore.backends.snaptrade.client import StClient, _BASE_URL


def _make_client(httpx_client: httpx.AsyncClient) -> StClient:
    return StClient(
        client_id="test-client",
        consumer_key="test-consumer-key",
        user_id="test-user",
        user_secret="test-secret",
        httpx_client=httpx_client,
    )


class TestHmacSigning:
    @pytest.mark.asyncio
    async def test_timestamp_header_present(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(json=[])
        async with httpx.AsyncClient() as http:
            client = _make_client(http)
            await client.get_accounts()

        req = httpx_mock.get_requests()[0]
        assert "timestamp" in req.headers

    @pytest.mark.asyncio
    async def test_signature_header_present(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(json=[])
        async with httpx.AsyncClient() as http:
            client = _make_client(http)
            await client.get_accounts()

        req = httpx_mock.get_requests()[0]
        assert "Signature" in req.headers

    @pytest.mark.asyncio
    async def test_signature_is_valid_hmac(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(json=[])
        async with httpx.AsyncClient() as http:
            client = _make_client(http)
            await client.get_accounts()

        req = httpx_mock.get_requests()[0]
        timestamp = req.headers["timestamp"]
        sig = req.headers["Signature"]
        expected = base64.b64encode(
            hmac.new(
                b"test-consumer-key",
                timestamp.encode(),
                hashlib.sha256,
            ).digest()
        ).decode()
        assert sig == expected

    @pytest.mark.asyncio
    async def test_client_id_in_query_params(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(json=[])
        async with httpx.AsyncClient() as http:
            client = _make_client(http)
            await client.get_accounts()

        req = httpx_mock.get_requests()[0]
        assert "clientId=test-client" in str(req.url)

    @pytest.mark.asyncio
    async def test_user_id_in_query_params(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(json=[])
        async with httpx.AsyncClient() as http:
            client = _make_client(http)
            await client.get_accounts()

        req = httpx_mock.get_requests()[0]
        assert "userId=test-user" in str(req.url)

    @pytest.mark.asyncio
    async def test_auth_headers_on_every_call(self, httpx_mock: HTTPXMock) -> None:
        """Each call independently generates auth headers."""
        httpx_mock.add_response(json=[])
        httpx_mock.add_response(json=[])
        async with httpx.AsyncClient() as http:
            client = _make_client(http)
            await client.get_accounts()
            await client.get_brokerage_authorizations()

        reqs = httpx_mock.get_requests()
        assert len(reqs) == 2
        for req in reqs:
            assert "timestamp" in req.headers
            assert "Signature" in req.headers


class TestPagination:
    @pytest.mark.asyncio
    async def test_bisects_when_page_limit_hit(self, httpx_mock: HTTPXMock) -> None:
        """When a range hits PAGE_LIMIT, client bisects and makes additional calls."""
        from datetime import date
        import finstore.backends.snaptrade.client as client_mod

        page_limit = client_mod._PAGE_LIMIT
        full_page = [
            {"id": f"a{i}", "account": {"id": "acct-1"}, "type": "BUY",
             "trade_date": "2024-01-12", "units": 1.0, "price": 10.0,
             "amount": -10.0, "fee": 0.0, "currency": "USD", "description": "buy"}
            for i in range(page_limit)
        ]
        # First call (full range) → PAGE_LIMIT → triggers bisection
        # Second call (first half) → 50 → done
        # Third call (second half) → 50 → done
        half_page = [
            {"id": f"b{i}", "account": {"id": "acct-1"}, "type": "BUY",
             "trade_date": "2024-01-12", "units": 1.0, "price": 10.0,
             "amount": -10.0, "fee": 0.0, "currency": "USD", "description": "buy"}
            for i in range(50)
        ]
        httpx_mock.add_response(json=full_page)   # first call
        httpx_mock.add_response(json=half_page)   # first half
        httpx_mock.add_response(json=half_page)   # second half

        async with httpx.AsyncClient() as http:
            client = _make_client(http)
            results = await client.get_activities(date(2024, 1, 1), date(2024, 3, 31))

        # Total = 50 + 50 from the bisected halves
        assert len(results) == 100
        assert len(httpx_mock.get_requests()) == 3

    @pytest.mark.asyncio
    async def test_warns_when_single_day_hits_limit(
        self, httpx_mock: HTTPXMock, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Single-day range (start==end) that hits PAGE_LIMIT logs a warning."""
        from datetime import date
        import finstore.backends.snaptrade.client as client_mod

        page_limit = client_mod._PAGE_LIMIT
        full_page = [
            {"id": f"a{i}", "account": {"id": "acct-1"}, "type": "BUY",
             "trade_date": "2024-01-01", "units": 1.0, "price": 10.0,
             "amount": -10.0, "fee": 0.0, "currency": "USD", "description": "buy"}
            for i in range(page_limit)
        ]
        httpx_mock.add_response(json=full_page)

        async with httpx.AsyncClient() as http:
            client = _make_client(http)
            with caplog.at_level("WARNING", logger="finstore.backends.snaptrade.client"):
                results = await client.get_activities(date(2024, 1, 1), date(2024, 1, 1))

        assert len(results) == page_limit
        assert any("page_limit" in r.message for r in caplog.records)

    @pytest.mark.asyncio
    async def test_two_day_range_is_bisected_not_truncated(
        self, httpx_mock: HTTPXMock
    ) -> None:
        """A 2-day range (delta=1) that hits PAGE_LIMIT must bisect, not warn."""
        from datetime import date
        import finstore.backends.snaptrade.client as client_mod

        page_limit = client_mod._PAGE_LIMIT
        full_page = [
            {"id": f"a{i}", "account": {"id": "acct-1"}, "type": "BUY",
             "trade_date": "2024-01-01", "units": 1.0, "price": 10.0,
             "amount": -10.0, "fee": 0.0, "currency": "USD", "description": "buy"}
            for i in range(page_limit)
        ]
        half_page = [
            {"id": f"b{i}", "account": {"id": "acct-1"}, "type": "BUY",
             "trade_date": "2024-01-01", "units": 1.0, "price": 10.0,
             "amount": -10.0, "fee": 0.0, "currency": "USD", "description": "buy"}
            for i in range(5)
        ]
        httpx_mock.add_response(json=full_page)  # 2024-01-01→2024-01-02 hits limit
        httpx_mock.add_response(json=half_page)  # 2024-01-01→2024-01-01 (first half)
        httpx_mock.add_response(json=half_page)  # 2024-01-02→2024-01-02 (second half)

        async with httpx.AsyncClient() as http:
            client = _make_client(http)
            results = await client.get_activities(date(2024, 1, 1), date(2024, 1, 2))

        # Both halves returned, not the truncated full-page
        assert len(results) == 10
        assert len(httpx_mock.get_requests()) == 3


class TestEndpointPaths:
    @pytest.mark.asyncio
    async def test_get_accounts_url(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(json=[])
        async with httpx.AsyncClient() as http:
            await _make_client(http).get_accounts()
        assert httpx_mock.get_requests()[0].url.path == "/api/v1/accounts"

    @pytest.mark.asyncio
    async def test_get_positions_url(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(json=[])
        async with httpx.AsyncClient() as http:
            await _make_client(http).get_positions("acct-99")
        assert "/accounts/acct-99/positions" in str(httpx_mock.get_requests()[0].url)

    @pytest.mark.asyncio
    async def test_get_activities_date_params(self, httpx_mock: HTTPXMock) -> None:
        from datetime import date
        httpx_mock.add_response(json=[])
        async with httpx.AsyncClient() as http:
            await _make_client(http).get_activities(
                date(2024, 1, 1), date(2024, 3, 31)
            )
        url = str(httpx_mock.get_requests()[0].url)
        assert "startDate=2024-01-01" in url
        assert "endDate=2024-03-31" in url

    @pytest.mark.asyncio
    async def test_get_balance_prefers_usd(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(json=[
            {"currency": {"code": "CAD"}, "cash": 100.0},
            {"currency": {"code": "USD"}, "cash": 500.0, "buying_power": 500.0},
        ])
        async with httpx.AsyncClient() as http:
            bal = await _make_client(http).get_account_balance("acct-1")
        from decimal import Decimal
        assert bal.cash == Decimal("500.0")
        assert bal.currency == "USD"
