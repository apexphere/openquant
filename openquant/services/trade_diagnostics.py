"""Trade diagnostics: decompose backtest results by regime, exit type, and decision trace."""
import json
from openquant.models.BacktestSession import get_backtest_session_by_id


def diagnose_session(session_id: str, top_n: int = 5) -> dict:
    session = get_backtest_session_by_id(session_id)
    if not session:
        raise ValueError(f'Session {session_id} not found')

    trades = session.trades_json or []
    regime_periods = session.regime_periods_json or []
    metrics = session.metrics_json or {}
    strategy_name = session.strategy_name or 'Unknown'

    # Assign regime to each trade
    trades_with_regime = [
        {**t, '_regime': _find_regime(t.get('opened_at', 0), regime_periods)}
        for t in trades
    ]

    regime_breakdown = _regime_breakdown(trades_with_regime, regime_periods)
    exit_analysis = _classify_exits(trades_with_regime)
    top_losers = _top_losers(trades_with_regime, top_n)
    missed = _missed_opportunities(regime_periods, trades_with_regime)

    return {
        'session_id': session_id,
        'strategy_name': strategy_name,
        'trade_count': len(trades),
        'regime_breakdown': regime_breakdown,
        'exit_analysis': exit_analysis,
        'top_losers': top_losers,
        'missed_opportunities': missed,
    }


def _find_regime(opened_at: float, regime_periods: list) -> str:
    for rp in regime_periods:
        start = rp.get('start', rp.get('start_ts', 0))
        end = rp.get('end', rp.get('end_ts', 0))
        if start <= opened_at <= end:
            return rp.get('regime', 'unknown')
    return 'unknown'


def _regime_breakdown(trades: list, regime_periods: list) -> list:
    # Compute duration per regime
    regime_durations = {}
    for rp in regime_periods:
        regime = rp.get('regime', 'unknown')
        start = rp.get('start', rp.get('start_ts', 0))
        end = rp.get('end', rp.get('end_ts', 0))
        days = (end - start) / (1000 * 86400) if end > start else 0
        regime_durations[regime] = regime_durations.get(regime, 0) + days

    # Group trades by regime
    grouped = {}
    for t in trades:
        regime = t['_regime']
        grouped.setdefault(regime, []).append(t)

    # Build breakdown
    all_regimes = set(list(regime_durations.keys()) + list(grouped.keys()))
    result = []
    for regime in sorted(all_regimes):
        regime_trades = grouped.get(regime, [])
        winners = [t for t in regime_trades if t.get('PNL_percentage', 0) > 0]
        total_pnl = sum(t.get('PNL_percentage', 0) for t in regime_trades)
        count = len(regime_trades)
        result.append({
            'regime': regime,
            'duration_days': round(regime_durations.get(regime, 0), 1),
            'trade_count': count,
            'win_rate': round(len(winners) / count * 100, 1) if count else 0,
            'total_pnl_pct': round(total_pnl, 3),
            'avg_pnl_pct': round(total_pnl / count, 3) if count else 0,
        })

    # Mark worst regime
    traded = [r for r in result if r['trade_count'] > 0]
    if traded:
        worst = min(traded, key=lambda r: r['total_pnl_pct'])
        worst['worst'] = True

    return result


def _classify_exits(trades: list) -> dict:
    counts = {}
    for t in trades:
        exit_trace = t.get('exit_trace', {})
        exit_type = exit_trace.get('exit_type', 'unknown')
        # Normalize
        if exit_type in ('stop-loss', 'stop_loss'):
            exit_type = 'stop-loss'
        elif exit_type in ('take-profit', 'take_profit'):
            exit_type = 'take-profit'
        counts[exit_type] = counts.get(exit_type, 0) + 1
    return counts


def _top_losers(trades: list, n: int) -> list:
    losers = sorted(trades, key=lambda t: t.get('PNL_percentage', 0))[:n]
    return [
        {
            'trade': _clean_trade(t),
            'verdict': _generate_verdict(t),
        }
        for t in losers
        if t.get('PNL_percentage', 0) < 0
    ]


def _generate_verdict(trade: dict) -> str:
    parts = []
    entry_trace = trade.get('entry_trace', {})
    exit_trace = trade.get('exit_trace', {})
    indicators = entry_trace.get('indicators', {})

    # Pullback behavior checks
    pct_above = indicators.get('price_vs_fast_ema_pct')
    if pct_above is not None and pct_above > 0.3:
        parts.append(f'price was {pct_above:.2f}% above fast EMA (weak pullback)')

    rsi = indicators.get('rsi')
    if rsi is not None and 40 < rsi < 60:
        parts.append(f'RSI neutral at {rsi:.0f} (no edge)')

    # BB behavior checks
    price_vs_lower = indicators.get('price_vs_bb_lower_pct')
    if price_vs_lower is not None and price_vs_lower > -0.1:
        parts.append(f'price barely at lower BB ({price_vs_lower:.2f}%)')

    price_vs_upper = indicators.get('price_vs_bb_upper_pct')
    if price_vs_upper is not None and price_vs_upper < 0.1:
        parts.append(f'price barely at upper BB ({price_vs_upper:.2f}%)')

    # Exit type analysis
    exit_type = exit_trace.get('exit_type', 'unknown')
    if exit_type == 'stop-loss':
        pnl = trade.get('PNL_percentage', 0)
        holding = trade.get('holding_period', 0)
        if holding < 3600:
            parts.append(f'stopped out quickly ({holding / 60:.0f}m hold)')
        else:
            parts.append(f'stopped out after {holding / 3600:.1f}h')
    elif exit_type == 'regime-change':
        parts.append('liquidated by regime change')

    # Regime mismatch at exit
    entry_regime = entry_trace.get('regime')
    exit_regime = exit_trace.get('regime_at_exit')
    if entry_regime and exit_regime and entry_regime != exit_regime:
        parts.append(f'regime shifted {entry_regime} -> {exit_regime}')

    return '; '.join(parts) if parts else 'no clear signal issues detected'


def _missed_opportunities(regime_periods: list, trades: list) -> list:
    missed = []
    for rp in regime_periods:
        regime = rp.get('regime', 'unknown')
        if regime in ('cold-start', 'bearish'):
            continue

        start = rp.get('start', rp.get('start_ts', 0))
        end = rp.get('end', rp.get('end_ts', 0))
        days = (end - start) / (1000 * 86400)
        if days < 3:
            continue

        # Count trades in this period
        period_trades = [
            t for t in trades
            if start <= t.get('opened_at', 0) <= end
        ]
        if len(period_trades) == 0:
            # Calculate price move from regime period data if available
            start_price = rp.get('start_price')
            end_price = rp.get('end_price')
            pct_change = rp.get('pct_change')
            if pct_change is None and start_price and end_price:
                pct_change = (end_price - start_price) / start_price * 100

            missed.append({
                'start': start,
                'end': end,
                'regime': regime,
                'duration_days': round(days, 1),
                'price_move_pct': round(pct_change, 2) if pct_change else None,
                'reason': f'{regime} period with no entries ({days:.0f} days)',
            })

    return missed


def _clean_trade(trade: dict) -> dict:
    """Return trade dict without internal fields."""
    return {k: v for k, v in trade.items() if not k.startswith('_')}
