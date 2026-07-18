"""Run backtest with proper UUID, write result to harness path."""
import asyncio
import json
import uuid
from pathlib import Path
import httpx

BASE_URL = "http://localhost:9000"
PASSWORD = "openquant123"
EXCHANGE = "Bybit USDT Perpetual"
RESULT_DIR = Path.home() / ".trading-harness" / "backtest-results"

STRATEGY = "SmaCross2050D"
SYMBOL = "BTC-USDT"
TIMEFRAME = "4h"
START = "2025-06-01"
FINISH = "2025-12-31"
HARNESS_SESSION_ID = "M1_iter2"


async def main():
    async with httpx.AsyncClient() as client:
        # Authenticate
        resp = await client.post(f"{BASE_URL}/auth/login", json={"password": PASSWORD})
        token = resp.json()["auth_token"]
        headers = {"Authorization": token}

        # Submit backtest with proper UUID
        jesse_id = str(uuid.uuid4())
        payload = {
            "id": jesse_id,
            "exchange": EXCHANGE,
            "routes": [{"symbol": SYMBOL, "timeframe": TIMEFRAME, "strategy": STRATEGY}],
            "data_routes": [{"symbol": SYMBOL, "timeframe": "1D"}],
            "config": {
                "warm_up_candles": 210,
                "logging": {
                    "strategy_execution": False, "order_submission": True,
                    "order_cancellation": True, "order_execution": True,
                    "position_opened": True, "position_increased": True,
                    "position_reduced": True, "position_closed": True,
                    "shorter_period_candles": False, "trading_candles": False,
                    "balance_update": True, "exchange_ws_reconnection": False,
                },
                "exchanges": {
                    EXCHANGE: {
                        "name": EXCHANGE, "fee": 0.00055, "type": "futures",
                        "futures_leverage_mode": "cross", "futures_leverage": 1,
                        "balance": 10000,
                    }
                },
            },
            "start_date": START,
            "finish_date": FINISH,
            "debug_mode": False,
            "export_chart": True,
            "export_tradingview": False,
            "export_csv": False,
            "export_json": True,
            "fast_mode": False,
            "benchmark": True,
        }

        resp = await client.post(f"{BASE_URL}/backtest", json=payload, headers=headers, timeout=30)
        print(f"Submitted: {resp.status_code} - {resp.text}")

        # Poll for completion
        for i in range(200):
            await asyncio.sleep(3)
            resp = await client.post(
                f"{BASE_URL}/backtest/sessions/{jesse_id}",
                json={}, headers=headers, timeout=30,
            )
            if resp.status_code != 200:
                print(f"Poll {i}: status={resp.status_code}")
                continue

            data = resp.json()
            session = data.get("session", {})
            status = session.get("status", "unknown")
            print(f"Poll {i}: {status}")

            if status == "finished":
                metrics = session.get("metrics", {})
                trades = session.get("trades", [])
                regime_periods = session.get("regime_periods", [])

                summary = {
                    "total_trades": metrics.get("total", 0),
                    "sharpe": metrics.get("sharpe_ratio", 0.0),
                    "win_rate": metrics.get("win_rate", 0.0),
                    "max_drawdown": metrics.get("max_drawdown", 0.0),
                    "pnl": metrics.get("net_profit_percentage", 0.0),
                    "annual_return": metrics.get("annual_return", 0.0),
                }

                # Write result file for harness
                RESULT_DIR.mkdir(parents=True, exist_ok=True)
                result_path = RESULT_DIR / f"{HARNESS_SESSION_ID}.json"
                result = {
                    "session_id": HARNESS_SESSION_ID,
                    "strategy": STRATEGY,
                    "symbol": SYMBOL,
                    "timeframe": TIMEFRAME,
                    "start": START,
                    "finish": FINISH,
                    "summary": summary,
                    "trades": trades,
                    "regime_periods": regime_periods,
                }
                result_path.write_text(json.dumps(result, default=str))
                print(f"\nResults written to {result_path}")
                print(json.dumps(summary, indent=2))
                return

            if status in ("stopped", "terminated"):
                print(f"FAILED: {session.get('exception', 'unknown')}")
                return

        print("Timed out waiting for backtest")


asyncio.run(main())
