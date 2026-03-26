"""Regime detection visualization — overlay regime state on price chart.

Runs a backtest for a given period and plots the regime state (trending-up,
trending-down, ranging) overlaid on the BTC price chart. Saved as PNG.

Usage:
    .venv/bin/python scripts/visualize_regime.py
    .venv/bin/python scripts/visualize_regime.py --start 2024-10-01 --finish 2025-03-15
    .venv/bin/python scripts/visualize_regime.py --output results/regime_chart.png
"""
import sys
import os
import argparse
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

try:
    import matplotlib
    matplotlib.use('Agg')  # Non-interactive backend
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates
except ImportError:
    print('matplotlib is required: pip install matplotlib')
    sys.exit(1)

from openquant.config import config, reset_config
from openquant.modes import backtest_mode
from openquant.store import store
from openquant.strategies import Strategy
import openquant.indicators as ta

DEFAULT_EXCHANGE = 'Bybit USDT Perpetual'
DEFAULT_SYMBOL = 'BTC-USDT'
DEFAULT_START = '2025-01-01'
DEFAULT_FINISH = '2026-03-15'

# Regime colors
REGIME_COLORS = {
    'trending-up': '#22c55e',     # green
    'trending-down': '#ef4444',   # red
    'ranging-up': '#3b82f6',      # blue
    'ranging-down': '#a855f7',    # purple
    'cold-start': '#6b7280',      # gray
}

REGIME_LABELS = {
    'trending-up': 'Trending Up',
    'trending-down': 'Trending Down',
    'ranging-up': 'Ranging (above SMA)',
    'ranging-down': 'Ranging (below SMA)',
    'cold-start': 'Cold Start',
}


def classify_regime_from_candles(daily_candles: np.ndarray, sma_period: int = 42,
                                  adx_min: float = 30, confirm_days: int = 3) -> list:
    """Classify regime for each daily candle using the same logic as RegimeRouter.

    Returns list of (timestamp, regime_str) tuples.
    """
    regimes = []
    confirmed_regime = 'cold-start'
    pending_regime = None
    pending_count = 0
    min_bars = sma_period * 2

    for i in range(len(daily_candles)):
        ts = daily_candles[i, 0]

        if i < min_bars:
            regimes.append((ts, 'cold-start'))
            continue

        candles_slice = daily_candles[:i + 1]
        sma_val = ta.sma(candles_slice, period=sma_period)
        adx_val = ta.adx(candles_slice, period=14)
        current_close = candles_slice[-1, 2]

        is_trending = adx_val >= adx_min

        if is_trending and current_close > sma_val:
            raw_regime = 'trending-up'
        elif is_trending and current_close < sma_val:
            raw_regime = 'trending-down'
        elif current_close >= sma_val:
            raw_regime = 'ranging-up'
        else:
            raw_regime = 'ranging-down'

        # Confirmation delay
        if confirm_days > 0:
            if raw_regime != confirmed_regime:
                if raw_regime == pending_regime:
                    pending_count += 1
                else:
                    pending_regime = raw_regime
                    pending_count = 1
                if pending_count >= confirm_days:
                    confirmed_regime = raw_regime
                    pending_regime = None
                    pending_count = 0
            else:
                pending_regime = None
                pending_count = 0
            regimes.append((ts, confirmed_regime))
        else:
            regimes.append((ts, raw_regime))

    return regimes


def load_daily_candles_from_db(exchange: str, symbol: str,
                                start_date: str, finish_date: str) -> np.ndarray:
    """Load 1m candles from the database and aggregate to daily."""
    from openquant.services.candle_service import _get_candles_from_db, _get_generated_candles
    import openquant.helpers as jh

    start_ts = jh.date_to_timestamp(start_date)
    finish_ts = jh.date_to_timestamp(finish_date)

    # Load raw 1m candles
    candles_1m = _get_candles_from_db(exchange, symbol, start_ts, finish_ts)
    if candles_1m is None or len(candles_1m) == 0:
        return np.array([])

    # Aggregate to daily
    daily_candles = _get_generated_candles('1D', candles_1m)
    return daily_candles


def plot_regime_chart(daily_candles: np.ndarray, regimes: list,
                       symbol: str, output_path: str) -> None:
    """Plot price chart with regime overlay and save as PNG."""
    # Convert timestamps to dates
    dates = [datetime.fromtimestamp(c[0] / 1000, tz=timezone.utc) for c in daily_candles]
    closes = daily_candles[:, 2]

    # Match regime to candle timestamps
    regime_map = {ts: regime for ts, regime in regimes}
    candle_regimes = [regime_map.get(c[0], 'cold-start') for c in daily_candles]

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(16, 10), height_ratios=[3, 1],
                                     sharex=True, gridspec_kw={'hspace': 0.05})

    # Top: Price chart with regime-colored background
    ax1.set_title(f'{symbol} — Regime Detection Overlay', fontsize=14, fontweight='bold')
    ax1.plot(dates, closes, color='#1a1a1a', linewidth=1.0, alpha=0.9)

    # Shade background by regime
    prev_regime = candle_regimes[0] if candle_regimes else 'cold-start'
    start_idx = 0
    for i in range(1, len(candle_regimes)):
        if candle_regimes[i] != prev_regime or i == len(candle_regimes) - 1:
            end_idx = i if candle_regimes[i] != prev_regime else i + 1
            if start_idx < len(dates) and end_idx <= len(dates):
                ax1.axvspan(
                    dates[start_idx], dates[min(end_idx, len(dates) - 1)],
                    alpha=0.15, color=REGIME_COLORS.get(prev_regime, '#6b7280'),
                    label=REGIME_LABELS.get(prev_regime, prev_regime) if start_idx == 0 or prev_regime not in [candle_regimes[j] for j in range(start_idx)] else None,
                )
            prev_regime = candle_regimes[i]
            start_idx = i

    ax1.set_ylabel('Price (USDT)', fontsize=11)
    ax1.grid(True, alpha=0.3)
    ax1.tick_params(axis='x', labelbottom=False)

    # Legend — deduplicate
    handles, labels = ax1.get_legend_handles_labels()
    seen = set()
    unique_handles, unique_labels = [], []
    for h, l in zip(handles, labels):
        if l not in seen:
            seen.add(l)
            unique_handles.append(h)
            unique_labels.append(l)
    ax1.legend(unique_handles, unique_labels, loc='upper left', fontsize=9)

    # Bottom: Regime state as colored bars
    regime_to_num = {
        'cold-start': 0,
        'ranging-down': 1,
        'ranging-up': 2,
        'trending-down': 3,
        'trending-up': 4,
    }
    regime_nums = [regime_to_num.get(r, 0) for r in candle_regimes]
    colors = [REGIME_COLORS.get(r, '#6b7280') for r in candle_regimes]

    ax2.bar(dates, [1] * len(dates), color=colors, width=1.0, edgecolor='none')
    ax2.set_ylabel('Regime', fontsize=11)
    ax2.set_yticks([])
    ax2.set_xlabel('Date', fontsize=11)
    ax2.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))
    ax2.xaxis.set_major_locator(mdates.MonthLocator())
    plt.setp(ax2.xaxis.get_majorticklabels(), rotation=45, ha='right')

    # Regime switch count
    switches = sum(1 for i in range(1, len(candle_regimes)) if candle_regimes[i] != candle_regimes[i - 1])
    fig.text(0.99, 0.01, f'Regime switches: {switches}', ha='right', va='bottom',
             fontsize=9, color='#666666')

    plt.tight_layout()
    plt.savefig(output_path, dpi=150, bbox_inches='tight')
    plt.close()
    print(f'Chart saved to {output_path}')


def main():
    parser = argparse.ArgumentParser(description='Visualize RegimeRouter regime detection')
    parser.add_argument('--exchange', default=DEFAULT_EXCHANGE)
    parser.add_argument('--symbol', default=DEFAULT_SYMBOL)
    parser.add_argument('--start', default=DEFAULT_START)
    parser.add_argument('--finish', default=DEFAULT_FINISH)
    parser.add_argument('--sma-period', type=int, default=42)
    parser.add_argument('--adx-min', type=float, default=30)
    parser.add_argument('--confirm-days', type=int, default=3)
    parser.add_argument('--output', default=None,
                        help='Output path (default: results/{timestamp}/regime_chart.png)')
    args = parser.parse_args()

    print(f'Loading daily candles: {args.symbol} on {args.exchange}')
    print(f'Period: {args.start} → {args.finish}')

    daily_candles = load_daily_candles_from_db(args.exchange, args.symbol,
                                                args.start, args.finish)

    if daily_candles is None or len(daily_candles) == 0:
        print('ERROR: No candle data found. Ensure candles are imported and DB is running.')
        sys.exit(1)

    print(f'Loaded {len(daily_candles)} daily candles')

    regimes = classify_regime_from_candles(
        daily_candles,
        sma_period=args.sma_period,
        adx_min=args.adx_min,
        confirm_days=args.confirm_days,
    )

    # Count regime distribution
    regime_counts = {}
    for _, r in regimes:
        regime_counts[r] = regime_counts.get(r, 0) + 1
    print('Regime distribution:')
    for regime, count in sorted(regime_counts.items()):
        pct = count / len(regimes) * 100
        print(f'  {REGIME_LABELS.get(regime, regime)}: {count} days ({pct:.1f}%)')

    # Output path
    if args.output:
        output_path = args.output
    else:
        timestamp = datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')
        output_dir = Path('results') / timestamp
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = str(output_dir / 'regime_chart.png')

    plot_regime_chart(daily_candles, regimes, args.symbol, output_path)


if __name__ == '__main__':
    main()
