# OpenQuant

Regime-aware crypto trading strategy composition framework. Forked from Jesse.

## CRITICAL RULE: Use the Framework, Not Scripts

**DO NOT write disposable Python scripts for backtesting, optimization, or data analysis.**
Use the CLI commands and web dashboard. Results are stored in PostgreSQL and visible in the UI.

## Quick Start

```bash
# 1. Start all services
docker compose up -d postgres redis
.venv/bin/jesse run          # Starts the server on port 9000 (keep running)

# 2. In another terminal — run a backtest
.venv/bin/jesse backtest RegimeRouterV2 --start 2025-06-01 --finish 2025-09-30

# 3. View results
.venv/bin/jesse results              # list recent sessions
.venv/bin/jesse results <session-id> # view specific session

# 4. Run tests
.venv/bin/python -m pytest
```

## CLI Commands

The server must be running (`jesse run`) for these commands to work.

### jesse backtest

```bash
# Basic backtest
jesse backtest RegimeRouter --start 2025-06-01 --finish 2025-09-30

# With options
jesse backtest TrendBreak --start 2025-06-01 --finish 2025-09-30 \
  --timeframe 4h --symbol BTC-USDT --balance 10000

# Machine-readable output
jesse backtest RegimeRouterV2 --start 2025-06-01 --finish 2025-09-30 --json-output
```

### jesse results

```bash
# List recent backtest sessions
jesse results
jesse results --limit 20

# View specific session metrics
jesse results <session-id>

# Machine-readable
jesse results <session-id> --json-output
```

### jesse optimize

```bash
jesse optimize RegimeRouterV2 \
  --training-start 2025-06-01 --training-finish 2025-09-30 \
  --testing-start 2025-10-01 --testing-finish 2025-12-31 \
  --trials 100 --objective sharpe
```

### jesse detector-results

```bash
# List all detector optimization studies
jesse detector-results

# Show top trials for a specific study (use full study name from list)
jesse detector-results supertrend_v5_835791a5-e2c3-469e-8ae4-0a6098d3e8e2

# Show regime breakdown for a specific trial
jesse detector-results supertrend_v5_835791a5-e2c3-469e-8ae4-0a6098d3e8e2 -t 628
```

### jesse detector-preview

Requires the server to be running (`jesse run`).

```bash
# Preview detector regime labels over a date range
jesse detector-preview supertrend_v5 --start 2025-01-25 --finish 2026-03-29

# With custom params
jesse detector-preview supertrend_v5 --start 2025-01-25 --finish 2026-03-29 \
  --params '{"trend_sma_period": 50}'

# Machine-readable
jesse detector-preview supertrend_v5 --start 2025-06-01 --finish 2026-03-25 --json-output
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

### Step 2: Backtest

```bash
jesse backtest MyStrategy --start 2025-06-01 --finish 2025-09-30
```

Results are automatically stored in the database and visible in the web dashboard at `localhost:9000`.

### Step 3: Diagnose and iterate

After checking results, identify the top problem:

**Common failure modes and fixes:**
- **Zero trades** → entry conditions too strict, or warmup insufficient (need 210+ for daily indicators)
- **Low win rate + low W/L ratio** → entries too loose, or exits too tight
- **High win rate + low PnL** → winners too small, widen take profit or tighten stop loss
- **Strategy sits idle** → filters too conservative (ADX threshold, volume multiplier, etc.)
- **Trend-following loses in ranges** → expected behavior. Use regime composition to switch strategies.
- **Mean-reversion loses in trends** → expected behavior. Use regime composition to switch strategies.

Then go back to Step 1 and modify the strategy code.

## Regime-Aware Composition

OpenQuant's core differentiator: every strategy can be regime-aware by default.

### Simple strategy (no regime detection)

Works exactly like a classic Jesse strategy. No changes needed.

### Composite strategy (regime-aware)

```python
from openquant.strategies import Strategy
from openquant.regime import ADXRegimeDetector
from openquant.regime.behaviors import MomentumRotationBehavior, BBMeanReversionBehavior

class MyCompositeStrategy(Strategy):
    def regime_detector(self):
        return ADXRegimeDetector(sma_period=42, adx_min=25, confirm_bars=3)

    def regimes(self):
        return {
            'trending-up': MomentumRotationBehavior,
            'trending-down': None,   # flat — no trading
            'ranging-up': BBMeanReversionBehavior,
            'ranging-down': BBMeanReversionBehavior,
            'cold-start': None,
        }

    def on_regime_change(self, old_regime, new_regime):
        if self.is_long or self.is_short:
            self.liquidate()

    # Fallback methods (used when no behavior is active)
    def should_long(self): return False
    def go_long(self): pass
```

### Built-in components

**Regime detectors** (`openquant.regime`):
- `ADXRegimeDetector` — ADX trend strength + SMA direction

**Behaviors** (`openquant.regime.behaviors`):
- `BBMeanReversionBehavior` — Bollinger Band fade for ranging markets
- `MomentumRotationBehavior` — Top-K momentum ranking for trending markets

### Writing a custom behavior

```python
class MyBehavior:
    def should_long(self, strategy) -> bool:
        return strategy.price > ta.sma(strategy.candles, 50)

    def should_short(self, strategy) -> bool:
        return False

    def go_long(self, strategy) -> None:
        qty = (strategy.balance * 0.05) / strategy.price
        strategy.buy = qty, strategy.price
        strategy.stop_loss = qty, strategy.price * 0.95

    def go_short(self, strategy) -> None:
        pass

    def update_position(self, strategy) -> None:
        pass
```

Behaviors receive the parent strategy as `strategy` — access candles, price, balance, indicators, and submit orders through it.

## Project Structure

```
openquant/                  # Core framework
  ├── regime/               # Regime composition framework
  │   ├── adx_detector.py   # ADX + SMA regime detector
  │   ├── behavior.py       # StrategyBehavior Protocol
  │   └── behaviors/        # Built-in behaviors (BB-MR, Momentum)
  ├── strategies/           # Base Strategy class (regime-aware)
  ├── modes/                # Backtest, optimize, import candles, monte carlo
  ├── services/             # Broker, orders, positions, candles, metrics
  ├── indicators/           # 300+ technical indicators (ta.*)
  ├── controllers/          # FastAPI API routes
  ├── models/               # Peewee ORM (Order, Position, ClosedTrade, Candle)
  ├── cli.py                # CLI commands (backtest, results, optimize)
  └── static/               # Web dashboard (Nuxt)

strategies/                 # User strategies — write new ones here
  ├── RegimeRouter/         # Original monolithic regime strategy
  ├── RegimeRouterV2/       # Composite version using the framework
  └── TrendBreak/           # Donchian breakout with trend filtering

tests/                      # pytest suite
```

## Available Data

PostgreSQL stores 1-minute candle data. Higher timeframes generated on-the-fly.

- **BTC-USDT**: 2024-11-01 to 2026-03-26 (continuous)
- **ETH-USDT**: 2024-06-01 to 2026-03-12

With 210-candle warmup on daily timeframe, earliest usable backtest start: ~2025-06-01.

## Technical Notes

- Use `jh.debug()` for debug output, never `print()`
- All strategies need `should_cancel_entry()` and `filters()` methods (can return False/[])
- If a strategy calls `self.get_candles(exchange, symbol, '1D')`, that timeframe MUST be in data_routes
- The web dashboard at `http://localhost:9000` shows all backtest/optimization results visually
- Behaviors use delegation (method refs operating on parent strategy state), not Strategy instances

## Testing

```bash
.venv/bin/python -m pytest                              # all tests
.venv/bin/python -m pytest tests/test_adx_regime_detector.py  # regime detector
.venv/bin/python -m pytest tests/test_regime_composition.py   # composition framework
```
