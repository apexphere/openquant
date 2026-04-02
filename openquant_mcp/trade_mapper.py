"""Pure field mapping functions for jesse → harness trade format."""


def map_trade(trade: dict) -> dict:
    """Map a single jesse ClosedTrade dict to harness format.

    All fields are extracted immutably — the source dict is never modified.
    """
    exit_trace = trade.get("exit_trace") or {}
    regime = exit_trace.get("regime_at_exit") or "_unlabeled"

    return {
        "id": trade["id"],
        "entry_timestamp": trade["opened_at"],
        "exit_timestamp": trade["closed_at"],
        "symbol": trade["symbol"],
        "side": trade["type"],
        "entry_price": trade["entry_price"],
        "exit_price": trade["exit_price"],
        "qty": trade["qty"],
        "pnl": trade["PNL"],
        "pnl_pct": trade["PNL_percentage"],
        "fee": trade["fee"],
        "slippage": 0.0,
        "regime": regime,
    }


def map_trades(trades: list[dict]) -> list[dict]:
    """Map a list of jesse trades to harness format."""
    return [map_trade(t) for t in trades]


def extract_summary(metrics: dict) -> dict:
    """Extract summary metrics from a jesse session metrics dict."""
    return {
        "total_trades": metrics.get("total", 0),
        "sharpe": metrics.get("sharpe_ratio", 0.0),
        "win_rate": metrics.get("win_rate", 0.0),
        "max_drawdown": metrics.get("max_drawdown", 0.0),
        "pnl": metrics.get("net_profit_percentage", 0.0),
    }


def build_result_file(
    session_id: str,
    strategy: str,
    symbol: str,
    timeframe: str,
    start: str,
    finish: str,
    metrics: dict,
    trades: list[dict],
    regime_periods: list[dict],
) -> dict:
    """Build the full result file dict from jesse session components.

    Returns a new dict matching the harness schema — never mutates inputs.
    """
    return {
        "session_id": session_id,
        "strategy": strategy,
        "symbol": symbol,
        "timeframe": timeframe,
        "start": start,
        "finish": finish,
        "summary": extract_summary(metrics),
        "trades": map_trades(trades),
        "regime_periods": regime_periods,
    }
