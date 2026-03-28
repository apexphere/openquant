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

## P3: Multi-Tenant Store Refactor
**What:** Scope Store (positions, orders, balances) per-user for Phase 3 beta users.
**Why:** Current architecture is single-tenant. Phase 3 requires multiple users trading simultaneously with isolated state.
**Effort:** L (human: ~3 weeks / CC: ~2 days)
**Depends on:** Phase 1 + Phase 2 completion
**Added:** 2026-03-26 via /plan-ceo-review
