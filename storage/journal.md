# Strategy Journal

Learning log for the thesis → backtest → review cycle.

---

## 2026-03-28 — RegimeRouterV2COpt

### What we tried
Regime-aware strategy composition: EMA+MACD detector routes to TrendPullback (trends) and BBMeanReversion (ranges).

### What we learned
1. **ADX is too laggy for BTC.** Takes 2-3 weeks to detect trend ends. Switched to EMA crossover for direction.
2. **EMA crossover can't detect trend ends either.** Added MACD as energy gate.
3. **MACD histogram causes false signals during pullbacks.** Switched to MACD line (zero-line bounce) for uptrend confirmation.
4. **Downtrend exhaustion needs histogram.** Asymmetric logic: line-only for uptrends, line+histogram for downtrends.
5. **15m candle pullback entries are noise.** Daily timeframe entries are far more reliable for BTC.
6. **BB mean-reversion is parameter-sensitive.** Window 34 and SL 1.5% from optimizer work. Manual guesses (0.5%, 2%) failed.
7. **CandleEnergyFilter doesn't separate winners from losers on 15m.** Daily candle energy shows signal, but it's a quality dimension, not an entry signal.
8. **"Unknown Strategy" in dashboard was a race condition.** Session row created by child process, state update tried before row existed.
9. **Backtests failing silently due to insufficient candle data.** Fixed: session status now updated to "stopped" with exception on crash.

### Key metrics
- ETH: +1.95% vs B&H -20.69% (alpha +22.64%, Sharpe 1.92)
- BTC Jan-Mar 2026: +1.04% (Sharpe 1.31) with correct ranging detection
- BTC full 10-month: -0.91% (needs re-optimization with MACD detector)

### Next steps
- Full optimization with MACD detector (running)
- ETH regime investigation (240 days of trending-up — correct or detector too slow?)
- Multi-asset support (P1 TODO)
