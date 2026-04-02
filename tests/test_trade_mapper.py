"""Tests for openquant_mcp.trade_mapper — field mapping contract from SPEC.md."""

import pytest

from openquant_mcp.trade_mapper import map_trade, map_trades, extract_summary


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_jesse_trade(**overrides) -> dict:
    """Build a complete jesse ClosedTrade dict with sensible defaults."""
    trade = {
        "id": "aaaa-bbbb-cccc-dddd",
        "opened_at": 1719792000000,
        "closed_at": 1719878400000,
        "symbol": "BTC-USDT",
        "type": "long",
        "entry_price": 65000.0,
        "exit_price": 67000.0,
        "qty": 0.01,
        "PNL": 20.0,
        "PNL_percentage": 3.08,
        "fee": 0.72,
        "exit_trace": {"regime_at_exit": "bullish"},
    }
    trade.update(overrides)
    return trade


def _make_jesse_metrics(**overrides) -> dict:
    metrics = {
        "sharpe_ratio": 1.85,
        "win_rate": 0.62,
        "max_drawdown": -8.5,
        "total": 42,
        "net_profit_percentage": 12.34,
    }
    metrics.update(overrides)
    return metrics


# ---------------------------------------------------------------------------
# map_trade — complete field mapping
# ---------------------------------------------------------------------------

class TestMapTrade:
    def test_all_fields_renamed_correctly(self):
        """Spec §2.1: every jesse field maps to the correct harness field."""
        jesse = _make_jesse_trade()
        result = map_trade(jesse)

        assert result["id"] == "aaaa-bbbb-cccc-dddd"
        assert result["entry_timestamp"] == 1719792000000
        assert result["exit_timestamp"] == 1719878400000
        assert result["symbol"] == "BTC-USDT"
        assert result["side"] == "long"        # jesse "type" → "side"
        assert result["entry_price"] == 65000.0
        assert result["exit_price"] == 67000.0
        assert result["qty"] == 0.01
        assert result["pnl"] == 20.0           # jesse "PNL" → "pnl"
        assert result["pnl_pct"] == 3.08       # jesse "PNL_percentage" → "pnl_pct"
        assert result["fee"] == 0.72
        assert result["slippage"] == 0.0       # always hardcoded
        assert result["regime"] == "bullish"

    def test_short_side(self):
        jesse = _make_jesse_trade(type="short")
        result = map_trade(jesse)
        assert result["side"] == "short"

    def test_missing_exit_trace_defaults_regime_to_unlabeled(self):
        """Spec §2.1: default '_unlabeled' when exit_trace is missing."""
        jesse = _make_jesse_trade()
        del jesse["exit_trace"]
        result = map_trade(jesse)
        assert result["regime"] == "_unlabeled"

    def test_none_exit_trace_defaults_regime_to_unlabeled(self):
        jesse = _make_jesse_trade(exit_trace=None)
        result = map_trade(jesse)
        assert result["regime"] == "_unlabeled"

    def test_exit_trace_without_regime_at_exit(self):
        jesse = _make_jesse_trade(exit_trace={})
        result = map_trade(jesse)
        assert result["regime"] == "_unlabeled"

    def test_exit_trace_with_null_regime_at_exit(self):
        """Spec §3: regime_at_exit is null → '_unlabeled'."""
        jesse = _make_jesse_trade(exit_trace={"regime_at_exit": None})
        result = map_trade(jesse)
        assert result["regime"] == "_unlabeled"

    def test_slippage_always_zero(self):
        """Spec §2.1: slippage is always hardcoded 0.0."""
        result = map_trade(_make_jesse_trade())
        assert result["slippage"] == 0.0
        assert isinstance(result["slippage"], float)

    def test_timestamps_pass_through_as_ms_integers(self):
        """Spec §3: timestamps must be Unix milliseconds (>= 1e12)."""
        opened = 1719792000000
        closed = 1719878400000
        jesse = _make_jesse_trade(opened_at=opened, closed_at=closed)
        result = map_trade(jesse)
        assert result["entry_timestamp"] == opened
        assert result["exit_timestamp"] == closed
        assert isinstance(result["entry_timestamp"], int)
        assert isinstance(result["exit_timestamp"], int)
        assert result["entry_timestamp"] >= 1e12
        assert result["exit_timestamp"] >= 1e12

    def test_source_dict_not_mutated(self):
        """Immutability: map_trade must not modify the input."""
        jesse = _make_jesse_trade()
        original_keys = set(jesse.keys())
        map_trade(jesse)
        assert set(jesse.keys()) == original_keys
        assert jesse["type"] == "long"  # not renamed in-place

    def test_no_extra_fields(self):
        """Result should contain exactly the spec'd fields, nothing extra."""
        result = map_trade(_make_jesse_trade())
        expected_keys = {
            "id", "entry_timestamp", "exit_timestamp", "symbol", "side",
            "entry_price", "exit_price", "qty", "pnl", "pnl_pct",
            "fee", "slippage", "regime",
        }
        assert set(result.keys()) == expected_keys


# ---------------------------------------------------------------------------
# map_trades — batch
# ---------------------------------------------------------------------------

class TestMapTrades:
    def test_empty_list(self):
        assert map_trades([]) == []

    def test_preserves_order(self):
        trades = [
            _make_jesse_trade(id="1", type="long"),
            _make_jesse_trade(id="2", type="short"),
        ]
        result = map_trades(trades)
        assert [t["id"] for t in result] == ["1", "2"]
        assert result[0]["side"] == "long"
        assert result[1]["side"] == "short"


# ---------------------------------------------------------------------------
# extract_summary — metric mapping
# ---------------------------------------------------------------------------

class TestExtractSummary:
    def test_all_metrics_mapped(self):
        """Spec §2.2: jesse metric names → harness names."""
        metrics = _make_jesse_metrics()
        summary = extract_summary(metrics)

        assert summary["sharpe"] == 1.85         # sharpe_ratio → sharpe
        assert summary["win_rate"] == 0.62       # win_rate → win_rate
        assert summary["max_drawdown"] == -8.5   # max_drawdown → max_drawdown
        assert summary["total_trades"] == 42     # total → total_trades
        assert summary["pnl"] == 12.34           # net_profit_percentage → pnl

    def test_missing_metrics_default_to_zero(self):
        """Missing metrics should default gracefully."""
        summary = extract_summary({})
        assert summary["total_trades"] == 0
        assert summary["sharpe"] == 0.0
        assert summary["win_rate"] == 0.0
        assert summary["max_drawdown"] == 0.0
        assert summary["pnl"] == 0.0

    def test_summary_field_count(self):
        summary = extract_summary(_make_jesse_metrics())
        expected_keys = {"total_trades", "sharpe", "win_rate", "max_drawdown", "pnl"}
        assert set(summary.keys()) == expected_keys


# ---------------------------------------------------------------------------
# build_result_file (if available) — full result file assembly
# ---------------------------------------------------------------------------

class TestBuildResultFile:
    """Spec §3: result file schema assembly.

    Tests import build_result_file dynamically so the suite still runs
    even if Dev hasn't created it yet.
    """

    @pytest.fixture
    def build_fn(self):
        try:
            from openquant_mcp.trade_mapper import build_result_file
        except ImportError:
            pytest.skip("build_result_file not yet implemented")
        return build_result_file

    def test_top_level_structure(self, build_fn):
        trades = [_make_jesse_trade()]
        metrics = _make_jesse_metrics()
        result = build_fn(
            session_id="abc-123",
            strategy="RegimeRouterV2",
            symbol="BTC-USDT",
            timeframe="15m",
            start="2025-06-01",
            finish="2025-09-30",
            metrics=metrics,
            trades=trades,
            regime_periods=[],
        )
        assert result["session_id"] == "abc-123"
        assert result["strategy"] == "RegimeRouterV2"
        assert result["symbol"] == "BTC-USDT"
        assert result["timeframe"] == "15m"
        assert result["start"] == "2025-06-01"
        assert result["finish"] == "2025-09-30"
        assert "summary" in result
        assert "trades" in result
        assert "regime_periods" in result

    def test_summary_uses_extract_summary(self, build_fn):
        metrics = _make_jesse_metrics(sharpe_ratio=2.5)
        result = build_fn(
            session_id="x",
            strategy="X",
            symbol="BTC-USDT",
            timeframe="15m",
            start="2025-06-01",
            finish="2025-09-30",
            metrics=metrics,
            trades=[],
            regime_periods=[],
        )
        assert result["summary"]["sharpe"] == 2.5

    def test_total_trades_equals_len_trades(self, build_fn):
        """Spec §3: total_trades MUST equal len(trades)."""
        trades = [_make_jesse_trade(id=str(i)) for i in range(5)]
        metrics = _make_jesse_metrics(total=5)
        result = build_fn(
            session_id="x",
            strategy="X",
            symbol="BTC-USDT",
            timeframe="15m",
            start="2025-06-01",
            finish="2025-09-30",
            metrics=metrics,
            trades=trades,
            regime_periods=[],
        )
        assert result["summary"]["total_trades"] == len(result["trades"])

    def test_empty_trades(self, build_fn):
        metrics = _make_jesse_metrics(total=0)
        result = build_fn(
            session_id="x",
            strategy="X",
            symbol="BTC-USDT",
            timeframe="15m",
            start="2025-06-01",
            finish="2025-09-30",
            metrics=metrics,
            trades=[],
            regime_periods=[],
        )
        assert result["trades"] == []
        assert result["summary"]["total_trades"] == 0

    def test_trades_are_mapped(self, build_fn):
        """Trades in the result file should use harness field names."""
        trades = [_make_jesse_trade()]
        metrics = _make_jesse_metrics()
        result = build_fn(
            session_id="x",
            strategy="X",
            symbol="BTC-USDT",
            timeframe="15m",
            start="2025-06-01",
            finish="2025-09-30",
            metrics=metrics,
            trades=trades,
            regime_periods=[],
        )
        t = result["trades"][0]
        assert "side" in t       # not "type"
        assert "pnl" in t        # not "PNL"
        assert "entry_timestamp" in t  # not "opened_at"
