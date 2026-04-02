"""OpenQuant MCP server — 7 tools for strategy development via Claude."""

import json
import re
from pathlib import Path

import httpx
from mcp.server import FastMCP

from openquant_mcp.jesse_client import api_post, authenticate, wait_for_session
from openquant_mcp.trade_mapper import extract_summary, map_trades

mcp = FastMCP("openquant")

EXCHANGE = "Bybit USDT Perpetual"
STRATEGIES_DIR = Path("strategies")
RESULT_DIR = Path.home() / ".trading-harness" / "backtest-results"

_VALID_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _is_valid_strategy_name(name: str) -> bool:
    return bool(_VALID_NAME_RE.match(name)) and "/" not in name and ".." not in name


def _backtest_payload(
    session_id: str,
    strategy: str,
    symbol: str,
    timeframe: str,
    start: str,
    finish: str,
) -> dict:
    data_routes = []
    for tf in ("1D", "4h"):
        if tf != timeframe:
            data_routes.append({"symbol": symbol, "timeframe": tf})

    return {
        "id": session_id,
        "exchange": EXCHANGE,
        "routes": [{"symbol": symbol, "timeframe": timeframe, "strategy": strategy}],
        "data_routes": data_routes,
        "config": {
            "warm_up_candles": 210,
            "logging": {
                "strategy_execution": False,
                "order_submission": True,
                "order_cancellation": True,
                "order_execution": True,
                "position_opened": True,
                "position_increased": True,
                "position_reduced": True,
                "position_closed": True,
                "shorter_period_candles": False,
                "trading_candles": False,
                "balance_update": True,
                "exchange_ws_reconnection": False,
            },
            "exchanges": {
                EXCHANGE: {
                    "name": EXCHANGE,
                    "fee": 0.00055,
                    "type": "futures",
                    "futures_leverage_mode": "cross",
                    "futures_leverage": 1,
                    "balance": 10000,
                }
            },
        },
        "start_date": start,
        "finish_date": finish,
        "debug_mode": False,
        "export_chart": True,
        "export_tradingview": False,
        "export_csv": False,
        "export_json": True,
        "fast_mode": False,
        "benchmark": True,
    }


def _optimization_payload(
    strategy: str,
    symbol: str,
    timeframe: str,
    training_start: str,
    training_finish: str,
    testing_start: str,
    testing_finish: str,
    trials: int,
    objective: str,
) -> dict:
    data_routes = []
    for tf in ("1D", "4h"):
        if tf != timeframe:
            data_routes.append({"symbol": symbol, "timeframe": tf})

    exchange_config = {
        "name": EXCHANGE,
        "fee": 0.001,
        "type": "futures",
        "futures_leverage_mode": "cross",
        "futures_leverage": 1,
        "balance": 10000,
    }

    return {
        "exchange": EXCHANGE,
        "routes": [{"symbol": symbol, "timeframe": timeframe, "strategy": strategy}],
        "data_routes": data_routes,
        "config": {
            "warm_up_candles": 210,
            "objective_function": objective,
            "trials": trials,
            "best_candidates_count": 20,
            "logging": {},
            "exchange": exchange_config,
            "exchanges": {EXCHANGE: exchange_config},
        },
        "training_start_date": training_start,
        "training_finish_date": training_finish,
        "testing_start_date": testing_start,
        "testing_finish_date": testing_finish,
        "optimal_total": 10,
        "fast_mode": False,
        "cpu_cores": 4,
        "state": {},
    }


def _write_result_file(
    session_id: str,
    strategy: str,
    symbol: str,
    timeframe: str,
    start: str,
    finish: str,
    summary: dict,
    trades: list[dict],
    regime_periods: list[dict],
) -> Path:
    RESULT_DIR.mkdir(parents=True, exist_ok=True)
    path = RESULT_DIR / f"{session_id}.json"

    result = {
        "session_id": session_id,
        "strategy": strategy,
        "symbol": symbol,
        "timeframe": timeframe,
        "start": start,
        "finish": finish,
        "summary": summary,
        "trades": trades,
        "regime_periods": regime_periods,
    }

    path.write_text(json.dumps(result, default=str), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@mcp.tool()
async def backtest(
    strategy: str,
    start: str,
    finish: str,
    session_id: str,
    symbol: str = "BTC-USDT",
    timeframe: str = "15m",
) -> str:
    """Run a strategy backtest. Returns summary metrics; trade-level data is written to disk."""
    try:
        async with httpx.AsyncClient() as client:
            token = await authenticate(client)

            payload = _backtest_payload(session_id, strategy, symbol, timeframe, start, finish)
            await api_post(client, "/backtest", token, payload)

            session = await wait_for_session(client, session_id, token)

            metrics = session.get("metrics", {})
            summary = extract_summary(metrics)
            raw_trades = session.get("trades", [])
            trades = map_trades(raw_trades)
            regime_periods = session.get("regime_periods", [])

            result_path = _write_result_file(
                session_id, strategy, symbol, timeframe, start, finish,
                summary, trades, regime_periods,
            )

            return json.dumps({
                "session_id": session_id,
                "total_trades": summary["total_trades"],
                "sharpe": summary["sharpe"],
                "pnl": summary["pnl"],
                "win_rate": summary["win_rate"],
                "max_drawdown": summary["max_drawdown"],
                "result_file": str(result_path),
            })
    except ConnectionError as e:
        return str(e)
    except TimeoutError as e:
        return str(e)
    except RuntimeError as e:
        return str(e)
    except Exception as e:
        return f"Backtest error: {e}"


@mcp.tool()
async def results(session_id: str = "") -> str:
    """List recent backtest sessions, or fetch a specific session's metrics."""
    try:
        async with httpx.AsyncClient() as client:
            token = await authenticate(client)

            if not session_id:
                data = await api_post(client, "/backtest/sessions", token)
                sessions = data.get("sessions", [])[:10]
                result = []
                for s in sessions:
                    state = s.get("state", {})
                    form = state.get("form", {})
                    routes = form.get("routes", [])
                    strat_name = (
                        routes[0].get("strategy", "") if routes else
                        s.get("strategy_name", "")
                    )
                    result.append({
                        "id": s.get("id", ""),
                        "status": s.get("status", ""),
                        "strategy": strat_name,
                        "pnl": s.get("metrics", {}).get("net_profit_percentage", 0.0),
                        "created_at": s.get("created_at", 0),
                    })
                return json.dumps(result)

            data = await api_post(client, f"/backtest/sessions/{session_id}", token)
            session = data.get("session", {})
            if not session:
                return f"Session not found: {session_id}"

            metrics = session.get("metrics", {})
            return json.dumps({
                "session_id": session_id,
                "status": session.get("status", ""),
                "metrics": {
                    "total_trades": metrics.get("total", 0),
                    "sharpe": metrics.get("sharpe_ratio", 0.0),
                    "win_rate": metrics.get("win_rate", 0.0),
                    "max_drawdown": metrics.get("max_drawdown", 0.0),
                    "pnl": metrics.get("net_profit_percentage", 0.0),
                    "annual_return": metrics.get("annual_return", 0.0),
                    "sortino_ratio": metrics.get("sortino_ratio", 0.0),
                    "calmar_ratio": metrics.get("calmar_ratio", 0.0),
                    "profit_factor": metrics.get("profit_factor", 0.0),
                    "expectancy_percentage": metrics.get("expectancy_percentage", 0.0),
                    "longs_count": metrics.get("longs_count", 0),
                    "shorts_count": metrics.get("shorts_count", 0),
                },
                "regime_periods": session.get("regime_periods", []),
                "trade_count": metrics.get("total", 0),
            })
    except ConnectionError as e:
        return str(e)
    except Exception as e:
        return f"Results error: {e}"


@mcp.tool()
async def optimize(
    strategy: str,
    training_start: str,
    training_finish: str,
    testing_start: str,
    testing_finish: str,
    symbol: str = "BTC-USDT",
    timeframe: str = "15m",
    trials: int = 100,
    objective: str = "sharpe",
) -> str:
    """Submit a parameter optimization run. Returns immediately — does NOT block until completion."""
    try:
        async with httpx.AsyncClient() as client:
            token = await authenticate(client)

            payload = _optimization_payload(
                strategy, symbol, timeframe,
                training_start, training_finish,
                testing_start, testing_finish,
                trials, objective,
            )
            await api_post(client, "/optimization", token, payload)

            return json.dumps({
                "session_id": f"opt-{strategy}",
                "status": "started",
                "message": "Optimization submitted. Poll with results tool or check dashboard.",
            })
    except ConnectionError as e:
        return str(e)
    except Exception as e:
        return f"Optimization error: {e}"


@mcp.tool()
async def write_strategy(name: str, code: str) -> str:
    """Write or overwrite a strategy file."""
    if not _is_valid_strategy_name(name):
        return f"Invalid strategy name: {name}"

    try:
        strategy_dir = STRATEGIES_DIR / name
        strategy_dir.mkdir(parents=True, exist_ok=True)
        file_path = strategy_dir / "__init__.py"
        file_path.write_text(code, encoding="utf-8")

        return json.dumps({
            "status": "ok",
            "file_path": str(file_path),
        })
    except Exception as e:
        return f"Failed to write strategy: {e}"


@mcp.tool()
async def read_strategy(name: str) -> str:
    """Read a strategy's source code."""
    if not _is_valid_strategy_name(name):
        return f"Invalid strategy name: {name}"

    file_path = STRATEGIES_DIR / name / "__init__.py"
    if not file_path.exists():
        return f"Strategy not found: {name}"

    try:
        return json.dumps({
            "name": name,
            "code": file_path.read_text(encoding="utf-8"),
        })
    except Exception as e:
        return f"Failed to read strategy: {e}"


@mcp.tool()
async def list_strategies() -> str:
    """List all available strategy names."""
    if not STRATEGIES_DIR.exists():
        return json.dumps({"strategies": []})

    strategies = sorted(
        d.name
        for d in STRATEGIES_DIR.iterdir()
        if d.is_dir() and (d / "__init__.py").exists()
    )
    return json.dumps({"strategies": strategies})


@mcp.tool()
async def detector_preview(
    detector_type: str,
    start: str,
    finish: str,
    symbol: str = "BTC-USDT",
    params: dict | None = None,
) -> str:
    """Preview regime labels for a detector over a date range."""
    try:
        async with httpx.AsyncClient() as client:
            token = await authenticate(client)

            payload = {
                "detector_type": detector_type,
                "params": params or {},
                "exchange": EXCHANGE,
                "symbol": symbol,
                "start_date": start,
                "finish_date": finish,
            }
            data = await api_post(client, "/detector-optimization/preview", token, payload)

            if "error" in data:
                return f"Detector error: {data['error']}"

            return json.dumps({
                "detector_type": detector_type,
                "regime_periods": data.get("regime_periods", []),
            })
    except ConnectionError as e:
        return str(e)
    except Exception as e:
        return f"Detector error: {e}"
