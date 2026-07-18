"""Tests for openquant_mcp.jesse_client — HTTP client with mocked httpx."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from openquant_mcp.jesse_client import authenticate, api_post, wait_for_session


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_response(status_code=200, json_data=None, text=""):
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.json.return_value = json_data or {}
    resp.text = text or (str(json_data) if json_data else "")
    return resp


# ---------------------------------------------------------------------------
# authenticate
# ---------------------------------------------------------------------------

class TestAuthenticate:
    @pytest.mark.asyncio
    async def test_successful_auth_returns_token(self):
        client = AsyncMock(spec=httpx.AsyncClient)
        client.post.return_value = _mock_response(200, {"auth_token": "tok123"})

        token = await authenticate(client)

        assert token == "tok123"
        client.post.assert_called_once()
        call_args = client.post.call_args
        assert "/auth/login" in call_args.args[0]
        assert call_args.kwargs["json"]["password"] is not None

    @pytest.mark.asyncio
    async def test_auth_connection_refused(self):
        """Spec §4: connection refused → 'Server not running'."""
        client = AsyncMock(spec=httpx.AsyncClient)
        client.post.side_effect = httpx.ConnectError("Connection refused")

        with pytest.raises(ConnectionError, match="Server not running"):
            await authenticate(client)

    @pytest.mark.asyncio
    async def test_auth_bad_password(self):
        """Spec §4: non-200 → 'Authentication failed: invalid password'."""
        client = AsyncMock(spec=httpx.AsyncClient)
        client.post.return_value = _mock_response(401, {})

        with pytest.raises(ValueError, match="Authentication failed"):
            await authenticate(client)

    @pytest.mark.asyncio
    async def test_auth_uses_env_port(self, monkeypatch):
        monkeypatch.setenv("JESSE_PORT", "8888")
        client = AsyncMock(spec=httpx.AsyncClient)
        client.post.return_value = _mock_response(200, {"auth_token": "tok"})

        await authenticate(client)

        url = client.post.call_args.args[0]
        assert "8888" in url

    @pytest.mark.asyncio
    async def test_auth_uses_env_password(self, monkeypatch):
        monkeypatch.setenv("PASSWORD", "secret42")
        client = AsyncMock(spec=httpx.AsyncClient)
        client.post.return_value = _mock_response(200, {"auth_token": "tok"})

        await authenticate(client)

        payload = client.post.call_args.kwargs["json"]
        assert payload["password"] == "secret42"


# ---------------------------------------------------------------------------
# api_post
# ---------------------------------------------------------------------------

class TestApiPost:
    @pytest.mark.asyncio
    async def test_sends_auth_header(self):
        client = AsyncMock(spec=httpx.AsyncClient)
        client.post.return_value = _mock_response(200, {"data": 1}, text='{"data":1}')

        result = await api_post(client, "/backtest", "mytoken", {"x": 1})

        assert result == {"data": 1}
        call_kwargs = client.post.call_args.kwargs
        assert call_kwargs["headers"]["Authorization"] == "mytoken"

    @pytest.mark.asyncio
    async def test_connection_refused(self):
        """Spec §4: connection refused → appropriate error."""
        client = AsyncMock(spec=httpx.AsyncClient)
        client.post.side_effect = httpx.ConnectError("Connection refused")

        with pytest.raises(ConnectionError, match="Server not running"):
            await api_post(client, "/backtest", "tok")

    @pytest.mark.asyncio
    async def test_empty_response_body(self):
        client = AsyncMock(spec=httpx.AsyncClient)
        client.post.return_value = _mock_response(200, text="")

        result = await api_post(client, "/some-path", "tok")
        assert result == {}


# ---------------------------------------------------------------------------
# wait_for_session — polling
# ---------------------------------------------------------------------------

class TestWaitForSession:
    @pytest.mark.asyncio
    async def test_returns_on_finished(self):
        """Spec §7: poll returns on 'finished' status."""
        session_data = {"session": {"status": "finished", "metrics": {}}}
        client = AsyncMock(spec=httpx.AsyncClient)
        client.post.return_value = _mock_response(200, session_data, text=str(session_data))

        with patch("openquant_mcp.jesse_client.asyncio.sleep", new_callable=AsyncMock):
            result = await wait_for_session(client, "sess-1", "tok", poll_interval=0.01)

        assert result["status"] == "finished"

    @pytest.mark.asyncio
    async def test_returns_on_stopped_raises_runtime_error(self):
        """Spec §4: stopped session → 'Backtest failed: {exception}'."""
        session_data = {
            "session": {"status": "stopped", "exception": "OutOfMemory"}
        }
        client = AsyncMock(spec=httpx.AsyncClient)
        client.post.return_value = _mock_response(200, session_data, text=str(session_data))

        with patch("openquant_mcp.jesse_client.asyncio.sleep", new_callable=AsyncMock):
            with pytest.raises(RuntimeError, match="Backtest failed: OutOfMemory"):
                await wait_for_session(client, "sess-1", "tok", poll_interval=0.01)

    @pytest.mark.asyncio
    async def test_returns_on_terminated(self):
        """Spec §7: terminated is also a terminal state."""
        session_data = {
            "session": {"status": "terminated", "exception": "killed"}
        }
        client = AsyncMock(spec=httpx.AsyncClient)
        client.post.return_value = _mock_response(200, session_data, text=str(session_data))

        with patch("openquant_mcp.jesse_client.asyncio.sleep", new_callable=AsyncMock):
            with pytest.raises(RuntimeError, match="Backtest failed"):
                await wait_for_session(client, "s", "tok", poll_interval=0.01)

    @pytest.mark.asyncio
    async def test_timeout(self):
        """Spec §4: poll loop exceeds timeout → 'Backtest timed out after 600s'."""
        session_data = {"session": {"status": "running"}}
        client = AsyncMock(spec=httpx.AsyncClient)
        client.post.return_value = _mock_response(200, session_data, text=str(session_data))

        with patch("openquant_mcp.jesse_client.asyncio.sleep", new_callable=AsyncMock):
            with pytest.raises(TimeoutError, match="timed out"):
                await wait_for_session(
                    client, "sess-1", "tok",
                    poll_interval=0.01, timeout=0.03,
                )

    @pytest.mark.asyncio
    async def test_polls_until_finished(self):
        """Verify it polls multiple times before getting 'finished'."""
        running = {"session": {"status": "running"}}
        finished = {"session": {"status": "finished", "metrics": {}}}

        responses = [
            _mock_response(200, running, text=str(running)),
            _mock_response(200, running, text=str(running)),
            _mock_response(200, finished, text=str(finished)),
        ]
        client = AsyncMock(spec=httpx.AsyncClient)
        client.post.side_effect = responses

        with patch("openquant_mcp.jesse_client.asyncio.sleep", new_callable=AsyncMock):
            result = await wait_for_session(
                client, "sess-1", "tok", poll_interval=0.01, timeout=10,
            )

        assert result["status"] == "finished"
        assert client.post.call_count == 3


# ---------------------------------------------------------------------------
# wait_for_session — trades consistency (regression: issue #10)
# ---------------------------------------------------------------------------

class TestWaitForSessionTradesRetry:
    """Regression tests for the missing-trades bug.

    When a session finishes with metrics.total > 0 but trades=[], the client
    should retry before returning, to guard against transaction timing issues.
    """

    def _make_session(self, status="finished", total=0, trades=None):
        return {
            "session": {
                "status": status,
                "metrics": {"total": total},
                "trades": trades or [],
            }
        }

    @pytest.mark.asyncio
    async def test_retries_when_trades_missing_then_populated(self):
        """First poll returns finished with trades=[] but total=7.
        Retry polls should fetch again and return the session WITH trades."""
        fake_trades = [{"id": f"t{i}"} for i in range(7)]

        # Initial poll: finished, trades missing
        first_response = self._make_session(status="finished", total=7, trades=[])
        # Retry responses: first retry still empty, second has trades
        retry_empty = self._make_session(status="finished", total=7, trades=[])
        retry_full = self._make_session(status="finished", total=7, trades=fake_trades)

        client = AsyncMock(spec=httpx.AsyncClient)
        client.post.side_effect = [
            _mock_response(200, first_response, text=str(first_response)),
            _mock_response(200, retry_empty, text=str(retry_empty)),
            _mock_response(200, retry_full, text=str(retry_full)),
        ]

        with patch("openquant_mcp.jesse_client.asyncio.sleep", new_callable=AsyncMock):
            result = await wait_for_session(
                client, "sess-retry", "tok", poll_interval=0.01, timeout=30,
            )

        assert len(result["trades"]) == 7
        # 1 initial poll + 2 retries
        assert client.post.call_count == 3

    @pytest.mark.asyncio
    async def test_no_retry_when_trades_present(self):
        """When trades are already present on first finished poll, no retry needed."""
        fake_trades = [{"id": "t1"}, {"id": "t2"}]
        session = self._make_session(status="finished", total=2, trades=fake_trades)

        client = AsyncMock(spec=httpx.AsyncClient)
        client.post.return_value = _mock_response(200, session, text=str(session))

        with patch("openquant_mcp.jesse_client.asyncio.sleep", new_callable=AsyncMock):
            result = await wait_for_session(
                client, "sess-ok", "tok", poll_interval=0.01, timeout=30,
            )

        assert len(result["trades"]) == 2
        # Only 1 call — no retries
        assert client.post.call_count == 1

    @pytest.mark.asyncio
    async def test_no_retry_when_zero_trades_expected(self):
        """When total=0 and trades=[], that's a legitimate zero-trade session."""
        session = self._make_session(status="finished", total=0, trades=[])

        client = AsyncMock(spec=httpx.AsyncClient)
        client.post.return_value = _mock_response(200, session, text=str(session))

        with patch("openquant_mcp.jesse_client.asyncio.sleep", new_callable=AsyncMock):
            result = await wait_for_session(
                client, "sess-zero", "tok", poll_interval=0.01, timeout=30,
            )

        assert result["trades"] == []
        assert client.post.call_count == 1

    @pytest.mark.asyncio
    async def test_retries_exhausted_returns_best_data(self):
        """If all retries still have empty trades, return the session anyway."""
        session = self._make_session(status="finished", total=3, trades=[])

        client = AsyncMock(spec=httpx.AsyncClient)
        client.post.return_value = _mock_response(200, session, text=str(session))

        with patch("openquant_mcp.jesse_client.asyncio.sleep", new_callable=AsyncMock):
            result = await wait_for_session(
                client, "sess-exhaust", "tok", poll_interval=0.01, timeout=30,
            )

        # Returns even though trades are empty — retries exhausted
        assert result["trades"] == []
        assert result["metrics"]["total"] == 3
        # 1 initial + 3 retries (the retry loop does 3 attempts)
        assert client.post.call_count == 4
