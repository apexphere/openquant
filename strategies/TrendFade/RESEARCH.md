# TrendFade Research Notes

Thesis: Ride confirmed trends, fade ranges. SuperTrend V7 detector (3-regime: bullish/bearish/ranging) maps bullish to trend_pullback, ranging to BB mean-reversion, bearish to flat.

## Round 1 — 2026-04-01 (baseline)
**Hypothesis**: Baseline run with default params. V7 detector should provide clean bullish/bearish/ranging labels.
**Result**: PnL -0.73%, Sharpe -2.29, win rate 33%, 106 trades, W/L 1.32x
**Regime quality**: Clean. No flickering. Regimes are well-structured: 21d bullish, 19d ranging, 41d bullish, 35d ranging, 3d bearish. The V7 detector is doing its job — this is the benefit of the SMA dominance gate and confirm_bars.
**Diagnosis**: This is a **behavior problem**, not a detector problem. The 33% win rate with 1.32x W/L is the classic "entry filter too loose" pattern. The pullback behavior is entering on noise rather than real pullbacks — it fires too often (106 trades in 4 months). The W/L ratio being decent (1.32x) means exits are working fine — winners are bigger than losers. The fix is tightening entry conditions, not touching exits. The 57 short trades (vs 49 long) is also suspicious — the strategy maps bearish to null, so shorts are coming from BB mean-reversion in ranging periods. With only 35d of ranging, 57 shorts seems high — the BB behavior may also be entering too aggressively.
**Next**: Tighten pullback entry filter — raise `pb_rsi_max` threshold to require more oversold conditions before entering. Consider adding a minimum pullback depth (e.g., price must pull back at least 0.5 ATR from recent high). For BB mean-reversion, widen `bb_mult` (2.0 may be too tight) or tighten RSI thresholds to require more extreme readings.
