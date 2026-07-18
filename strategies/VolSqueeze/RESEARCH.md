# VolSqueeze Research Notes

Thesis: Catch breakouts after volatility squeezes. ATR percentile detector maps high-vol to breakout, low-vol to BB mean-reversion, normal to trend-follow.

## Round 1 — 2026-04-01 (baseline)
**Hypothesis**: Baseline run with default params. Volatility detector (ATR percentile) should separate squeeze/expansion/normal regimes.
**Result**: PnL -0.89%, Sharpe -2.47, win rate 40.5%, 131 trades, W/L 0.96x
**Regime quality**: Severe flickering. Detector constantly toggles between `low-volatility` and `normal` in 1-day stints (Jun-Jul: dozens of 1-day flips). `high-volatility` only appears briefly in late Aug. The detector is too sensitive — `confirm_bars: 4` on 15m candles means ~1 hour of confirmation, which is meaningless for a regime that should persist for days.
**Diagnosis**: This is a **detector problem**, not a behavior problem. With 1-day regime stints, behaviors can't complete a single trade cycle before getting liquidated by the transition cooldown. The 131 trades at 40.5% win rate and 0.96x W/L suggests the behaviors themselves are roughly neutral — they're just getting chopped up by constant regime switches. The percentile thresholds (85/15) may also be wrong — most time spent in low-vol suggests BTC vol distribution is skewed and 15th percentile is too generous.
**Next**: Raise `confirm_bars` significantly (try 24 = 6 hours on 15m, or even 48 = 12 hours). Consider widening percentile bands (e.g., 90/10) to reduce regime transitions. Alternative: switch to a different volatility measure that's inherently smoother (Bollinger Band width percentile, or ATR ratio instead of raw percentile).
