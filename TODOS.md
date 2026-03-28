# TODOS

## ~~P2: Create CLAUDE.md~~ DONE
Completed 2026-03-26. CLAUDE.md created with project structure, strategy development workflow, Phase A script documentation, common failure modes, and technical gotchas.

## P2: Thread Safety Audit for Store
**What:** Audit Store dict mutations for thread safety. Add locks where WebSocket callbacks and main thread share state.
**Why:** In live trading, WebSocket position updates can arrive while orders are being processed — race condition risk on shared Store dicts.
**Effort:** M (human: ~1 week / CC: ~1 hour)
**Depends on:** Understanding which Store operations are called from WS threads vs main thread. Check jesse-live plugin source.
**Added:** 2026-03-26 via /plan-ceo-review

## P2: Integration Test for Full Live Trading Loop
**What:** Build an integration test that simulates the full live trading loop: candle arrives → regime detected → signal generated → circuit breaker checked → order submitted → notification sent. Uses mocked exchange API.
**Why:** All current tests are unit/backtest-scoped. Before paper trading (Phase C), need confidence that the components work together end-to-end.
**Effort:** M (human: ~1 week / CC: ~1 hour)
**Depends on:** Phase B safety infrastructure (circuit breaker, NaN guard, margin check, notifications)
**Added:** 2026-03-26 via /plan-eng-review

## P2: Dashboard Quality Score Visualization
**What:** Add quality score timeline chart to the web dashboard (localhost:9000). Shows per-bar quality scores with min_quality threshold line and trade entry/exit markers.
**Why:** Enables visual threshold tuning. Seeing quality scores overlaid on price action makes it obvious whether filters are catching junk setups.
**Effort:** M (human: ~3 days / CC: ~30 min). Requires Nuxt dashboard exploration.
**Priority:** P2
**Depends on:** Quality Filter Layer implementation + quality_score_at_entry on ClosedTrade model.
**Added:** 2026-03-27 via /plan-ceo-review

## P3: Continuous Divergence Scoring (MACDDivergenceFilter v2)
**What:** Upgrade MACDDivergenceFilter from binary (present=3, absent=10) to continuous scoring based on divergence magnitude.
**Why:** Binary tells you IF divergence exists. Continuous tells you HOW MUCH. Enables finer-grained threshold tuning.
**Effort:** S (human: ~4 hours / CC: ~15 min). Peak detection (the hard part) is already built in v1.
**Priority:** P3
**Depends on:** MACDDivergenceFilter v1 + backtesting validation that divergence detection matters.
**Added:** 2026-03-27 via /plan-ceo-review

## P3: Extract ConfirmationMixin from Detectors
**What:** Extract the `_apply_confirmation` state machine (~25 lines) from ADXRegimeDetector, TrendStrengthDetector, and VolatilityRegimeDetector into a shared mixin or utility function.
**Why:** Same code copy-pasted across 3 detectors. If quality filters ever need confirmation, that's a 4th copy.
**Effort:** S (human: ~2 hours / CC: ~10 min)
**Priority:** P3
**Depends on:** Nothing.
**Added:** 2026-03-27 via /plan-ceo-review

## P1: Multi-Asset Support (Top 10 Crypto)
**What:** Import candle data and enable backtesting/optimization for the top 10 crypto pairs: BTC-USDT, ETH-USDT, SOL-USDT, BNB-USDT, XRP-USDT, DOGE-USDT, ADA-USDT, AVAX-USDT, LINK-USDT, DOT-USDT. Enable multi-route strategies that trade across multiple pairs simultaneously.
**Why:** MomentumRotation behavior ranks coins by momentum and trades the strongest. Single-symbol backtesting can't validate this. Multi-asset support unlocks rotation strategies, portfolio-level risk management, and cross-asset regime detection.
**Effort:** M (human: ~1 week / CC: ~2 hours). Data import via `jesse import-candles`, multi-route YAML config, verify backtest engine handles multiple routes.
**Priority:** P1
**Depends on:** Working regime detector + behaviors (done). Bybit API access for historical data.
**Added:** 2026-03-28

## P2: Grid Trading Behavior for Ranging Markets
**What:** Build a GridTradingBehavior that places multiple simultaneous buy/sell limit orders at fixed price intervals across a detected range. Replaces BB mean-reversion as the primary ranging behavior.
**Why:** Grid trading doesn't predict direction — it captures oscillation. More robust than BB which requires correct band-touch prediction. Crypto markets spend ~70% of time consolidating. Research (arxiv: Dynamic Grid Trading, 2025) shows grid outperforms mean-reversion in sideways markets with proper range detection.
**Effort:** L (human: ~2 weeks / CC: ~3 hours). Requires extending the behavior protocol to support multi-order submission (current `go_long` submits one entry). Grid needs: range bounds from detector, N grid levels, simultaneous limit orders, order management on fills.
**Priority:** P2
**Depends on:** Behavior protocol refactor to support multi-order strategies. Regime detector providing range bounds (upper/lower).
**Added:** 2026-03-28

## P2: Breakout Behavior for Trend Starts
**What:** Add BreakoutBehavior to the trending regime as a complement to TrendPullback. Breakout enters on new highs/lows (Donchian channel break), catching the start of trends. Pullback enters mid-trend. Wire both: breakout for first entry, pullback for subsequent entries.
**Why:** Pullback misses trend starts entirely — it waits for a dip that may not come. The Jul 2025 BTC rally started with a breakout above $107k. A breakout behavior would have caught the first move. BreakoutBehavior already exists in the codebase at `openquant/regime/behaviors/breakout.py`.
**Effort:** S (human: ~2 days / CC: ~30 min). Behavior exists, needs testing with regime detector + YAML wiring. May need a mechanism to switch from breakout to pullback within the same trending regime.
**Priority:** P2
**Depends on:** Nothing — BreakoutBehavior is already built. Needs backtesting and YAML integration.
**Added:** 2026-03-28

## P2: Per-Asset Detector Tuning
**What:** Investigate whether detector parameters (EMA periods, MACD settings, separation threshold) should differ per asset. ETH showed 240 days of continuous trending-up which may be correct or may indicate the detector is too slow to detect ETH ranges.
**Why:** BTC and ETH have different volatility profiles and trend characteristics. One-size-fits-all detector params may leave edge on the table. Each asset's config.yaml can already have different detector params.
**Effort:** M (human: ~1 week / CC: ~2 hours). Run backtests per asset, compare regime timelines against actual price action, optimize detector params per asset.
**Priority:** P2
**Depends on:** Multi-asset data (P1 for all 10, but ETH data already available).
**Added:** 2026-03-28

## P3: Multi-Tenant Store Refactor
**What:** Scope Store (positions, orders, balances) per-user for Phase 3 beta users.
**Why:** Current architecture is single-tenant. Phase 3 requires multiple users trading simultaneously with isolated state.
**Effort:** L (human: ~3 weeks / CC: ~2 days)
**Depends on:** Phase 1 + Phase 2 completion
**Added:** 2026-03-26 via /plan-ceo-review
