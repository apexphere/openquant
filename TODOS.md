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

## P3: Multi-Tenant Store Refactor
**What:** Scope Store (positions, orders, balances) per-user for Phase 3 beta users.
**Why:** Current architecture is single-tenant. Phase 3 requires multiple users trading simultaneously with isolated state.
**Effort:** L (human: ~3 weeks / CC: ~2 days)
**Depends on:** Phase 1 + Phase 2 completion
**Added:** 2026-03-26 via /plan-ceo-review
