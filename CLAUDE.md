# OpenQuant

AI-native crypto trading strategy development framework. Forked from Jesse.

## CRITICAL RULE: Use the Framework, Not Scripts

**DO NOT write disposable Python scripts for backtesting, optimization, or data analysis.**
OpenQuant is a full framework with a web API. Use it.

The server runs on `http://localhost:9000`. All operations go through the API.
Results are stored in PostgreSQL and visible in the web dashboard.

## Quick Start

```bash
# 1. Start all services
docker compose up -d postgres redis
.venv/bin/jesse run          # Starts the server on port 9000

# 2. Get auth token (use this in all subsequent requests)
curl -s -X POST http://localhost:9000/auth/login \
  -H "Content-Type: application/json" \
  -d '{"password": "openquant123"}' | python3 -m json.tool
# Returns: {"auth_token": "<TOKEN>"}

# 3. Run tests
.venv/bin/python -m pytest
```

## Strategy Development Workflow

### Step 1: Write the strategy

Strategies live in `strategies/{StrategyName}/__init__.py`. They extend `openquant.strategies.Strategy`:

```python
from openquant.strategies import Strategy
import openquant.indicators as ta

class MyStrategy(Strategy):
    def hyperparameters(self):
        return [
            {'name': 'sma_period', 'type': int, 'min': 10, 'max': 100, 'default': 20},
        ]

    def should_long(self) -> bool:
        return self.price > ta.sma(self.candles, period=self.hp['sma_period'])

    def should_short(self) -> bool:
        return False

    def go_long(self):
        qty = (self.balance * 0.05) / self.price
        self.buy = qty, self.price
        self.stop_loss = qty, self.price * 0.95
        self.take_profit = qty, self.price * 1.10

    def go_short(self):
        pass

    def update_position(self):
        pass

    def should_cancel_entry(self):
        return False

    def filters(self):
        return []
```

Access market data:
- `self.candles` — numpy array `[timestamp, open, close, high, low, volume]`
- `self.get_candles(exchange, symbol, timeframe)` — other timeframes (must be in data_routes)
- `self.price` — current close price
- `self.balance` — available balance
- `import openquant.indicators as ta` — 300+ indicators (sma, ema, rsi, bollinger_bands, adx, atr, etc.)

### Step 2: Backtest via the API

**Do NOT write a Python script.** Use curl or the Bash tool to call the API:

```bash
TOKEN="<auth_token from step 1>"

# Run a backtest
curl -s -X POST http://localhost:9000/backtest \
  -H "Content-Type: application/json" \
  -H "Authorization: $TOKEN" \
  -d '{
    "id": "'$(python3 -c 'import uuid; print(uuid.uuid4())')'",
    "exchange": "Bybit USDT Perpetual",
    "routes": [{"symbol": "BTC-USDT", "timeframe": "4h", "strategy": "MyStrategy"}],
    "data_routes": [{"symbol": "BTC-USDT", "timeframe": "1D"}],
    "config": {
      "warm_up_candles": 210,
      "logging": {
        "strategy_execution": false,
        "order_submission": true,
        "order_cancellation": true,
        "order_execution": true,
        "position_opened": true,
        "position_increased": true,
        "position_reduced": true,
        "position_closed": true,
        "shorter_period_candles": false,
        "trading_candles": false,
        "balance_update": true,
        "exchange_ws_reconnection": false
      },
      "exchanges": {
        "Bybit USDT Perpetual": {
          "name": "Bybit USDT Perpetual",
          "fee": 0.001,
          "type": "futures",
          "futures_leverage_mode": "cross",
          "futures_leverage": 1,
          "balance": 10000
        }
      }
    },
    "start_date": "2025-06-01",
    "finish_date": "2025-09-30",
    "debug_mode": false,
    "export_chart": true,
    "export_tradingview": false,
    "export_csv": false,
    "export_json": true,
    "fast_mode": false,
    "benchmark": false
  }'
```

The backtest runs asynchronously. Results are stored in the database and streamed via Redis to the web dashboard.

### Step 3: Check results

```bash
# List all backtest sessions
curl -s -X POST http://localhost:9000/backtest/sessions \
  -H "Content-Type: application/json" \
  -H "Authorization: $TOKEN" \
  -d '{}' | python3 -m json.tool

# Get a specific session's results (includes metrics, trades, equity curve)
curl -s -X POST http://localhost:9000/backtest/sessions/<SESSION_ID> \
  -H "Content-Type: application/json" \
  -H "Authorization: $TOKEN" | python3 -m json.tool

# Get chart data for a session
curl -s -X POST http://localhost:9000/backtest/sessions/<SESSION_ID>/chart-data \
  -H "Content-Type: application/json" \
  -H "Authorization: $TOKEN" | python3 -m json.tool
```

The session response includes: metrics (Sharpe, Sortino, max drawdown, win rate, PnL, etc.), trades list, equity curve, and hyperparameters.

### Step 4: Run optimization

```bash
curl -s -X POST http://localhost:9000/optimization \
  -H "Content-Type: application/json" \
  -H "Authorization: $TOKEN" \
  -d '{
    "exchange": "Bybit USDT Perpetual",
    "routes": [{"symbol": "BTC-USDT", "timeframe": "4h", "strategy": "MyStrategy"}],
    "data_routes": [{"symbol": "BTC-USDT", "timeframe": "1D"}],
    "config": {
      "warm_up_candles": 210,
      "objective_function": "sharpe",
      "trials": 100,
      "best_candidates_count": 10,
      "logging": {},
      "exchanges": {
        "Bybit USDT Perpetual": {
          "name": "Bybit USDT Perpetual",
          "fee": 0.001,
          "type": "futures",
          "futures_leverage_mode": "cross",
          "futures_leverage": 1,
          "balance": 10000
        }
      }
    },
    "training_start_date": "2025-06-01",
    "training_finish_date": "2025-09-30",
    "testing_start_date": "2025-10-01",
    "testing_finish_date": "2025-12-31",
    "optimal_total": 10,
    "fast_mode": false,
    "cpu_cores": 4,
    "state": {}
  }'
```

### Step 5: Diagnose and iterate

After checking results, identify the top problem:

**Common failure modes and fixes:**
- **Zero trades** → entry conditions too strict, or warmup insufficient (need 210+ for daily indicators)
- **Low win rate + low W/L ratio** → entries too loose, or exits too tight
- **High win rate + low PnL** → winners too small, widen take profit or tighten stop loss
- **Strategy sits idle** → filters too conservative (ADX threshold, volume multiplier, etc.)
- **Trend-following loses in ranges** → expected behavior, not a bug. Consider multi-strategy approach.
- **Mean-reversion loses in trends** → expected behavior. Add trend filter to disable entries.

Then go back to Step 1 and modify the strategy code.

## API Reference

All endpoints require `Authorization: <TOKEN>` header (except `/auth/login`).
Server: `http://localhost:9000`

| Method | Endpoint | Purpose |
|--------|----------|---------|
| POST | `/auth/login` | Get auth token (`{"password": "openquant123"}`) |
| POST | `/backtest` | Start a backtest |
| POST | `/backtest/cancel` | Cancel running backtest |
| POST | `/backtest/sessions` | List all backtest sessions |
| POST | `/backtest/sessions/{id}` | Get session results (metrics, trades, equity) |
| POST | `/backtest/sessions/{id}/chart-data` | Get chart data |
| POST | `/backtest/sessions/{id}/remove` | Delete a session |
| POST | `/optimization` | Start optimization (Optuna parameter sweep) |
| POST | `/optimization/cancel` | Cancel running optimization |
| POST | `/optimization/sessions` | List optimization sessions |
| POST | `/optimization/sessions/{id}` | Get optimization results |
| GET | `/strategy/all` | List available strategies |
| POST | `/strategy/make` | Scaffold a new strategy (`{"name": "MyStrategy"}`) |
| POST | `/strategy/get` | Get strategy source code |
| POST | `/candles/import` | Import candles from exchange |
| GET | `/system/active-workers` | Check running processes |

## Project Structure

```
openquant/                  # Core framework
  ├── modes/                # Backtest, optimize, import candles, monte carlo
  ├── services/             # Broker, orders, positions, candles, metrics, notifications
  ├── strategies/           # Base Strategy class
  ├── indicators/           # 300+ technical indicators (ta.*)
  ├── store/                # Centralized state (positions, orders, candles)
  ├── controllers/          # FastAPI API routes
  ├── models/               # Peewee ORM (Order, Position, ClosedTrade, Candle)
  └── static/               # Web dashboard (Nuxt)

strategies/                 # User strategies — write new ones here
  ├── RegimeRouter/         # Regime-switching composite strategy
  └── TrendBreak/           # Donchian breakout with trend filtering

tests/                      # pytest suite (31 files)
```

## Available Data

PostgreSQL stores 1-minute candle data. Higher timeframes generated on-the-fly.

- **BTC-USDT**: 2024-11-01 to 2026-03-26 (continuous)
- **ETH-USDT**: 2024-06-01 to 2026-03-12

With 210-candle warmup on daily timeframe, earliest usable backtest start: ~2025-06-01.

## Technical Notes

- Use `jh.debug()` for debug output, never `print()`
- All strategies need `should_cancel_entry()` and `filters()` methods (can return False/[])
- If a strategy calls `self.get_candles(exchange, symbol, '1D')`, that timeframe MUST be in `data_routes`
- The web dashboard at `http://localhost:9000` shows all backtest/optimization results visually

## Testing

```bash
.venv/bin/python -m pytest                          # all tests
.venv/bin/python -m pytest tests/test_indicators.py  # specific file
```
