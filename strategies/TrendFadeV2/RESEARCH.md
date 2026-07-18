# TrendFadeV2 Research Notes

Thesis: Symmetric trend pullback for crypto futures. Long pullbacks in bullish, short pullbacks in bearish, fade BB extremes in ranging.

Forked from TrendFade V1 after thesis-level finding: V1 mapped bearish→null (spot mindset), leaving 137 days of bear market untouched on a futures instrument.

## Round 1 — 2026-04-01 (baseline)
**Hypothesis**: Fix thesis — map bearish→trend_pullback_short. Keep all structural filters from TrendFade research (EMA spread gate, BB band width gate).
**Result**: Training (Jun-Sep 2025): +0.25%, 8 trades, Sharpe 1.31. OOS (Oct 2025 - Mar 2026): +1.29%, 43 trades, Sharpe 1.71. Alpha +41.14% vs buy-and-hold (-39.86%).
**Regime quality**: Bearish regime: 40 trades, 40% win rate, +28.52% PnL. This is the money V1 was leaving on the table.
**Diagnosis**: Thesis fix validated. The short behavior works in bear markets with the same structural filters. Losers still show RSI neutral-zone pattern (42-48) — same weakness as long side. 98% exits are stop-loss (no TP on pullback behaviors — trailing stops only). But 2.77x W/L means winners are large enough to compensate for 37% win rate.
**Next steps**: Optimize across full date range to find better params. Consider tightening RSI filter for both long and short pullback behaviors.
