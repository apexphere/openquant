# OpenQuant

An AI-native crypto trading strategy development framework. Forked from Jesse.

## Quick Reference

```bash
# Run tests
.venv/bin/python -m pytest

# Start services (required for backtesting with real data)
docker compose up -d postgres redis

# Run multi-condition backtest
.venv/bin/python scripts/run_backtests.py

# Visualize regime detection
.venv/bin/python scripts/visualize_regime.py

# Parameter sensitivity analysis
.venv/bin/python scripts/sensitivity_analysis.py
```

## Project Structure

```
openquant/                  # Core framework (500+ files)
  ├── modes/                # Execution engines: backtest, optimize, import candles
  ├── services/             # Business logic: broker, orders, positions, candles, metrics
  ├── strategies/           # Built-in strategy base classes
  ├── indicators/           # 300+ technical indicators (ta.sma, ta.rsi, ta.bollinger_bands, etc.)
  ├── store/                # Centralized state management (positions, orders, candles)
  ├── controllers/          # FastAPI API routes
  ├── models/               # Peewee ORM models (Order, Position, ClosedTrade, Candle)
  └── static/               # Web dashboard UI (Nuxt)

strategies/                 # User strategies (this is where you write new strategies)
  └── RegimeRouter/         # Example: regime-switching strategy

scripts/                    # Development tooling
  ├── run_backtests.py      # Multi-condition backtest runner
  ├── visualize_regime.py   # Regime detection overlay chart
  ├── sensitivity_analysis.py # Parameter sweep analysis
  └── import_ccxt.py        # Import candle data from Bybit

results/                    # Git-tracked backtest outputs (configs + reports)
tests/                      # pytest test suite (31 files)
```

## Strategy Development Workflow

When developing or improving a trading strategy, follow this loop:

### 1. Write or modify the strategy

Strategies live in `strategies/{StrategyName}/__init__.py`. They extend `openquant.strategies.Strategy` and implement:

- `hyperparameters()` — tunable parameters with min/max/default
- `should_long()` / `should_short()` — entry conditions (return bool)
- `go_long()` / `go_short()` — set entry price, stop loss, take profit
- `update_position()` — manage open positions (trailing stops, regime exits)
- `on_close_position()` — post-exit logic

Access market data via:
- `self.candles` — numpy array of current timeframe candles `[timestamp, open, close, high, low, volume]`
- `self.get_candles(exchange, symbol, timeframe)` — other timeframes
- `self.price` — current close price
- `self.balance` — available balance
- `import openquant.indicators as ta` — 300+ indicators

### 2. Run backtests across multiple conditions

```bash
.venv/bin/python scripts/run_backtests.py
```

This runs the strategy across 3 time periods and produces a comparison report with:
- PnL %, Sharpe ratio, Sortino, max drawdown, win rate per condition
- Phase gate check (Sharpe >= 0.7 across all conditions)
- Per-condition detail: trades, streaks, expectancy, fees

Results saved to `results/{timestamp}/`. Inspect `report.txt` for the formatted report and `results.json` for machine-readable data.

### 3. Visualize regime detection

```bash
.venv/bin/python scripts/visualize_regime.py
```

Produces a PNG chart overlaying regime state (trending-up, trending-down, ranging) on the BTC price chart. Use this to verify the regime detector fires at the right times.

Output: `results/{timestamp}/regime_chart.png`

Key things to check:
- What % of time is each regime active?
- Do regime switches align with actual market transitions?
- Is the strategy spending too much time in cold-start or inactive regimes?

### 4. Analyze parameter sensitivity

```bash
.venv/bin/python scripts/sensitivity_analysis.py --steps 3  # fast
.venv/bin/python scripts/sensitivity_analysis.py             # thorough
```

Sweeps key parameters individually and classifies each as:
- **LOAD-BEARING** (Sharpe range > 0.3) — tune these carefully
- **MODERATE** (0.1 < range <= 0.3) — meaningful but not dominant
- **NOISE** (range <= 0.1) — default values are fine

### 5. Diagnose and iterate

After reviewing backtest results, identify the top problem:

**Common failure modes and fixes:**
- **Regime underutilization** (one regime active <10% of time) → lower the ADX threshold or change the regime classification logic
- **Low win rate + low W/L ratio** → entry conditions are too loose, or exits are too tight
- **High win rate + low overall PnL** → winners are too small relative to losers, widen take profit or tighten stop loss
- **All parameters show NOISE in sensitivity** → the problem is structural (regime logic, entry/exit architecture), not parametric
- **Strategy sits idle most of the time** → entry conditions are too strict, or the regime detector is too conservative

Then go back to step 1 and modify the strategy.

## Technical Notes

### Database

PostgreSQL stores 1-minute candle data. Higher timeframes (15m, 4h, 1D) are generated on-the-fly from 1m candles during backtesting.

Available data: BTC-USDT 1m from 2024-11-01 to 2026-03-26 (continuous, no gaps). With 210-candle warmup on daily timeframe, earliest usable backtest start is ~2025-06-01.

### Running backtests programmatically

The scripts use `backtest_mode.run()` which stores results in the global `store` object. After run completes, extract metrics via:

```python
from openquant.services import report
metrics = report.portfolio_metrics()  # dict with sharpe, pnl, drawdown, etc.
trades = report.trades()              # list of closed trade dicts
```

Important: `run()` returns None. Results live in the store.

### Key gotchas

- **Redis process registration**: Scripts must register `client_id` in Redis before calling `backtest_mode.run()`, or the status checker kills the process immediately
- **Warmup candles**: RegimeRouter needs SMA(42)*2 = 84 daily candles minimum. Use `warmup_candles_num >= 210` for safety
- **1m candle generation**: Set `config['env']['data']['generate_candles_from_1m'] = True` before backtesting (DB only has 1m candles)
- **Strategy loading**: When `PYTEST_CURRENT_TEST` is set, strategies load from `openquant/strategies/` instead of `strategies/`. Don't set this env var in scripts.

### Debugging

- Use `jh.debug()` for debug output, never `print()`
- Strategy decisions are NOT logged by default — add logging to `_get_regime()`, `should_long()`, etc. when debugging
- The regime visualization script is the fastest way to see what the regime detector is doing

## Testing

```bash
.venv/bin/python -m pytest           # all tests
.venv/bin/python -m pytest tests/test_indicators.py  # specific file
```

Test suite covers: indicators (300+), order lifecycle, position management, backtest execution, strategy API. Weak areas: no live trading tests, no integration tests for the full loop.
