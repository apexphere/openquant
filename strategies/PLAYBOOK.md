# Trader Agent Playbook

Protocol for developing trading strategies in OpenQuant. Every trader agent must follow these phases in order.

## PHASE 1: DESIGN (before writing any code)

1. **State the thesis** in one sentence — what market behavior are you exploiting?
2. **Match thesis to instrument** — the strategy must use the instrument's full capabilities:
   - **Futures/perpetuals**: can go long AND short. Every regime should have an active behavior. Mapping a regime to `null` (flat) wastes the ability to profit from that regime. A bearish regime is a shorting opportunity, not a reason to sit flat.
   - **Spot**: can only go long. Mapping bearish to `null` is correct — you can't short on spot.
   - If your thesis says "go flat in bearish" on a futures instrument, the thesis is wrong for the instrument. Fix the thesis, not the parameters.
3. **Pick detector + behaviors** from the existing library (compose first, build new only if nothing fits)
4. **Justify regime-behavior mapping** — why this behavior for this regime? Every tradeable regime should have a behavior. Justify any regime mapped to `null` — is it truly untradeable, or are you leaving money on the table?
5. **Identify timeframe and asset** — which symbol, which candle timeframe, which data routes?

### Available Detectors

| Detector | Regimes | Best For |
|----------|---------|----------|
| `adx` | trending-up/down, ranging-up/down, cold-start | Classic trend/range split |
| `trend_strength` | trending-up/down, ranging, cold-start | EMA crossover simplicity |
| `ema_adx` | trending-up/down, ranging-up/down, cold-start | EMA + ADX + MACD composite |
| `breakout_v3` | trending-up/down, ranging-up/down | Asymmetric bull/bear |
| `supertrend_v5` | bullish/bearish/ranging | SuperTrend + ADX + CHOP |
| `supertrend_v6` | bullish/bearish/ranging | Confidence-based with smoothing |
| `supertrend_v7` | bullish/bearish/ranging | Simplified 3-regime |
| `volatility` | high-volatility, low-volatility, normal, cold-start | ATR percentile |

### Available Behaviors

| Behavior | Style | Best For |
|----------|-------|----------|
| `trend_pullback` | Long pullback entries | Uptrend dips |
| `trend_pullback_short` | Short rally entries | Downtrend bounces |
| `trend_follow` | Trailing trend ride | Sustained trends |
| `bb_mean_reversion` | Bollinger Band fade | Range-bound markets |
| `breakout` | Donchian breakout | Volatility expansion |
| `grid` | Grid trading | Tight ranges |

## PHASE 2: BUILD

5. **Create strategy as CompositeStrategy** — `config.yaml` + minimal `__init__.py`
6. **Use the framework** — no disposable Python scripts, no raw file reads
7. **Set param ranges** — every tunable param needs `default`, `min`, `max`
8. **Follow naming convention** — strategy dir name = class name

### Strategy Template

```python
# strategies/MyStrategy/__init__.py
from openquant.regime.composite import CompositeStrategy

class MyStrategy(CompositeStrategy):
    config_file = 'config.yaml'
```

```yaml
# strategies/MyStrategy/config.yaml
detector:
  type: <detector_name>
  params:
    param1: value1

regimes:
  regime-a: behavior_name
  regime-b: another_behavior
  cold-start: null

transitions:
  on_switch: close_all
  cooldown_bars: 4

data_routes: [1D, 4h]

params:
  risk_pct: {default: 0.05, min: 0.01, max: 0.2}
  # ... more params
```

## PHASE 3: VALIDATE

9. **Backtest** the strategy:
   ```bash
   jesse backtest StrategyName --start 2025-06-01 --finish 2025-09-30
   ```

10. **Write research notes** — MANDATORY after every backtest. Use the `jesse annotate` CLI:

    ```bash
    # Human workflow
    jesse annotate <session-id> \
      --hypothesis "what was changed and why" \
      --result-summary "PnL, Sharpe, win rate, trades" \
      --regime-quality "did the detector label regimes correctly?" \
      --diagnosis "what went wrong or right and WHY" \
      --next-steps "specific change to try next" \
      --tags "detector-problem,dead-end"

    # AI agent workflow (JSON input)
    jesse annotate <session-id> --json-input '{
      "hypothesis": "baseline with default params",
      "result_summary": "PnL -0.73%, Sharpe -2.29, 106 trades",
      "diagnosis": "behavior problem - entries too loose",
      "next_steps": "tighten pullback entry filter"
    }' --author agent-name
    ```

    View research history: `jesse research StrategyName`
    Dashboard: `localhost:3000/research/StrategyName`

    Rules for research notes:
    - Numbers alone are not notes. The DB has numbers. Notes capture **reasoning**.
    - Separate detector problems from behavior problems. Clean regimes + poor trades = behavior issue. Flickering regimes = detector issue. This distinction determines what to fix.
    - Record dead ends — "tried X, didn't work because Y" prevents re-running the same experiment.
    - Each round builds on the previous. Reference prior rounds when relevant.

11. **Diagnose failure modes** using the diagnostic table:

    | Symptom | Diagnosis | Fix |
    |---------|-----------|-----|
    | Zero trades | Entry conditions too strict / insufficient warmup | Relax thresholds, check warmup (210+ for daily) |
    | Low win rate + low W/L | Entries too loose | Tighten entry conditions |
    | High win rate + low PnL | Winners too small | Widen TP or tighten SL |
    | Low win rate + high W/L | Entry filter too loose, but exit logic is sound | Tighten entry filter, keep exits |
    | Strategy sits idle | Filters too conservative | Lower ADX threshold, volume filter |
    | Regime flickering | Detector switching too fast (low confirm_bars, tight thresholds) | Raise confirm_bars, widen regime bands |
    | Trend strategy loses in ranges | Expected | Fix detector, not behavior |
    | Mean-reversion loses in trends | Expected | Fix detector, not behavior |

12. **Iterate** — modify config.yaml and re-backtest. Maximum 3 iteration rounds before moving to optimization.

### Deep Research Analysis

When composite metrics (PnL, Sharpe, win rate) are bad but the cause isn't obvious, use `jesse diagnose` to decompose the problem layer by layer. **Never guess which layer is broken. Prove it.**

#### The Diagnostic Tool

```bash
# Run diagnostics on any backtest session
jesse diagnose <session-id>

# More losers
jesse diagnose <session-id> --top-n 10

# Machine-readable for agent consumption
jesse diagnose <session-id> --json-output
```

`jesse diagnose` automatically:
1. **Breaks down trades by regime** — shows trade count, win rate, and PnL per regime. Identifies which regime is the worst performer.
2. **Classifies exits** — stop-loss vs take-profit vs regime-change. Tells you if the problem is entries or exits.
3. **Traces top losers** — for each losing trade, shows the exact indicator values at entry (RSI, EMA, BB bands, etc.) and generates a verdict explaining what went wrong.
4. **Finds missed opportunities** — regime periods with no trades where price moved significantly.

#### Decision Traces

Every trade automatically records WHY it was made:
- **Entry trace**: regime, behavior, indicator values, which conditions were met
- **Exit trace**: exit type (stop-loss/take-profit/regime-change), indicator values at exit

Behaviors implement `trace(strategy) -> dict` to provide indicator snapshots. This is captured at trade open/close and stored in the session's trade data.

#### The Signal Chain

Every trade passes through this chain. `jesse diagnose` helps you identify which layer failed. But the first layer — thesis — is above the signal chain. If the thesis is wrong for the instrument, no amount of tuning below will fix it.

```
Thesis/Instrument Fit → Regime Detection → Behavior Selection → Entry Signal → Exit Signal
```

| Layer | Symptom | Fix |
|-------|---------|-----|
| **Thesis** | Long stretches with zero trades despite large price moves | Strategy doesn't use the instrument's capabilities (e.g., no shorting on futures). Fix the thesis. |
| **Thesis** | Strategy only profits in one market condition | Thesis is one-directional. Add the symmetric case. |
| **Regime** | Losses spread evenly across all regimes | Fix detector, not behaviors |
| **Regime** | Mislabeled regime (e.g., "bullish" during a -10% crash) | Detector lagging on reversals. Tune detector. |
| **Behavior mapping** | One regime has all the losses | Change behavior for that regime |
| **Entry signals** | Traces show weak indicator values (RSI neutral, price far from EMA) | Tighten entry conditions or add structural filters |
| **Exit signals** | Most losses are stop-loss with short hold times | Stop too tight, or entry price bad |
| **Exit signals** | Most losses are regime-change liquidations | Detector switching too early |

#### Research When Stuck

When you hit a structural wall — not a parameter problem, but a fundamental limitation of your approach — research what others do before inventing from scratch. This applies to:
- A behavior that doesn't work for a regime (e.g., BB mean-reversion failing in ranges due to regime-boundary lag)
- An indicator that doesn't fit the price structure
- A thesis that doesn't match the market condition

Steps:
1. **Define the problem precisely** — "BB bands lag after regime change" not "ranging doesn't work"
2. **Search for established approaches** — what do quant traders, algo trading papers, and open-source strategies use for this specific market condition?
3. **Evaluate fit** — does the approach work with our regime-aware architecture? Can it be implemented as a behavior?
4. **Build or adapt** — compose from existing indicators before writing custom ones

Use web search, trading forums, academic papers, and open-source strategy repositories. The crypto algo trading community has likely solved the same problem differently.

#### Timeframe Analysis Tool

When a behavior uses indicators (BB, EMA, RSI, ATR), the timeframe determines what the indicator "sees." Use `jesse analyze-timeframe` to find the right match:

```bash
# Compare BB band widths across timeframes for a ranging period
jesse analyze-timeframe bb --start 2025-08-23 --finish 2025-09-27

# Compare RSI extremes across timeframes
jesse analyze-timeframe rsi --start 2025-08-23 --finish 2025-09-27 --period 14

# Compare EMA deviation on specific timeframes
jesse analyze-timeframe ema --start 2025-06-01 --finish 2025-09-30 --timeframes 1h,4h,1D
```

The tool shows actual indicator values from the database, not estimates. Key principle: **the indicator's lookback window must match the regime's time scale.** A 20-period BB on 15m covers 5 hours — that's intraday noise, not range structure. The same BB on 4h covers 3.3 days — that captures real price swings.

**Regime-boundary warning**: Trailing indicators (BB, EMA) include data from the previous regime in their lookback. After a bullish→ranging switch, the first N bars of BB bands are computed from bullish data and will be centered on the wrong price level. Account for this lag when choosing lookback periods, or add a warmup after regime changes.

#### Workflow: Diagnose → Annotate → Fix

```bash
# 1. Run diagnostics
jesse diagnose <session-id>

# 2. Annotate findings using diagnose output
jesse annotate <session-id> --json-input '{
  "hypothesis": "deep analysis of Round 3 losers",
  "diagnosis": "Layer: entry signal. All 5 worst trades are BB mean-reversion in ranging. Traces show price barely touching BB band (0.1-2.4% from band). Entry filter too loose.",
  "next_steps": "Require price to be at or below lower BB, not just near it. Or switch ranging behavior entirely."
}' --tags "deep-analysis,entry-signal"

# 3. Fix the specific layer, re-backtest, re-diagnose
```

## PHASE 4: OPTIMIZE

13. **Optimize detector independently** (if using a new or untuned detector):
    ```bash
    jesse optimize-detector <detector_name> --start 2025-06-01 --finish 2026-03-25 --trials 300
    ```

14. **Lock detector params** — copy best trial params into config.yaml

15. **Preview detector** to sanity-check regime labels:
    ```bash
    jesse detector-preview <detector_name> --start 2025-06-01 --finish 2026-03-25
    ```

16. **Optimize strategy params** with train/test split:
    ```bash
    jesse optimize StrategyName \
      --training-start 2025-06-01 --training-finish 2025-09-30 \
      --testing-start 2025-10-01 --testing-finish 2025-12-31 \
      --trials 200
    ```

17. **Validate out-of-sample** — testing Sharpe must be positive. If negative, the strategy is overfit.

18. **Write optimization notes** — use `jesse annotate` with the optimization session's best backtest ID. Include train vs test comparison and whether the strategy passed or is overfit.

## PHASE 5: REPORT

19. **Report back** with:
    - Strategy name and thesis (one sentence)
    - Detector and regime-behavior mapping
    - Key metrics: Sharpe, max drawdown, win rate, total trades, net PnL %
    - Training vs testing performance (overfit check)
    - What worked and what didn't
    - Suggested next steps

## Rules

- **Compose first** — use existing detectors and behaviors before building new ones
- **Use the CLI** — `jesse backtest`, `jesse optimize`, `jesse results`, `jesse detector-preview`
- **No scripts** — results go to Postgres and the dashboard, not stdout
- **Immutable iteration** — don't modify config.yaml in place during optimization; create a new strategy variant if making significant changes (e.g., StrategyNameV2)
- **Use the instrument** — on futures/perpetuals, every regime should have an active behavior (long AND short). Mapping bearish/trending-down to `null` wastes the ability to short. Only map to `null` on spot where you can't short, or for cold-start warmup.
- **Max 3 backtest iterations** before optimizing — avoid manual curve-fitting
- **Validate thesis before tuning** — if OOS shows long idle periods with no trades during large price moves, the problem is the thesis, not the parameters. Check instrument-thesis fit first.
