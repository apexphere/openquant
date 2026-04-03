"""Async HTTP client for the jesse server API."""

import asyncio
import os

import httpx


def _base_url() -> str:
    port = os.environ.get("JESSE_PORT", "9000")
    return f"http://localhost:{port}"


def _password() -> str:
    return os.environ.get("PASSWORD", "openquant123")


async def authenticate(client: httpx.AsyncClient) -> str:
    """Authenticate with the jesse server and return the auth token.

    Raises ConnectionError on connection refused, ValueError on bad credentials.
    """
    try:
        resp = await client.post(
            f"{_base_url()}/auth/login",
            json={"password": _password()},
            timeout=5,
        )
    except httpx.ConnectError:
        raise ConnectionError("Server not running. Start with: jesse run")

    if resp.status_code != 200:
        raise ValueError("Authentication failed: invalid password")

    return resp.json()["auth_token"]


async def api_post(
    client: httpx.AsyncClient, path: str, token: str, data: dict | None = None
) -> dict:
    """Make an authenticated POST request to the jesse API."""
    try:
        resp = await client.post(
            f"{_base_url()}{path}",
            json=data or {},
            headers={"Authorization": token},
            timeout=30,
        )
    except httpx.ConnectError:
        raise ConnectionError("Server not running. Start with: jesse run")

    return resp.json() if resp.text else {}


async def wait_for_session(
    client: httpx.AsyncClient,
    session_id: str,
    token: str,
    poll_interval: float = 3.0,
    timeout: float = 600.0,
) -> dict:
    """Poll until a backtest session finishes or times out.

    Returns the session dict on completion.
    Raises TimeoutError if the session doesn't finish within the timeout.
    Raises RuntimeError if the session stops with an exception.
    """
    elapsed = 0.0
    while elapsed < timeout:
        await asyncio.sleep(poll_interval)
        elapsed += poll_interval

        data = await api_post(
            client, f"/backtest/sessions/{session_id}", token
        )
        session = data.get("session", {})
        status = session.get("status", "unknown")

        if status == "finished":
            return session
        if status in ("stopped", "terminated"):
            exception = session.get("exception", "unknown error")
            raise RuntimeError(f"Backtest failed: {exception}")

    raise TimeoutError(f"Backtest timed out after {int(timeout)}s")


async def wait_for_import(
    client: httpx.AsyncClient,
    session_id: str,
    token: str,
    poll_interval: float = 5.0,
    timeout: float = 600.0,
) -> None:
    """Poll until a candle import finishes (disappears from active workers).

    Raises TimeoutError if the import doesn't finish within the timeout.
    """
    elapsed = 0.0
    while elapsed < timeout:
        await asyncio.sleep(poll_interval)
        elapsed += poll_interval

        data = await api_post(client, "/system/active-workers", token)
        active = data.get("data", [])

        if session_id not in active:
            return

    raise TimeoutError(f"Candle import timed out after {int(timeout)}s")
