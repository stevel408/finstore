import asyncio
import json

import httpx
import pytest

from finstore.backends.simplefin.client import (
    WINDOW_CAP_CODE,
    WINDOW_CAP_MSG_FRAGMENT,
    SimpleFinClient,
    UpstreamClientError,
    UpstreamResponseError,
    UpstreamServerError,
    UpstreamTransportError,
    _accounts_endpoint,
    _filter_errlist,
    _sanitize_msg,
    _windows,
)
from finstore.exceptions import BackendError, FinstoreError

# ---------------------------------------------------------------------------
# _windows
# ---------------------------------------------------------------------------

class TestWindows:
    def test_exactly_one_window_when_range_equals_window(self):
        wins = _windows(0, 90 * 86400, 90 * 86400)
        assert len(wins) == 1
        assert wins[0] == (0, 90 * 86400)

    def test_two_windows_for_double_range(self):
        wins = _windows(0, 180 * 86400, 90 * 86400)
        assert len(wins) == 2
        # Each window <= 90 days wide
        for start, end in wins:
            assert end - start <= 90 * 86400
        # Second window ends at 180 days
        assert wins[1][1] == 180 * 86400
        # Windows are contiguous
        assert wins[0][1] == wins[1][0]

    def test_five_windows_for_365_days(self):
        wins = _windows(0, 365 * 86400, 90 * 86400)
        assert len(wins) == 5
        # All windows <= 90 days
        for start, end in wins:
            assert end - start <= 90 * 86400
        # Contiguous
        for i in range(len(wins) - 1):
            assert wins[i][1] == wins[i + 1][0]
        # Last window ends at 365 days
        assert wins[-1][1] == 365 * 86400

    def test_windows_oldest_first(self):
        wins = _windows(1000, 1000 + 200 * 86400, 90 * 86400)
        starts = [w[0] for w in wins]
        assert starts == sorted(starts)

    def test_empty_range_returns_one_window(self):
        """dtstart == end_anchor: returns exactly one degenerate window."""
        wins = _windows(500, 500, 90 * 86400)
        assert len(wins) == 1
        assert wins[0] == (500, 500)

    def test_non_zero_start(self):
        start = 1_700_000_000
        end = start + 180 * 86400
        wins = _windows(start, end, 90 * 86400)
        assert len(wins) == 2
        assert wins[0][0] == start
        assert wins[-1][1] == end


# ---------------------------------------------------------------------------
# _filter_errlist
# ---------------------------------------------------------------------------

class TestFilterErrlist:
    def test_drops_window_cap_entry(self):
        errlist = (
            (WINDOW_CAP_CODE, f"Request {WINDOW_CAP_MSG_FRAGMENT}"),
        )
        result = _filter_errlist(errlist)
        assert result == []

    def test_keeps_non_cap_entries(self):
        errlist = (
            ("auth.error", "Invalid credentials"),
            ("rate.limit", "Too many requests"),
        )
        result = _filter_errlist(errlist)
        assert result == [
            ("auth.error", "Invalid credentials"),
            ("rate.limit", "Too many requests"),
        ]

    def test_mixed_drops_cap_keeps_others(self):
        errlist = (
            (WINDOW_CAP_CODE, f"Window {WINDOW_CAP_MSG_FRAGMENT} - please use shorter range"),
            ("server.error", "Internal server error"),
        )
        result = _filter_errlist(errlist)
        assert len(result) == 1
        assert result[0][0] == "server.error"

    def test_empty_errlist(self):
        assert _filter_errlist(()) == []

    def test_sanitizes_messages(self):
        errlist = (("code", "msg\x00with\x01control\x7fchars"),)
        result = _filter_errlist(errlist)
        assert result == [("code", "msgwithcontrolchars")]

    def test_cap_entry_not_dropped_if_different_code(self):
        errlist = (("other.code", WINDOW_CAP_MSG_FRAGMENT),)
        result = _filter_errlist(errlist)
        assert len(result) == 1

    def test_cap_entry_not_dropped_if_different_msg(self):
        errlist = ((WINDOW_CAP_CODE, "some other message"),)
        result = _filter_errlist(errlist)
        assert len(result) == 1


# ---------------------------------------------------------------------------
# _sanitize_msg
# ---------------------------------------------------------------------------

class TestSanitizeMsg:
    def test_strips_control_chars(self):
        msg = "Hello\x00World\x01\x1f!"
        assert _sanitize_msg(msg) == "HelloWorld!"

    def test_strips_del_char(self):
        msg = "test\x7fvalue"
        assert _sanitize_msg(msg) == "testvalue"

    def test_truncates_to_200_chars(self):
        msg = "a" * 300
        result = _sanitize_msg(msg)
        assert len(result) == 200

    def test_preserves_printable_ascii(self):
        msg = "Normal message with spaces, punctuation: 1234!@#$"
        assert _sanitize_msg(msg) == msg

    def test_preserves_space(self):
        # ord(' ') == 32 — should be kept
        assert _sanitize_msg("hello world") == "hello world"

    def test_empty_string(self):
        assert _sanitize_msg("") == ""

    def test_exactly_200_chars_unchanged(self):
        msg = "x" * 200
        assert _sanitize_msg(msg) == msg


# ---------------------------------------------------------------------------
# _accounts_endpoint
# ---------------------------------------------------------------------------

class TestAccountsEndpoint:
    def test_appends_accounts_to_base_path(self):
        url = "https://user:pass@bridge.simplefin.org/simplefin"
        result = _accounts_endpoint(url)
        assert result == "https://user:pass@bridge.simplefin.org/simplefin/accounts"

    def test_strips_trailing_slash_then_appends(self):
        url = "https://user:pass@bridge.simplefin.org/simplefin/"
        result = _accounts_endpoint(url)
        assert result == "https://user:pass@bridge.simplefin.org/simplefin/accounts"

    def test_preserves_credentials(self):
        url = "https://myuser:mypass@api.example.com/path"
        result = _accounts_endpoint(url)
        assert "myuser:mypass@" in result
        assert result.endswith("/accounts")

    def test_empty_path(self):
        url = "https://user:pass@api.example.com"
        result = _accounts_endpoint(url)
        assert result.endswith("/accounts")

    def test_deep_path(self):
        url = "https://user:pass@api.example.com/a/b/c"
        result = _accounts_endpoint(url)
        assert result == "https://user:pass@api.example.com/a/b/c/accounts"


# ---------------------------------------------------------------------------
# Public-surface failure modes — every escape from fetch_chunk must inherit
# FinstoreError so consumers can catch the umbrella.
# ---------------------------------------------------------------------------


def _client_with_handler(handler):
    """Build a SimpleFinClient backed by httpx.MockTransport(handler)."""
    transport = httpx.MockTransport(handler)
    async_client = httpx.AsyncClient(transport=transport)
    return SimpleFinClient(
        access_url="https://user:pass@bridge.simplefin.org/simplefin",
        httpx_client=async_client,
        max_retries=0,
    )


class TestPublicFailureModes:
    def test_all_upstream_errors_subclass_backend_error(self):
        for cls in (
            UpstreamServerError,
            UpstreamTransportError,
            UpstreamClientError,
            UpstreamResponseError,
        ):
            assert issubclass(cls, BackendError)
            assert issubclass(cls, FinstoreError)

    def test_4xx_wraps_as_upstream_client_error(self):
        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(403, text="forbidden")

        client = _client_with_handler(handler)
        with pytest.raises(UpstreamClientError) as exc_info:
            asyncio.run(client.fetch_chunk(0, 1))
        assert exc_info.value.status_code == 403
        assert isinstance(exc_info.value, BackendError)

    def test_5xx_wraps_as_upstream_server_error(self):
        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(503, text="bad")

        client = _client_with_handler(handler)
        with pytest.raises(UpstreamServerError) as exc_info:
            asyncio.run(client.fetch_chunk(0, 1))
        assert exc_info.value.status_code == 503
        assert isinstance(exc_info.value, BackendError)

    def test_malformed_json_wraps_as_upstream_response_error(self):
        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, content=b"not json")

        client = _client_with_handler(handler)
        with pytest.raises(UpstreamResponseError):
            asyncio.run(client.fetch_chunk(0, 1))

        # Underlying cause is preserved.
        try:
            asyncio.run(client.fetch_chunk(0, 1))
        except UpstreamResponseError as e:
            assert isinstance(e.__cause__, (json.JSONDecodeError, ValueError))

    def test_transport_failure_wraps_as_upstream_transport_error(self):
        def handler(_request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("DNS failure")

        client = _client_with_handler(handler)
        with pytest.raises(UpstreamTransportError) as exc_info:
            asyncio.run(client.fetch_chunk(0, 1))
        assert isinstance(exc_info.value, BackendError)
        assert isinstance(exc_info.value.__cause__, httpx.TransportError)
