"""Integration tests for MCP server tool registration and filesystem tools.

Tests import the server module dynamically and skip gracefully if Dev
hasn't created it yet.
"""

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Dynamic import — skip entire module if server.py doesn't exist yet
# ---------------------------------------------------------------------------

try:
    from openquant_mcp.server import mcp as _mcp
    HAS_SERVER = True
except (ImportError, ModuleNotFoundError):
    HAS_SERVER = False

pytestmark = pytest.mark.skipif(not HAS_SERVER, reason="server module not yet implemented")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_tool_names():
    """Extract registered tool names from the MCP server instance."""
    if not HAS_SERVER:
        return []
    # mcp-python registers tools as a dict on the server instance
    # Try common attribute patterns
    if hasattr(_mcp, "_tools"):
        return list(_mcp._tools.keys())
    if hasattr(_mcp, "tools"):
        tools = _mcp.tools
        if isinstance(tools, dict):
            return list(tools.keys())
        return [t.name for t in tools]
    # FastMCP stores tools in _tool_manager
    if hasattr(_mcp, "_tool_manager"):
        mgr = _mcp._tool_manager
        if hasattr(mgr, "_tools"):
            return list(mgr._tools.keys())
    return []


def _get_tool(name: str):
    """Get a tool definition by name."""
    if hasattr(_mcp, "_tool_manager"):
        mgr = _mcp._tool_manager
        if hasattr(mgr, "_tools"):
            return mgr._tools.get(name)
    if hasattr(_mcp, "_tools"):
        return _mcp._tools.get(name)
    return None


# ---------------------------------------------------------------------------
# Tool registration
# ---------------------------------------------------------------------------

EXPECTED_TOOLS = [
    "backtest",
    "results",
    "optimize",
    "write_strategy",
    "read_strategy",
    "list_strategies",
    "detector_preview",
    "import_candles",
]


class TestToolRegistration:
    def test_all_tools_registered(self):
        """Spec §1: all 8 tools must be registered."""
        names = _get_tool_names()
        for tool_name in EXPECTED_TOOLS:
            assert tool_name in names, f"Tool '{tool_name}' not registered. Found: {names}"

    def test_no_extra_tools(self):
        """Only the 7 spec'd tools should be registered."""
        names = set(_get_tool_names())
        expected = set(EXPECTED_TOOLS)
        extra = names - expected
        assert not extra, f"Unexpected tools registered: {extra}"


# ---------------------------------------------------------------------------
# write_strategy + read_strategy + list_strategies round-trip
# ---------------------------------------------------------------------------

class TestStrategyFilesystem:
    """Test the filesystem tools using tmp_path to isolate from real strategies/."""

    @pytest.fixture
    def strategies_dir(self, tmp_path, monkeypatch):
        """Redirect STRATEGIES_DIR to a temp directory."""
        strat_dir = tmp_path / "strategies"
        strat_dir.mkdir()
        # Try common module paths for the constant
        try:
            import openquant_mcp.server as srv
            if hasattr(srv, "STRATEGIES_DIR"):
                monkeypatch.setattr(srv, "STRATEGIES_DIR", strat_dir)
            elif hasattr(srv, "_strategies_dir"):
                monkeypatch.setattr(srv, "_strategies_dir", strat_dir)
            else:
                monkeypatch.setattr(srv, "STRATEGIES_DIR", strat_dir)
        except Exception:
            pytest.skip("Cannot patch STRATEGIES_DIR")
        return strat_dir

    @pytest.mark.asyncio
    async def test_write_creates_strategy_file(self, strategies_dir):
        """Spec §1.4: write_strategy creates strategies/{name}/__init__.py."""
        from openquant_mcp.server import mcp

        code = "class TestStrat:\n    pass\n"
        # Find and call the write_strategy tool
        tool = _get_tool("write_strategy")
        if tool is None:
            pytest.skip("write_strategy tool not accessible")

        # Write via direct function call if possible
        try:
            from openquant_mcp.server import write_strategy
            result = await write_strategy(name="TestStrat", code=code)
        except ImportError:
            pytest.skip("write_strategy function not importable")

        init_file = strategies_dir / "TestStrat" / "__init__.py"
        assert init_file.exists()
        assert init_file.read_text() == code

    @pytest.mark.asyncio
    async def test_read_strategy_returns_code(self, strategies_dir):
        """Spec §1.5: read_strategy returns name + code."""
        # Pre-create a strategy
        strat_dir = strategies_dir / "MyStrat"
        strat_dir.mkdir()
        code = "class MyStrat:\n    pass\n"
        (strat_dir / "__init__.py").write_text(code)

        try:
            from openquant_mcp.server import read_strategy
            result = await read_strategy(name="MyStrat")
        except ImportError:
            pytest.skip("read_strategy function not importable")

        parsed = json.loads(result)
        assert parsed["name"] == "MyStrat"
        assert parsed["code"] == code

    @pytest.mark.asyncio
    async def test_read_strategy_not_found(self, strategies_dir):
        """Spec §4: missing strategy → 'Strategy not found: {name}'."""
        try:
            from openquant_mcp.server import read_strategy
        except ImportError:
            pytest.skip("read_strategy function not importable")

        result = await read_strategy(name="Nonexistent")
        assert "Strategy not found: Nonexistent" in result

    @pytest.mark.asyncio
    async def test_list_strategies(self, strategies_dir):
        """Spec §1.6: list subdirs that contain __init__.py, sorted."""
        # Create two valid strategies
        for name in ["Bravo", "Alpha"]:
            d = strategies_dir / name
            d.mkdir()
            (d / "__init__.py").write_text(f"class {name}: pass")

        # Create a non-strategy dir (no __init__.py)
        (strategies_dir / "NotAStrategy").mkdir()

        # Create a file that isn't a directory
        (strategies_dir / "PLAYBOOK.md").write_text("notes")

        try:
            from openquant_mcp.server import list_strategies
            result = await list_strategies()
        except ImportError:
            pytest.skip("list_strategies function not importable")

        parsed = json.loads(result)
        assert parsed["strategies"] == ["Alpha", "Bravo"]

    @pytest.mark.asyncio
    async def test_write_strategy_invalid_name_slash(self, strategies_dir):
        """Spec §1.4: name with '/' is rejected."""
        try:
            from openquant_mcp.server import write_strategy
        except ImportError:
            pytest.skip("write_strategy function not importable")

        result = await write_strategy(name="../../etc/passwd", code="x")
        assert "Invalid strategy name" in result

    @pytest.mark.asyncio
    async def test_write_strategy_invalid_name_dotdot(self, strategies_dir):
        """Spec §1.4: name with '..' is rejected."""
        try:
            from openquant_mcp.server import write_strategy
        except ImportError:
            pytest.skip("write_strategy function not importable")

        result = await write_strategy(name="foo..bar", code="x")
        assert "Invalid strategy name" in result

    @pytest.mark.asyncio
    async def test_write_strategy_invalid_name_whitespace(self, strategies_dir):
        """Spec §1.4: name with whitespace is rejected."""
        try:
            from openquant_mcp.server import write_strategy
        except ImportError:
            pytest.skip("write_strategy function not importable")

        result = await write_strategy(name="My Strategy", code="x")
        assert "Invalid strategy name" in result

    @pytest.mark.asyncio
    async def test_write_strategy_overwrites(self, strategies_dir):
        """Spec §1.4: writing same name overwrites the file."""
        try:
            from openquant_mcp.server import write_strategy
        except ImportError:
            pytest.skip("write_strategy function not importable")

        await write_strategy(name="Foo", code="v1")
        await write_strategy(name="Foo", code="v2")

        content = (strategies_dir / "Foo" / "__init__.py").read_text()
        assert content == "v2"


# ---------------------------------------------------------------------------
# backtest — result file output
# ---------------------------------------------------------------------------

class TestBacktestResultFile:
    """Test that backtest writes a correct result file (mock jesse_client)."""

    @pytest.mark.asyncio
    async def test_result_file_written_with_correct_schema(self, tmp_path, monkeypatch):
        """Spec §3: result file schema validation."""
        try:
            import openquant_mcp.server as srv
            from openquant_mcp.server import backtest
        except ImportError:
            pytest.skip("server module not importable")

        # Redirect result file directory
        results_dir = tmp_path / "backtest-results"
        results_dir.mkdir(parents=True)
        if hasattr(srv, "RESULT_DIR"):
            monkeypatch.setattr(srv, "RESULT_DIR", results_dir)
        elif hasattr(srv, "RESULTS_DIR"):
            monkeypatch.setattr(srv, "RESULTS_DIR", results_dir)
        elif hasattr(srv, "_results_dir"):
            monkeypatch.setattr(srv, "_results_dir", results_dir)

        # Mock the jesse client calls
        fake_session = {
            "status": "finished",
            "metrics": {
                "sharpe_ratio": 1.5,
                "win_rate": 0.6,
                "max_drawdown": -5.0,
                "total": 2,
                "net_profit_percentage": 8.0,
            },
            "trades": [
                {
                    "id": "t1",
                    "opened_at": 1719792000000,
                    "closed_at": 1719878400000,
                    "symbol": "BTC-USDT",
                    "type": "long",
                    "entry_price": 65000.0,
                    "exit_price": 66000.0,
                    "qty": 0.01,
                    "PNL": 10.0,
                    "PNL_percentage": 1.5,
                    "fee": 0.5,
                    "exit_trace": {"regime_at_exit": "bullish"},
                },
                {
                    "id": "t2",
                    "opened_at": 1719878400000,
                    "closed_at": 1719964800000,
                    "symbol": "BTC-USDT",
                    "type": "short",
                    "entry_price": 66000.0,
                    "exit_price": 65000.0,
                    "qty": 0.02,
                    "PNL": 20.0,
                    "PNL_percentage": 3.0,
                    "fee": 1.0,
                    "exit_trace": None,
                },
            ],
            "regime_periods": [
                {"start": 1719792000000, "end": 1719964800000, "regime": "bullish"}
            ],
        }

        with patch("openquant_mcp.server.authenticate", new_callable=AsyncMock, return_value="tok"), \
             patch("openquant_mcp.server.api_post", new_callable=AsyncMock), \
             patch("openquant_mcp.server.wait_for_session", new_callable=AsyncMock, return_value=fake_session):

            result = await backtest(
                strategy="RegimeRouterV2",
                start="2025-06-01",
                finish="2025-09-30",
                session_id="test-sess-1",
            )

        # Verify result file was written
        result_file = results_dir / "test-sess-1.json"
        if not result_file.exists():
            # Dev might use a different dir structure; check return value
            parsed_result = json.loads(result)
            if "result_file" in parsed_result:
                result_file = Path(parsed_result["result_file"])

        assert result_file.exists(), f"Result file not found at {result_file}"
        data = json.loads(result_file.read_text())

        # Top-level fields
        assert data["session_id"] == "test-sess-1"
        assert data["strategy"] == "RegimeRouterV2"
        assert "summary" in data
        assert "trades" in data

        # Summary
        assert data["summary"]["total_trades"] == len(data["trades"])

        # Trades use harness field names
        t = data["trades"][0]
        assert "side" in t
        assert "entry_timestamp" in t
        assert "pnl" in t
        assert t["slippage"] == 0.0

        # Second trade has no exit_trace → regime is _unlabeled
        assert data["trades"][1]["regime"] == "_unlabeled"

        # Verify return value is summary-only (JSON string)
        parsed_result = json.loads(result)
        assert parsed_result["session_id"] == "test-sess-1"
        assert "total_trades" in parsed_result or "sharpe" in parsed_result


# ---------------------------------------------------------------------------
# Backtest trades consistency (regression: issue #10)
# ---------------------------------------------------------------------------

class TestBacktestTradesConsistency:
    """Regression tests: result file trades must match summary.total_trades."""

    def _fake_trade(self, trade_id: str) -> dict:
        return {
            "id": trade_id,
            "opened_at": 1719792000000,
            "closed_at": 1719878400000,
            "symbol": "BTC-USDT",
            "type": "long",
            "entry_price": 65000.0,
            "exit_price": 66000.0,
            "qty": 0.01,
            "PNL": 10.0,
            "PNL_percentage": 1.5,
            "fee": 0.5,
            "exit_trace": {"regime_at_exit": "bullish"},
        }

    @pytest.mark.asyncio
    async def test_backtest_result_file_trades_match_summary(self, tmp_path, monkeypatch):
        """Result file must have summary.total_trades == len(trades)."""
        try:
            import openquant_mcp.server as srv
            from openquant_mcp.server import backtest
        except ImportError:
            pytest.skip("server module not importable")

        results_dir = tmp_path / "backtest-results"
        results_dir.mkdir(parents=True)
        monkeypatch.setattr(srv, "RESULT_DIR", results_dir)

        trades = [self._fake_trade(f"t{i}") for i in range(5)]
        fake_session = {
            "status": "finished",
            "metrics": {"total": 5, "sharpe_ratio": 1.0, "win_rate": 0.6,
                        "max_drawdown": -3.0, "net_profit_percentage": 5.0},
            "trades": trades,
            "regime_periods": [],
        }

        with patch("openquant_mcp.server.authenticate", new_callable=AsyncMock, return_value="tok"), \
             patch("openquant_mcp.server.api_post", new_callable=AsyncMock), \
             patch("openquant_mcp.server.wait_for_session", new_callable=AsyncMock, return_value=fake_session):

            result = await backtest(
                strategy="TestStrat", start="2025-06-01", finish="2025-09-30",
                session_id="consistency-5",
            )

        result_file = results_dir / "consistency-5.json"
        assert result_file.exists()
        data = json.loads(result_file.read_text())

        assert data["summary"]["total_trades"] == 5
        assert len(data["trades"]) == 5
        assert data["summary"]["total_trades"] == len(data["trades"])

    @pytest.mark.asyncio
    async def test_backtest_falls_back_to_exported_json(self, tmp_path, monkeypatch):
        """Issue #10: when session has empty trades but metrics.total > 0,
        read from the exported JSON file as a fallback."""
        try:
            import openquant_mcp.server as srv
            from openquant_mcp.server import backtest
        except ImportError:
            pytest.skip("server module not importable")

        results_dir = tmp_path / "backtest-results"
        results_dir.mkdir(parents=True)
        monkeypatch.setattr(srv, "RESULT_DIR", results_dir)

        # Session has metrics but empty trades
        fake_session = {
            "status": "finished",
            "metrics": {"total": 3, "sharpe_ratio": 0.5, "win_rate": 0.4,
                        "max_drawdown": -2.0, "net_profit_percentage": 1.0},
            "trades": [],
            "regime_periods": [],
        }

        # Create the exported JSON file that Jesse would have written
        exported_trades = [self._fake_trade(f"t{i}") for i in range(3)]
        storage_dir = Path("storage/json")
        storage_dir.mkdir(parents=True, exist_ok=True)

        # We need to capture the jesse_id used inside the backtest function.
        # Patch uuid.uuid4 to return a known value.
        import uuid as _uuid
        known_uuid = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
        exported_path = storage_dir / f"{known_uuid}.json"
        exported_path.write_text(json.dumps({
            "trades": exported_trades,
            "considering_timeframes": ["1m"],
        }))

        try:
            with patch("openquant_mcp.server.authenticate", new_callable=AsyncMock, return_value="tok"), \
                 patch("openquant_mcp.server.api_post", new_callable=AsyncMock), \
                 patch("openquant_mcp.server.wait_for_session", new_callable=AsyncMock, return_value=fake_session), \
                 patch("openquant_mcp.server.uuid.uuid4", return_value=_uuid.UUID(known_uuid)):

                result = await backtest(
                    strategy="TestStrat", start="2025-06-01", finish="2025-09-30",
                    session_id="fallback-test",
                )

            parsed = json.loads(result)
            # Should NOT have a warning — trades were recovered from exported JSON
            assert "warning" not in parsed
            assert parsed["trades_source"] == "exported_json"
            assert parsed["total_trades"] == 3

            # Verify result file has trades
            result_file = results_dir / "fallback-test.json"
            data = json.loads(result_file.read_text())
            assert len(data["trades"]) == 3
        finally:
            # Clean up exported file
            exported_path.unlink(missing_ok=True)

    @pytest.mark.asyncio
    async def test_backtest_warns_when_no_fallback_available(self, tmp_path, monkeypatch):
        """When both session and exported JSON have no trades, response must include a warning."""
        try:
            import openquant_mcp.server as srv
            from openquant_mcp.server import backtest
        except ImportError:
            pytest.skip("server module not importable")

        results_dir = tmp_path / "backtest-results"
        results_dir.mkdir(parents=True)
        monkeypatch.setattr(srv, "RESULT_DIR", results_dir)

        fake_session = {
            "status": "finished",
            "metrics": {"total": 3, "sharpe_ratio": 0.5, "win_rate": 0.4,
                        "max_drawdown": -2.0, "net_profit_percentage": 1.0},
            "trades": [],
            "regime_periods": [],
        }

        with patch("openquant_mcp.server.authenticate", new_callable=AsyncMock, return_value="tok"), \
             patch("openquant_mcp.server.api_post", new_callable=AsyncMock), \
             patch("openquant_mcp.server.wait_for_session", new_callable=AsyncMock, return_value=fake_session), \
             patch("openquant_mcp.server._read_exported_trades", return_value=[]):

            result = await backtest(
                strategy="TestStrat", start="2025-06-01", finish="2025-09-30",
                session_id="warn-empty",
            )

        parsed = json.loads(result)
        assert "warning" in parsed
        assert parsed["total_trades"] == 3
