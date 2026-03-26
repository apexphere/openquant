"""Multi-condition backtest runner for RegimeRouter.

Runs RegimeRouter across multiple market conditions and generates a
formatted comparison report. Results are saved to results/{timestamp}/.

Usage:
    # Requires Docker services (postgres + redis) running:
    #   docker compose up -d postgres redis
    .venv/bin/python scripts/run_backtests.py

    # Custom conditions:
    .venv/bin/python scripts/run_backtests.py --conditions trending ranging

    # Custom exchange/symbol:
    .venv/bin/python scripts/run_backtests.py --exchange "Bybit USDT Perpetual" --symbol BTC-USDT
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

from openquant.config import config, reset_config
from openquant.modes import backtest_mode
from openquant.store import store

# ── Market Condition Definitions ────────────────────────────────────
# Each condition defines a date range that represents a distinct market regime.
# Adjust these based on available candle data in your database.
# NOTE: Continuous 1m candle data runs from 2024-11-01 to 2026-03-26.
# RegimeRouter needs SMA(42)*2=84 daily candles warmup. With 210 warmup candles
# on daily timeframe, earliest usable start date is ~2025-06-01.
MARKET_CONDITIONS = {
    'period_1': {
        'label': 'Period 1 (Jun-Sep 2025)',
        'start': '2025-06-01',
        'finish': '2025-09-30',
        'description': 'Mid-year period — 4 months of trading data',
    },
    'period_2': {
        'label': 'Period 2 (Oct-Dec 2025)',
        'start': '2025-10-01',
        'finish': '2025-12-31',
        'description': 'Q4 2025 — 3 months of trading data',
    },
    'period_3': {
        'label': 'Period 3 (Jan-Mar 2026)',
        'start': '2026-01-01',
        'finish': '2026-03-15',
        'description': 'Most recent period — 2.5 months of trading data',
    },
}

DEFAULT_EXCHANGE = 'Bybit USDT Perpetual'
DEFAULT_SYMBOL = 'BTC-USDT'
DEFAULT_STRATEGY = 'RegimeRouter'
DEFAULT_TIMEFRAME = '15m'
DEFAULT_BALANCE = 10_000.0
DEFAULT_FEE = 0.001  # 0.1% Bybit taker fee


def setup_config(exchange: str, balance: float, fee: float) -> dict:
    """Build the user_config dict for a backtest run."""
    return {
        'warm_up_candles': 210,
        'logging': {
            'strategy_execution': False,
            'order_submission': False,
            'order_cancellation': False,
            'order_execution': False,
            'position_opened': False,
            'position_increased': False,
            'position_reduced': False,
            'position_closed': False,
            'shorter_period_candles': False,
            'trading_candles': False,
            'balance_update': False,
            'exchange_ws_reconnection': False,
        },
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


def run_single_backtest(
    condition_name: str,
    condition: dict,
    exchange: str,
    symbol: str,
    strategy: str,
    timeframe: str,
    balance: float,
    fee: float,
) -> dict:
    """Run a single backtest and return the result dict."""
    print(f'\n{"="*60}')
    print(f'Running: {condition["label"]}')
    print(f'  Period: {condition["start"]} → {condition["finish"]}')
    print(f'  {condition["description"]}')
    print(f'{"="*60}')

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
    config['env']['data']['generate_candles_from_1m'] = True
    config['env']['data']['warmup_candles_num'] = 210
    # Set trading mode (normally done by run(), but we call _execute_backtest directly)
    config['app']['trading_mode'] = 'backtest'
    config['app']['debug_mode'] = False

    user_config = setup_config(exchange, balance, fee)

    routes = [
        {'symbol': symbol, 'timeframe': timeframe, 'strategy': strategy}
    ]

    # RegimeRouter needs 1D and 4h candles as data routes
    data_routes = [
        {'symbol': symbol, 'timeframe': '1D'},
        {'symbol': symbol, 'timeframe': '4h'},
    ]

    # client_id must be a valid UUID (DB schema constraint)
    client_id = str(uuid.uuid4())

    # Register process as active in Redis so the status checker doesn't kill it
    from openquant.services.redis import sync_redis
    from openquant.services.env import ENV_VALUES
    port = ENV_VALUES.get('APP_PORT', '9000')
    sync_redis.sadd(f"{port}|active-processes", client_id)

    start_time = time.time()
    try:
        # run() returns None — results live in the store after completion.
        # We use report.portfolio_metrics() and report.trades() to extract them.
        backtest_mode.run(
            client_id=client_id,
            debug_mode=False,
            user_config=user_config,
            exchange=exchange,
            routes=routes,
            data_routes=data_routes,
            start_date=condition['start'],
            finish_date=condition['finish'],
            candles=None,  # Load from database
            chart=False,
            tradingview=False,
            csv=False,
            json=False,
            fast_mode=False,
            benchmark=False,
        )
    except Exception as e:
        print(f'  ERROR: {e}')
        return {
            'condition': condition_name,
            'label': condition['label'],
            'period': f'{condition["start"]} → {condition["finish"]}',
            'error': str(e),
            'metrics': None,
        }

    elapsed = time.time() - start_time

    # Extract results from the store (run() doesn't return them)
    from openquant.services import report
    metrics = report.portfolio_metrics()
    trades_list = report.trades()

    summary = {
        'condition': condition_name,
        'label': condition['label'],
        'period': f'{condition["start"]} → {condition["finish"]}',
        'description': condition['description'],
        'execution_seconds': round(elapsed, 1),
        'metrics': _extract_key_metrics(metrics),
        'trade_count': len(trades_list),
        'error': None,
    }

    if metrics:
        _print_condition_summary(summary)

    return summary


def _extract_key_metrics(metrics: dict | None) -> dict | None:
    """Extract the key metrics we care about from the full metrics dict."""
    if metrics is None:
        return None
    return {
        'net_profit_pct': metrics.get('net_profit_percentage', 0),
        'sharpe_ratio': metrics.get('sharpe_ratio', 0),
        'sortino_ratio': metrics.get('sortino_ratio', 0),
        'calmar_ratio': metrics.get('calmar_ratio', 0),
        'max_drawdown': metrics.get('max_drawdown', 0),
        'win_rate': metrics.get('win_rate', 0),
        'total_trades': metrics.get('total', 0),
        'longs_count': metrics.get('longs_count', 0),
        'shorts_count': metrics.get('shorts_count', 0),
        'ratio_avg_win_loss': metrics.get('ratio_avg_win_loss', 0),
        'annual_return': metrics.get('annual_return', 0),
        'expectancy_pct': metrics.get('expectancy_percentage', 0),
        'winning_streak': metrics.get('winning_streak', 0),
        'losing_streak': metrics.get('losing_streak', 0),
        'largest_winning_trade': metrics.get('largest_winning_trade', 0),
        'largest_losing_trade': metrics.get('largest_losing_trade', 0),
        'fee': metrics.get('fee', 0),
    }


def _print_condition_summary(summary: dict) -> None:
    """Print a quick summary for one condition."""
    m = summary['metrics']
    if m is None:
        print('  No trades executed.')
        return
    print(f'  PnL: {m["net_profit_pct"]:+.1f}% | Sharpe: {m["sharpe_ratio"]:.2f} | '
          f'Max DD: {m["max_drawdown"]:.1f}% | Win Rate: {m["win_rate"]*100:.1f}%')
    print(f'  Trades: {m["total_trades"]} ({m["longs_count"]}L/{m["shorts_count"]}S) | '
          f'W/L ratio: {m["ratio_avg_win_loss"]:.2f}x | '
          f'Duration: {summary["execution_seconds"]:.1f}s')


def generate_report(results: list, config_info: dict) -> str:
    """Generate a formatted comparison report."""
    lines = []
    lines.append('# RegimeRouter Backtest Report')
    lines.append(f'Generated: {datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")}')
    lines.append(f'Strategy: {config_info["strategy"]}')
    lines.append(f'Exchange: {config_info["exchange"]} | Symbol: {config_info["symbol"]} | '
                 f'Timeframe: {config_info["timeframe"]}')
    lines.append(f'Starting Balance: ${config_info["balance"]:,.0f} | Fee: {config_info["fee"]*100:.2f}%')
    lines.append('')

    # Comparison table
    lines.append('## Results Comparison')
    lines.append('')
    header = f'{"Condition":<25} {"PnL %":>8} {"Sharpe":>8} {"Sortino":>8} {"Max DD":>8} {"Win Rate":>9} {"Trades":>7}'
    lines.append(header)
    lines.append('-' * len(header))

    for r in results:
        m = r.get('metrics')
        if r.get('error'):
            lines.append(f'{r["label"]:<25} {"ERROR":>8}  {r["error"]}')
        elif m is None:
            lines.append(f'{r["label"]:<25} {"N/A":>8}  No trades executed')
        else:
            lines.append(
                f'{r["label"]:<25} {m["net_profit_pct"]:>+7.1f}% '
                f'{m["sharpe_ratio"]:>8.2f} {m["sortino_ratio"]:>8.2f} '
                f'{m["max_drawdown"]:>7.1f}% {m["win_rate"]*100:>8.1f}% '
                f'{m["total_trades"]:>7d}'
            )

    lines.append('')

    # Gate check
    lines.append('## Phase Gate Check')
    sharpe_values = [
        r['metrics']['sharpe_ratio']
        for r in results
        if r.get('metrics') and not r.get('error')
    ]
    if sharpe_values:
        min_sharpe = min(sharpe_values)
        avg_sharpe = sum(sharpe_values) / len(sharpe_values)
        gate_pass = min_sharpe >= 0.7
        lines.append(f'Min Sharpe across conditions: {min_sharpe:.2f}')
        lines.append(f'Avg Sharpe across conditions: {avg_sharpe:.2f}')
        lines.append(f'Gate (Sharpe >= 0.7 all conditions): {"PASS" if gate_pass else "FAIL"}')
    else:
        lines.append('Gate check: INSUFFICIENT DATA (no successful backtests)')

    lines.append('')

    # Per-condition details
    lines.append('## Per-Condition Details')
    for r in results:
        lines.append(f'\n### {r["label"]}')
        lines.append(f'Period: {r["period"]}')
        lines.append(f'Description: {r.get("description", "N/A")}')
        m = r.get('metrics')
        if r.get('error'):
            lines.append(f'Error: {r["error"]}')
        elif m is None:
            lines.append('No trades executed in this period.')
        else:
            lines.append(f'  Net PnL:        {m["net_profit_pct"]:+.1f}%')
            lines.append(f'  Annual Return:   {m["annual_return"]:.1f}%')
            lines.append(f'  Sharpe Ratio:    {m["sharpe_ratio"]:.2f}')
            lines.append(f'  Sortino Ratio:   {m["sortino_ratio"]:.2f}')
            lines.append(f'  Calmar Ratio:    {m["calmar_ratio"]:.2f}')
            lines.append(f'  Max Drawdown:    {m["max_drawdown"]:.1f}%')
            lines.append(f'  Win Rate:        {m["win_rate"]*100:.1f}%')
            lines.append(f'  Total Trades:    {m["total_trades"]} ({m["longs_count"]}L/{m["shorts_count"]}S)')
            lines.append(f'  Avg Win/Loss:    {m["ratio_avg_win_loss"]:.2f}x')
            lines.append(f'  Expectancy:      {m["expectancy_pct"]:.2f}%/trade')
            lines.append(f'  Streaks:         {m["winning_streak"]}W / {m["losing_streak"]}L')
            lines.append(f'  Best Trade:      {m["largest_winning_trade"]:.2f}')
            lines.append(f'  Worst Trade:     {m["largest_losing_trade"]:.2f}')
            lines.append(f'  Total Fees:      {m["fee"]:.2f}')

    return '\n'.join(lines)


def save_results(results: list, report_text: str, config_info: dict) -> Path:
    """Save results to a timestamped directory in results/."""
    timestamp = datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')
    results_dir = Path('results') / timestamp
    results_dir.mkdir(parents=True, exist_ok=True)

    # Save config
    config_path = results_dir / 'config.json'
    config_path.write_text(json.dumps(config_info, indent=2))

    # Save raw results
    raw_path = results_dir / 'results.json'
    raw_path.write_text(json.dumps(results, indent=2))

    # Save formatted report
    report_path = results_dir / 'report.txt'
    report_path.write_text(report_text)

    print(f'\nResults saved to {results_dir}/')
    return results_dir


def main():
    parser = argparse.ArgumentParser(description='Run RegimeRouter backtests across market conditions')
    parser.add_argument('--conditions', nargs='+', default=list(MARKET_CONDITIONS.keys()),
                        choices=list(MARKET_CONDITIONS.keys()),
                        help='Market conditions to test')
    parser.add_argument('--exchange', default=DEFAULT_EXCHANGE)
    parser.add_argument('--symbol', default=DEFAULT_SYMBOL)
    parser.add_argument('--strategy', default=DEFAULT_STRATEGY)
    parser.add_argument('--timeframe', default=DEFAULT_TIMEFRAME)
    parser.add_argument('--balance', type=float, default=DEFAULT_BALANCE)
    parser.add_argument('--fee', type=float, default=DEFAULT_FEE)
    args = parser.parse_args()

    config_info = {
        'exchange': args.exchange,
        'symbol': args.symbol,
        'strategy': args.strategy,
        'timeframe': args.timeframe,
        'balance': args.balance,
        'fee': args.fee,
        'conditions': args.conditions,
        'run_date': datetime.now(timezone.utc).isoformat(),
    }

    print(f'RegimeRouter Multi-Condition Backtest')
    print(f'Exchange: {args.exchange} | Symbol: {args.symbol}')
    print(f'Conditions: {", ".join(args.conditions)}')

    results = []
    for name in args.conditions:
        condition = MARKET_CONDITIONS[name]
        summary = run_single_backtest(
            condition_name=name,
            condition=condition,
            exchange=args.exchange,
            symbol=args.symbol,
            strategy=args.strategy,
            timeframe=args.timeframe,
            balance=args.balance,
            fee=args.fee,
        )
        results.append(summary)

    report_text = generate_report(results, config_info)

    print(f'\n{"="*60}')
    print(report_text)
    print(f'{"="*60}')

    save_results(results, report_text, config_info)


if __name__ == '__main__':
    main()
