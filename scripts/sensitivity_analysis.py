"""Parameter sensitivity analysis for RegimeRouter.

Sweeps individual parameters while holding others at defaults to identify
which parameters are load-bearing (significantly affect Sharpe) vs noise.

Usage:
    .venv/bin/python scripts/sensitivity_analysis.py
    .venv/bin/python scripts/sensitivity_analysis.py --params regime_adx_min bb_mult trail_pct
    .venv/bin/python scripts/sensitivity_analysis.py --steps 5  # fewer steps = faster
"""
import sys
import os
import json
import argparse
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

from openquant.config import config, reset_config
from openquant.modes import backtest_mode
from openquant.store import store

DEFAULT_EXCHANGE = 'Bybit USDT Perpetual'
DEFAULT_SYMBOL = 'BTC-USDT'
DEFAULT_STRATEGY = 'RegimeRouter'
DEFAULT_TIMEFRAME = '15m'
DEFAULT_BALANCE = 10_000.0
DEFAULT_FEE = 0.001
# Use a single representative period for sensitivity analysis
# NOTE: Continuous data from 2024-11-01. With 210 warmup candles, earliest start ~2025-06-01.
DEFAULT_START = '2025-06-01'
DEFAULT_FINISH = '2025-09-30'

# Parameters to analyze — from RegimeRouter.hyperparameters()
# Format: (name, type, min, max, default, steps)
PARAMS_TO_ANALYZE = [
    ('regime_adx_min', float, 15, 40, 30, 6),
    ('bb_mult',        float, 1.5, 3.5, 2.5, 5),
    ('trail_pct',      float, 0.005, 0.08, 0.02, 6),
    ('sl_pct',         float, 0.02, 0.10, 0.05, 5),
    ('rsi_oversold',   float, 20, 45, 30, 6),
    ('rsi_overbought', float, 55, 80, 70, 6),
]

# Default hyperparameters for RegimeRouter
DEFAULT_HP = {
    'bb_window': 15,
    'bb_mult': 2.5,
    'regime_sma': 42,
    'regime_adx_min': 30,
    'regime_confirm': 3,
    'momentum_lookback': 42,
    'risk_pct': 0.05,
    'trail_pct': 0.02,
    'sl_pct': 0.05,
    'tp_pct': 0.10,
    'rsi_period': 14,
    'rsi_oversold': 30,
    'rsi_overbought': 70,
    'vol_mult': 1.2,
}


def generate_sweep_values(param_min: float, param_max: float, default: float,
                           steps: int, param_type: type) -> list:
    """Generate evenly-spaced values across the parameter range, including the default."""
    values = list(np.linspace(param_min, param_max, steps))
    if default not in values:
        values.append(default)
        values.sort()
    if param_type == int:
        values = sorted(set(int(round(v)) for v in values))
    else:
        values = sorted(set(round(v, 4) for v in values))
    return values


def run_backtest_with_hp(hp_overrides: dict, exchange: str, symbol: str,
                          start: str, finish: str, balance: float, fee: float) -> dict:
    """Run a single backtest with specific hyperparameter overrides."""
    reset_config()
    store.reset()

    # Reset DB connection to clear any poisoned transaction state
    try:
        from openquant.services.db import database
        if not database.is_closed():
            database.close()
    except Exception:
        pass

    # Enable 1m candle aggregation (DB only has 1m candles)
    from openquant.config import config as global_config
    global_config['env']['data']['generate_candles_from_1m'] = True
    global_config['env']['data']['warmup_candles_num'] = 210
    global_config['app']['trading_mode'] = 'backtest'
    global_config['app']['debug_mode'] = False

    user_config = {
        'warm_up_candles': 210,
        'logging': {k: False for k in [
            'strategy_execution', 'order_submission', 'order_cancellation',
            'order_execution', 'position_opened', 'position_increased',
            'position_reduced', 'position_closed', 'shorter_period_candles',
            'trading_candles', 'balance_update', 'exchange_ws_reconnection',
        ]},
        'data': {
            'generate_candles_from_1m': True,
            'warmup_candles_num': 60,
            'persistency': False,
        },
        'exchanges': {
            exchange: {
                'name': exchange,
                'fee': fee,
                'type': 'futures',
                'futures_leverage_mode': 'cross',
                'futures_leverage': 1,
                'balance': balance,
            }
        },
    }

    routes = [{'symbol': symbol, 'timeframe': DEFAULT_TIMEFRAME, 'strategy': DEFAULT_STRATEGY,
               'hp': {**DEFAULT_HP, **hp_overrides}}]
    data_routes = [
        {'symbol': symbol, 'timeframe': '1D'},
        {'symbol': symbol, 'timeframe': '4h'},
    ]

    client_id = str(uuid.uuid4())

    # Register process as active in Redis so the status checker doesn't kill it
    from openquant.services.redis import sync_redis
    from openquant.services.env import ENV_VALUES
    port = ENV_VALUES.get('APP_PORT', '9000')
    sync_redis.sadd(f"{port}|active-processes", client_id)

    try:
        backtest_mode.run(
            client_id=client_id,
            debug_mode=False,
            user_config=user_config,
            exchange=exchange,
            routes=routes,
            data_routes=data_routes,
            start_date=start,
            finish_date=finish,
            candles=None,
            chart=False,
            fast_mode=False,
        )
        # Extract results from the store (run() doesn't return them)
        from openquant.services import report
        metrics = report.portfolio_metrics()
        if metrics:
            return {
                'sharpe': metrics.get('sharpe_ratio', 0),
                'net_profit_pct': metrics.get('net_profit_percentage', 0),
                'max_drawdown': metrics.get('max_drawdown', 0),
                'win_rate': metrics.get('win_rate', 0),
                'total_trades': metrics.get('total', 0),
            }
    except Exception as e:
        print(f'    Error: {e}')

    return {'sharpe': 0, 'net_profit_pct': 0, 'max_drawdown': 0, 'win_rate': 0, 'total_trades': 0}


def analyze_param(param_name: str, param_type: type, param_min: float,
                   param_max: float, default: float, steps: int,
                   exchange: str, symbol: str, start: str, finish: str,
                   balance: float, fee: float) -> dict:
    """Sweep a single parameter and measure impact on Sharpe."""
    values = generate_sweep_values(param_min, param_max, default, steps, param_type)
    print(f'\n  {param_name}: sweeping {len(values)} values [{param_min} → {param_max}], default={default}')

    sweep_results = []
    for val in values:
        marker = ' ←default' if val == default else ''
        print(f'    {param_name}={val}{marker}', end='', flush=True)
        metrics = run_backtest_with_hp({param_name: val}, exchange, symbol,
                                        start, finish, balance, fee)
        print(f'  → Sharpe={metrics["sharpe"]:.2f}  PnL={metrics["net_profit_pct"]:+.1f}%')
        sweep_results.append({
            'value': val,
            'is_default': val == default,
            **metrics,
        })

    # Calculate sensitivity: range of Sharpe values
    sharpe_values = [r['sharpe'] for r in sweep_results]
    sharpe_range = max(sharpe_values) - min(sharpe_values) if sharpe_values else 0
    best_value = sweep_results[max(range(len(sweep_results)), key=lambda i: sweep_results[i]['sharpe'])]['value']
    default_sharpe = next((r['sharpe'] for r in sweep_results if r['is_default']), 0)

    return {
        'param': param_name,
        'min': param_min,
        'max': param_max,
        'default': default,
        'best_value': best_value,
        'sharpe_range': round(sharpe_range, 3),
        'default_sharpe': round(default_sharpe, 3),
        'best_sharpe': round(max(sharpe_values), 3) if sharpe_values else 0,
        'sweep': sweep_results,
    }


def generate_sensitivity_report(results: list, config_info: dict) -> str:
    """Generate formatted sensitivity analysis report."""
    lines = []
    lines.append('# RegimeRouter Parameter Sensitivity Analysis')
    lines.append(f'Generated: {datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")}')
    lines.append(f'Period: {config_info["start"]} → {config_info["finish"]}')
    lines.append(f'Exchange: {config_info["exchange"]} | Symbol: {config_info["symbol"]}')
    lines.append('')

    # Sort by sensitivity (Sharpe range) descending
    sorted_results = sorted(results, key=lambda r: r['sharpe_range'], reverse=True)

    lines.append('## Sensitivity Ranking (most to least impactful)')
    lines.append('')
    header = f'{"Rank":<5} {"Parameter":<18} {"Sharpe Range":>13} {"Default Sharpe":>15} {"Best Sharpe":>12} {"Best Value":>11}'
    lines.append(header)
    lines.append('-' * len(header))

    for i, r in enumerate(sorted_results, 1):
        classification = 'LOAD-BEARING' if r['sharpe_range'] > 0.3 else 'MODERATE' if r['sharpe_range'] > 0.1 else 'NOISE'
        lines.append(
            f'{i:<5} {r["param"]:<18} {r["sharpe_range"]:>13.3f} '
            f'{r["default_sharpe"]:>15.3f} {r["best_sharpe"]:>12.3f} '
            f'{r["best_value"]:>11}'
        )
        lines.append(f'      → {classification}')

    lines.append('')
    lines.append('## Interpretation')
    load_bearing = [r for r in sorted_results if r['sharpe_range'] > 0.3]
    moderate = [r for r in sorted_results if 0.1 < r['sharpe_range'] <= 0.3]
    noise = [r for r in sorted_results if r['sharpe_range'] <= 0.1]

    if load_bearing:
        lines.append(f'LOAD-BEARING (Sharpe range > 0.3): {", ".join(r["param"] for r in load_bearing)}')
        lines.append('  These parameters significantly affect strategy performance. Tune carefully.')
    if moderate:
        lines.append(f'MODERATE (0.1 < range ≤ 0.3): {", ".join(r["param"] for r in moderate)}')
        lines.append('  These have meaningful but not dominant impact.')
    if noise:
        lines.append(f'NOISE (range ≤ 0.1): {", ".join(r["param"] for r in noise)}')
        lines.append('  These barely affect performance. Default values are fine.')

    # Optimization suggestions
    lines.append('')
    lines.append('## Suggested Optimizations')
    for r in sorted_results:
        if r['best_value'] != r['default'] and r['sharpe_range'] > 0.1:
            lines.append(f'  {r["param"]}: default={r["default"]} → suggested={r["best_value"]} '
                        f'(Sharpe {r["default_sharpe"]:.2f} → {r["best_sharpe"]:.2f})')

    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser(description='RegimeRouter parameter sensitivity analysis')
    parser.add_argument('--params', nargs='+', default=None,
                        help='Specific parameters to analyze (default: all 6)')
    parser.add_argument('--steps', type=int, default=None,
                        help='Override number of steps per parameter')
    parser.add_argument('--exchange', default=DEFAULT_EXCHANGE)
    parser.add_argument('--symbol', default=DEFAULT_SYMBOL)
    parser.add_argument('--start', default=DEFAULT_START)
    parser.add_argument('--finish', default=DEFAULT_FINISH)
    parser.add_argument('--balance', type=float, default=DEFAULT_BALANCE)
    parser.add_argument('--fee', type=float, default=DEFAULT_FEE)
    args = parser.parse_args()

    params_to_run = PARAMS_TO_ANALYZE
    if args.params:
        params_to_run = [p for p in PARAMS_TO_ANALYZE if p[0] in args.params]
        if not params_to_run:
            print(f'No matching params. Available: {[p[0] for p in PARAMS_TO_ANALYZE]}')
            sys.exit(1)

    if args.steps:
        params_to_run = [(name, ptype, pmin, pmax, default, args.steps)
                          for name, ptype, pmin, pmax, default, _ in params_to_run]

    total_runs = sum(len(generate_sweep_values(pmin, pmax, default, steps, ptype))
                      for _, ptype, pmin, pmax, default, steps in params_to_run)

    config_info = {
        'exchange': args.exchange, 'symbol': args.symbol,
        'start': args.start, 'finish': args.finish,
        'balance': args.balance, 'fee': args.fee,
        'params_analyzed': [p[0] for p in params_to_run],
        'run_date': datetime.now(timezone.utc).isoformat(),
    }

    print(f'RegimeRouter Sensitivity Analysis')
    print(f'Parameters: {[p[0] for p in params_to_run]}')
    print(f'Total backtest runs: ~{total_runs}')
    print(f'Period: {args.start} → {args.finish}')

    start_time = time.time()
    results = []

    for name, ptype, pmin, pmax, default, steps in params_to_run:
        result = analyze_param(name, ptype, pmin, pmax, default, steps,
                                args.exchange, args.symbol, args.start, args.finish,
                                args.balance, args.fee)
        results.append(result)

    elapsed = time.time() - start_time
    print(f'\nTotal time: {elapsed:.0f}s ({elapsed/60:.1f}m)')

    report_text = generate_sensitivity_report(results, config_info)
    print(f'\n{"="*60}')
    print(report_text)

    # Save results
    timestamp = datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')
    results_dir = Path('results') / f'sensitivity-{timestamp}'
    results_dir.mkdir(parents=True, exist_ok=True)

    (results_dir / 'config.json').write_text(json.dumps(config_info, indent=2))
    (results_dir / 'results.json').write_text(json.dumps(results, indent=2, default=str))
    (results_dir / 'report.txt').write_text(report_text)

    print(f'\nResults saved to {results_dir}/')


if __name__ == '__main__':
    main()
