# Strategy: RegimeRouterV2COpt

## Thesis
Markets alternate between trending and ranging regimes. A strategy that detects the current regime and routes to the appropriate behavior (trend-following in trends, mean-reversion in ranges) outperforms static strategies that assume one market condition.

## Evidence
- BTC Jun 2025 - Mar 2026: +1.95% on ETH vs B&H -20.69% (alpha +22.64%)
- Regime-aware composition avoids the #1 failure mode of algo trading: applying the wrong strategy to the wrong market condition
- 熊猫交易思维 framework validates the approach: direction + energy + quality assessment before entry

## Premises
1. Markets have identifiable regimes (trending-up, trending-down, ranging) that persist long enough to trade
2. Different regimes require different entry/exit logic (pullbacks in trends, band fades in ranges)
3. EMA crossover detects direction faster than ADX for crypto
4. MACD line (not histogram) confirms trend energy without false signals during pullbacks
5. MACD histogram detects downtrend exhaustion before it's visible in price
6. Daily timeframe pullback entries are more reliable than 15m for BTC

## Entry Rules
**Trending-up (TrendPullbackBehavior):**
- 4h/1D fast EMA below slow EMA confirms uptrend structure
- Previous bar's low touches fast EMA (the pullback)
- Current bar closes back above fast EMA (bounce confirmed)
- RSI not overbought

**Trending-down (TrendPullbackShortBehavior):**
- Mirror of trending-up for shorts
- Previous bar's high touches fast EMA (the rally)
- Current bar closes back below fast EMA (rejection confirmed)
- RSI not oversold

**Ranging (BBMeanReversionBehavior):**
- Price at or below lower BB + RSI oversold → long
- Price at or above upper BB + RSI overbought → short
- Operates on 15m (route timeframe) for quick entries

## Exit Rules
**Trending:** ATR-based stop loss, trailing stop (ATR + percentage), no fixed TP (let trends run)
**Ranging:** TP at middle BB band, SL just past entry band (1.5%)

## Regime Mapping
```yaml
detector: ema_adx (EMA direction + asymmetric MACD confirmation)
trending-up:    trend_pullback        # buy dips to daily EMA
trending-down:  trend_pullback_short  # short rallies to daily EMA
ranging-up:     bb_mean_reversion     # fade BB bands on 15m
ranging-down:   bb_mean_reversion     # fade BB bands on 15m
```

## Known Weaknesses
1. **Downtrend-to-range transition:** MACD line stays negative during ranges below moving averages. Histogram helps but adds ~2 weeks of lag.
2. **Parameter sensitivity:** BB mean-reversion params (window, SL%, RSI thresholds) are highly sensitive. Needs per-coin optimization.
3. **Single-asset only:** Currently tested on BTC and ETH individually. Multi-asset rotation not yet implemented.
4. **No position sizing optimization:** Fixed risk_pct across all regimes. Trending trades should size differently than ranging trades.
5. **240-day trending classification on ETH:** The detector may stay in trending-up too long for assets with sustained trends. Ranging periods within trends may be missed.

## Backtest Results

| Period | Asset | PNL | Sharpe | B&H Return | Alpha | Trades |
|--------|-------|-----|--------|------------|-------|--------|
| Jun 25 - Mar 26 | ETH | +1.95% | 1.92 | -20.69% | +22.64% | 19 |
| Jun 25 - Mar 26 | BTC | -0.91% | -0.32 | ? | ? | 87 |
| Jan 26 - Mar 26 | BTC | +1.04% | 1.31 | ? | ? | 32 |

## Status
BACKTESTED — profitable on ETH, near-breakeven on BTC. BTC params need re-optimization with MACD detector. Full optimization running.
