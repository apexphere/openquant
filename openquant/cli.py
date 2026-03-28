import os
import time
import uuid
import json
import sys

import click
from importlib.metadata import version as get_version
import uvicorn

import openquant.helpers as jh
from openquant.services.multiprocessing import process_manager
from openquant.services.web import fastapi_app


def _get_server_url() -> str:
    """Get the OpenQuant server URL from .env or default."""
    try:
        from openquant.services.env import ENV_VALUES
        port = ENV_VALUES.get('APP_PORT', '9000')
    except Exception:
        port = '9000'
    return f'http://localhost:{port}'


def _get_auth_token(server_url: str) -> str:
    """Authenticate with the server and return the auth token."""
    import requests
    try:
        from openquant.services.env import ENV_VALUES
        password = ENV_VALUES.get('PASSWORD', 'openquant123')
    except Exception:
        password = 'openquant123'

    try:
        resp = requests.post(f'{server_url}/auth/login',
                             json={'password': password}, timeout=5)
        resp.raise_for_status()
        return resp.json()['auth_token']
    except requests.ConnectionError:
        click.echo('Error: OpenQuant server is not running. Start it with: jesse run')
        sys.exit(1)
    except Exception as e:
        click.echo(f'Error authenticating: {e}')
        sys.exit(1)


def _api_post(path: str, data: dict = None, server_url: str = None,
              token: str = None) -> dict:
    """Make an authenticated POST request to the API."""
    import requests
    if server_url is None:
        server_url = _get_server_url()
    if token is None:
        token = _get_auth_token(server_url)
    resp = requests.post(f'{server_url}{path}',
                         json=data or {},
                         headers={'Authorization': token},
                         timeout=30)
    return json.loads(resp.text) if resp.text else {}


def _wait_for_session(session_id: str, server_url: str, token: str,
                       poll_interval: float = 3.0, timeout: float = 600) -> dict:
    """Poll until a backtest/optimization session finishes, showing progress."""
    import requests
    elapsed = 0.0
    last_status = ''
    while elapsed < timeout:
        time.sleep(poll_interval)
        elapsed += poll_interval
        try:
            resp = requests.post(
                f'{server_url}/backtest/sessions/{session_id}',
                json={}, headers={'Authorization': token}, timeout=10)
            data = json.loads(resp.text)
            session = data.get('session', {})
            status = session.get('status', 'unknown')
            if status in ('finished', 'stopped', 'terminated'):
                click.echo('')  # newline after progress dots
                return session
            # Show progress indicator
            if status != last_status:
                click.echo(f'\r  [{status}] {int(elapsed)}s...', nl=False)
                last_status = status
            else:
                click.echo('.', nl=False)
        except Exception:
            pass
    click.echo(f'\nTimeout after {timeout}s waiting for session {session_id}')
    return {}


def _save_session_results_state(
    session_id, session, strategy, exchange, symbol, timeframe,
    start, finish, data_routes, server_url, token
):
    """Save full state so the dashboard shows General Info, Routes, and metrics."""
    metrics = session.get('metrics', {})
    hp = session.get('hyperparameters', [])
    trades = session.get('trades', [])
    state = {
        'form': {
            'start_date': start,
            'finish_date': finish,
            'debug_mode': False,
            'export_chart': True,
            'export_tradingview': False,
            'export_csv': False,
            'export_json': True,
            'fast_mode': False,
            'benchmark': True,
            'exchange': exchange,
            'routes': [{'symbol': symbol, 'timeframe': timeframe, 'strategy': strategy}],
            'data_routes': data_routes,
        },
        'results': {
            'showResults': True,
            'executing': False,
            'logsModal': False,
            'progressbar': {'current': 100, 'estimated_remaining_seconds': 0},
            'routes_info': [[
                {'value': symbol, 'style': ''},
                {'value': timeframe, 'style': ''},
                {'value': strategy, 'style': ''},
            ]],
            'generalInfo': {
                'title': None,
                'description': None,
                'session_id': session_id,
                'debug_mode': 'False',
            },
            'metrics': metrics if metrics else {},
            'hyperparameters': hp if hp else [],
            'trades': trades if trades else [],
            'exception': session.get('exception'),
            'alert': None,
            'info': None,
        },
    }
    try:
        _api_post('/backtest/update-state', {'id': session_id, 'state': state}, server_url, token)
    except Exception:
        pass  # non-critical — backtest results still accessible


def _format_regime_periods(periods: list) -> str:
    """Format regime periods as a readable timeline."""
    if not periods:
        return ''
    from datetime import datetime, timezone
    lines = ['  Regime Timeline:']
    for p in periods:
        start_ts = p.get('start', 0)
        end_ts = p.get('end', 0)
        regime = p.get('regime', '?')
        start_str = datetime.fromtimestamp(start_ts / 1000, tz=timezone.utc).strftime('%Y-%m-%d')
        end_str = datetime.fromtimestamp(end_ts / 1000, tz=timezone.utc).strftime('%Y-%m-%d')
        duration_days = max(1, round((end_ts - start_ts) / (1000 * 86400)))
        lines.append(f'    {start_str} → {end_str}  ({duration_days:>3}d)  {regime}')
    return '\n'.join(lines)


def _format_metrics(m: dict) -> str:
    """Format a metrics dict as a readable table with interpretation."""
    if not m:
        return '  No metrics available.'

    total = m.get('total', 0) or 0
    sharpe = m.get('sharpe_ratio', 0) or 0
    max_dd = m.get('max_drawdown', 0) or 0
    win_rate = (m.get('win_rate', 0) or 0) * 100
    wl_ratio = m.get('ratio_avg_win_loss', 0) or 0
    max_underwater = m.get('max_underwater_period', 0) or 0
    gross_profit = m.get('gross_profit', 0) or 0
    gross_loss = abs(m.get('gross_loss', 0) or 0)
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else 0

    lines = [
        f'  Net PnL:        {m.get("net_profit_percentage", 0):+.2f}%',
        f'  Annual Return:   {m.get("annual_return", 0):.1f}%',
        f'  Sharpe Ratio:    {sharpe:.2f}{_sharpe_note(sharpe, total)}',
        f'  Sortino Ratio:   {m.get("sortino_ratio", 0):.2f}',
        f'  Calmar Ratio:    {m.get("calmar_ratio", 0):.2f}',
        f'  Max Drawdown:    {max_dd:.1f}%{_drawdown_note(max_dd, max_underwater)}',
        f'  Win Rate:        {win_rate:.1f}%',
        f'  Total Trades:    {total} '
        f'({m.get("longs_count", 0)}L/{m.get("shorts_count", 0)}S)',
        f'  Avg Win/Loss:    {wl_ratio:.2f}x',
        f'  Profit Factor:   {profit_factor:.2f}{_profit_factor_note(profit_factor)}',
        f'  Expectancy:      {m.get("expectancy_percentage", 0):.2f}%/trade',
    ]
    return '\n'.join(lines)


def _sharpe_note(sharpe: float, total: int) -> str:
    if total < 30:
        return f'  ⚠ {total} trades — not statistically significant'
    if total < 100:
        return f'  ({total} trades — marginal significance)'
    return ''


def _drawdown_note(max_dd: float, max_underwater: float) -> str:
    parts = []
    if max_underwater > 0:
        parts.append(f'{max_underwater:.0f}d underwater')
    if max_dd < -10:
        parts.append('severe')
    elif max_dd < -5:
        parts.append('moderate')
    return f'  ({", ".join(parts)})' if parts else ''


def _profit_factor_note(pf: float) -> str:
    if pf == 0:
        return ''
    if pf < 1.0:
        return '  ⚠ losing (< 1.0)'
    if pf < 1.3:
        return '  ⚠ fragile (< 1.3)'
    if pf >= 2.0:
        return '  strong'
    return ''


def _format_benchmark(b: dict) -> str:
    """Format benchmark comparison."""
    if not b:
        return ''
    lines = [
        f'\n  Benchmark ({b.get("symbol", "?")} Buy & Hold):',
        f'    B&H Return:    {b.get("buy_and_hold_return", 0):+.2f}%',
        f'    B&H Sharpe:    {b.get("buy_and_hold_sharpe", 0):.2f}',
        f'    B&H Drawdown:  {b.get("buy_and_hold_max_drawdown", 0):.1f}%',
        f'    Alpha:         {b.get("alpha", 0):+.2f}%',
    ]
    return '\n'.join(lines)


@click.group()
@click.version_option(get_version("openquant"))
def cli() -> None:
    """OpenQuant — regime-aware strategy composition framework."""
    pass


@cli.command()
@click.argument('strategy')
@click.option('--start', required=True, help='Start date (YYYY-MM-DD)')
@click.option('--finish', required=True, help='Finish date (YYYY-MM-DD)')
@click.option('--exchange', default='Bybit USDT Perpetual', help='Exchange name')
@click.option('--symbol', default='BTC-USDT', help='Trading pair')
@click.option('--timeframe', default='15m', help='Trading timeframe')
@click.option('--balance', default=10000.0, type=float, help='Starting balance')
@click.option('--fee', default=0.001, type=float, help='Trading fee (decimal)')
@click.option('--warmup', default=210, type=int, help='Warmup candles')
@click.option('--data-routes', default=None, help='Extra timeframes, comma-separated (e.g., 1D,4h)')
@click.option('--json-output', is_flag=True, help='Output raw JSON instead of formatted text')
def backtest(strategy, start, finish, exchange, symbol, timeframe,
             balance, fee, warmup, data_routes, json_output) -> None:
    """Run a backtest for STRATEGY and display results.

    Requires the server to be running (jesse run).

    Examples:

        jesse backtest RegimeRouter --start 2025-06-01 --finish 2025-09-30

        jesse backtest TrendBreak --start 2025-06-01 --finish 2025-09-30 --timeframe 4h

        jesse backtest RegimeRouterV2 --start 2025-06-01 --finish 2025-09-30 --data-routes 1D,4h
    """
    server_url = _get_server_url()
    token = _get_auth_token(server_url)
    session_id = str(uuid.uuid4())

    # Build data routes
    if data_routes:
        dr = [{'symbol': symbol, 'timeframe': tf.strip()} for tf in data_routes.split(',')]
    else:
        # Default: include 1D and 4h for regime-aware strategies
        dr = [{'symbol': symbol, 'timeframe': '1D'}, {'symbol': symbol, 'timeframe': '4h'}]
        # Remove the primary timeframe if it's in data routes
        dr = [r for r in dr if r['timeframe'] != timeframe]

    payload = {
        'id': session_id,
        'exchange': exchange,
        'routes': [{'symbol': symbol, 'timeframe': timeframe, 'strategy': strategy}],
        'data_routes': dr,
        'config': {
            'warm_up_candles': warmup,
            'logging': {
                'strategy_execution': False, 'order_submission': True,
                'order_cancellation': True, 'order_execution': True,
                'position_opened': True, 'position_increased': True,
                'position_reduced': True, 'position_closed': True,
                'shorter_period_candles': False, 'trading_candles': False,
                'balance_update': True, 'exchange_ws_reconnection': False,
            },
            'exchanges': {
                exchange: {
                    'name': exchange, 'fee': fee, 'type': 'futures',
                    'futures_leverage_mode': 'cross', 'futures_leverage': 1,
                    'balance': balance,
                }
            },
        },
        'start_date': start,
        'finish_date': finish,
        'debug_mode': False,
        'export_chart': True,
        'export_tradingview': False,
        'export_csv': False,
        'export_json': True,
        'fast_mode': False,
        'benchmark': True,
    }

    click.echo(f'Backtesting {strategy} on {symbol} ({timeframe})')
    click.echo(f'Period: {start} → {finish} | Balance: ${balance:,.0f} | Fee: {fee*100:.2f}%')

    # Submit backtest — session state (strategy name, exchange, symbol)
    # is saved inside the backtest mode, not here
    _api_post('/backtest', payload, server_url, token)

    click.echo(f'Submitted. Session ID: {session_id}')
    click.echo(f'Check progress:  jesse status')
    click.echo(f'View results:    jesse results {session_id}')


@cli.command('cancel')
@click.argument('session_id')
@click.option('--type', 'session_type', default='backtest',
              type=click.Choice(['backtest', 'optimization']),
              help='Session type to cancel')
def cancel(session_id, session_type) -> None:
    """Cancel a running backtest or optimization.

    Examples:

        jesse cancel abc123-def456

        jesse cancel abc123-def456 --type optimization
    """
    server_url = _get_server_url()
    token = _get_auth_token(server_url)

    if session_type == 'optimization':
        endpoint = '/optimization/terminate'
    else:
        endpoint = '/backtest/cancel'

    data = _api_post(endpoint, {'id': session_id}, server_url, token)
    click.echo(data.get('message', f'Cancelled {session_id}'))


@cli.command()
@click.argument('session_id', required=False)
@click.option('--limit', default=10, type=int, help='Number of sessions to show')
@click.option('--json-output', is_flag=True, help='Output raw JSON')
def results(session_id, limit, json_output) -> None:
    """Show backtest results. Without SESSION_ID, lists recent sessions.

    Examples:

        jesse results

        jesse results abc123-def456

        jesse results --limit 20
    """
    server_url = _get_server_url()
    token = _get_auth_token(server_url)

    if session_id:
        # Show specific session
        data = _api_post(f'/backtest/sessions/{session_id}', {}, server_url, token)
        session = data.get('session', {})
        if not session:
            click.echo(f'Session {session_id} not found.')
            sys.exit(1)
        if json_output:
            click.echo(json.dumps(session, indent=2, default=str))
        else:
            click.echo(f'Session: {session_id}')
            click.echo(f'Status:  {session.get("status", "unknown")}')
            if session.get('status') == 'stopped' and session.get('exception'):
                click.echo(f'\n  Error: {session["exception"][:300]}')
            else:
                click.echo(f'\n{_format_metrics(session.get("metrics"))}')
                trades = session.get('trades', [])
                if trades:
                    click.echo(f'\n  Trade count: {len(trades)}')
                m = session.get('metrics')
                bench = m.get('benchmark') if m else None
                if bench:
                    click.echo(_format_benchmark(bench))
                regime_periods = session.get('regime_periods')
                if regime_periods:
                    click.echo(f'\n{_format_regime_periods(regime_periods)}')
    else:
        # List recent sessions
        data = _api_post('/backtest/sessions', {'limit': limit}, server_url, token)
        sessions = data.get('sessions', data.get('data', []))
        if not sessions:
            click.echo('No backtest sessions found.')
            return
        if json_output:
            click.echo(json.dumps(sessions, indent=2, default=str))
        else:
            click.echo(f'{"ID":<38} {"Status":<10} {"PnL":>8} {"Updated"}')
            click.echo('-' * 75)
            from datetime import datetime, timezone
            for s in sessions:
                pnl = s.get('net_profit_percentage')
                pnl_str = f'{pnl:+.1f}%' if pnl is not None else 'N/A'
                updated_raw = s.get('updated_at', 0)
                if isinstance(updated_raw, (int, float)) and updated_raw > 1e12:
                    updated = datetime.fromtimestamp(updated_raw / 1000, tz=timezone.utc).strftime('%Y-%m-%d %H:%M')
                else:
                    updated = str(updated_raw)[:19]
                click.echo(f'{s["id"]:<38} {s.get("status", "?"):<10} {pnl_str:>8} {updated}')


@cli.command()
@click.argument('strategy')
@click.option('--training-start', required=True, help='Training period start (YYYY-MM-DD)')
@click.option('--training-finish', required=True, help='Training period finish (YYYY-MM-DD)')
@click.option('--testing-start', required=True, help='Testing period start (YYYY-MM-DD)')
@click.option('--testing-finish', required=True, help='Testing period finish (YYYY-MM-DD)')
@click.option('--exchange', default='Bybit USDT Perpetual')
@click.option('--symbol', default='BTC-USDT')
@click.option('--timeframe', default='15m')
@click.option('--balance', default=10000.0, type=float)
@click.option('--fee', default=0.001, type=float)
@click.option('--warmup', default=210, type=int)
@click.option('--trials', default=100, type=int, help='Optimization trials')
@click.option('--objective', default='sharpe', help='Objective function (sharpe, sortino, calmar)')
@click.option('--cpu-cores', default=4, type=int)
def optimize(strategy, training_start, training_finish, testing_start,
             testing_finish, exchange, symbol, timeframe, balance, fee,
             warmup, trials, objective, cpu_cores) -> None:
    """Run parameter optimization for STRATEGY.

    Requires the server to be running (jesse run).

    Example:

        jesse optimize RegimeRouterV2 \\
          --training-start 2025-06-01 --training-finish 2025-09-30 \\
          --testing-start 2025-10-01 --testing-finish 2025-12-31
    """
    server_url = _get_server_url()
    token = _get_auth_token(server_url)

    data_routes = [{'symbol': symbol, 'timeframe': '1D'},
                   {'symbol': symbol, 'timeframe': '4h'}]
    data_routes = [r for r in data_routes if r['timeframe'] != timeframe]

    exchange_config = {
        'name': exchange, 'fee': fee, 'type': 'futures',
        'futures_leverage_mode': 'cross', 'futures_leverage': 1,
        'balance': balance,
    }
    payload = {
        'exchange': exchange,
        'routes': [{'symbol': symbol, 'timeframe': timeframe, 'strategy': strategy}],
        'data_routes': data_routes,
        'config': {
            'warm_up_candles': warmup,
            'objective_function': objective,
            'trials': trials,
            'best_candidates_count': 20,
            'logging': {},
            'exchange': exchange_config,
            'exchanges': {exchange: exchange_config},
        },
        'training_start_date': training_start,
        'training_finish_date': training_finish,
        'testing_start_date': testing_start,
        'testing_finish_date': testing_finish,
        'optimal_total': 10,
        'fast_mode': False,
        'cpu_cores': cpu_cores,
        'state': {},
    }

    click.echo(f'Optimizing {strategy} on {symbol} ({timeframe})')
    click.echo(f'Training: {training_start} → {training_finish}')
    click.echo(f'Testing:  {testing_start} → {testing_finish}')
    click.echo(f'Trials: {trials} | Objective: {objective} | CPU cores: {cpu_cores}')

    _api_post('/optimization', payload, server_url, token)
    click.echo('Optimization started. Check the dashboard for progress.')


@cli.command('status')
def status() -> None:
    """Show running backtests and optimizations.

    Example:

        jesse status
    """
    server_url = _get_server_url()
    token = _get_auth_token(server_url)

    # Check running backtests
    data = _api_post('/backtest/sessions', {'limit': 20}, server_url, token)
    sessions = data.get('sessions', data.get('data', []))
    running_bt = [s for s in sessions if s.get('status') == 'running']

    # Check running optimizations
    data = _api_post('/optimization/sessions', {'limit': 10}, server_url, token)
    opt_sessions = data.get('sessions', [])
    running_opt = [s for s in opt_sessions if s.get('status') == 'running']

    if not running_bt and not running_opt:
        click.echo('No running jobs.')
        return

    if running_bt:
        click.echo(f'Backtests ({len(running_bt)} running):')
        click.echo(f'  {"ID":<38} {"Updated"}')
        click.echo(f'  {"-" * 55}')
        from datetime import datetime, timezone
        for s in running_bt:
            updated_raw = s.get('updated_at', 0)
            if isinstance(updated_raw, (int, float)) and updated_raw > 1e12:
                updated_raw = updated_raw / 1000
            try:
                updated = datetime.fromtimestamp(updated_raw).strftime('%H:%M:%S')
            except Exception:
                updated = '?'
            click.echo(f'  {s["id"]:<38} {updated}')
        click.echo()

    if running_opt:
        click.echo(f'Optimizations ({len(running_opt)} running):')
        click.echo(f'  {"ID":<38} {"Progress":>10} {"Best":>8}')
        click.echo(f'  {"-" * 60}')
        for s in running_opt:
            completed = s.get('completed_trials', 0)
            total = s.get('total_trials', 0)
            best = s.get('best_score')
            best_str = f'{best:.4f}' if best is not None else 'N/A'
            progress = f'{completed}/{total}'
            click.echo(f'  {s["id"]:<38} {progress:>10} {best_str:>8}')


@cli.command('optimize-results')
@click.argument('session_id', required=False)
@click.option('--limit', default=5, type=int, help='Number of top trials to show')
@click.option('--json-output', is_flag=True, help='Output as JSON')
def optimize_results(session_id, limit, json_output) -> None:
    """Show optimization results. Without SESSION_ID, lists recent sessions.

    Examples:

        jesse optimize-results

        jesse optimize-results abc123-def456

        jesse optimize-results abc123-def456 --limit 10
    """
    server_url = _get_server_url()
    token = _get_auth_token(server_url)

    if session_id:
        data = _api_post(f'/optimization/sessions/{session_id}', {}, server_url, token)
        session = data.get('session', {})
        if not session:
            click.echo(f'Optimization session {session_id} not found.')
            sys.exit(1)

        if json_output:
            click.echo(json.dumps(session, indent=2, default=str))
            return

        status = session.get('status', 'unknown')
        completed = session.get('completed_trials', 0)
        total = session.get('total_trials', 0)
        best_score = session.get('best_score')
        pct = (completed / total * 100) if total > 0 else 0

        click.echo(f'Session:  {session_id}')
        click.echo(f'Status:   {status}')
        click.echo(f'Progress: {completed}/{total} ({pct:.0f}%)')
        if best_score is not None:
            click.echo(f'Best:     {best_score:.4f}')
        click.echo()

        trials = session.get('best_candidates', session.get('best_trials', []))
        if isinstance(trials, str):
            trials = json.loads(trials) if trials else []
        if not trials:
            click.echo('No completed trials yet.')
            return

        # Show top N trials
        click.echo(f'Top {min(limit, len(trials))} trials:')
        click.echo(f'{"Rank":>4} {"Trial":>7} {"Fitness":>8} {"Train Sharpe":>13} {"Test Sharpe":>12}')
        click.echo('-' * 50)
        for i, t in enumerate(trials[:limit]):
            rank = i + 1
            trial_num = t.get('trial', t.get('trial_number', '?'))
            fitness = t.get('fitness', t.get('score', 0))
            # Try multiple key formats for training/testing metrics
            train_sharpe = _extract_sharpe(t, 'training')
            test_sharpe = _extract_sharpe(t, 'testing')
            click.echo(f'{rank:>4} {trial_num:>7} {fitness:>8.4f} {train_sharpe:>13} {test_sharpe:>12}')

        # Show best trial params
        click.echo()
        best = trials[0]
        params = best.get('params', best.get('hp', {}))
        if params:
            click.echo('Best params:')
            for k, v in sorted(params.items()):
                if isinstance(v, float):
                    click.echo(f'  {k}: {v:.4f}')
                else:
                    click.echo(f'  {k}: {v}')
    else:
        data = _api_post('/optimization/sessions', {'limit': 10}, server_url, token)
        sessions = data.get('sessions', [])
        if not sessions:
            click.echo('No optimization sessions found.')
            return

        if json_output:
            click.echo(json.dumps(sessions, indent=2, default=str))
            return

        click.echo(f'{"ID":<38} {"Status":<10} {"Progress":>10} {"Best":>8}')
        click.echo('-' * 72)
        for s in sessions:
            completed = s.get('completed_trials', 0)
            total = s.get('total_trials', 0)
            best = s.get('best_score')
            best_str = f'{best:.4f}' if best is not None else 'N/A'
            progress = f'{completed}/{total}'
            click.echo(f'{s["id"]:<38} {s.get("status", "?"):<10} {progress:>10} {best_str:>8}')


def _extract_sharpe(trial: dict, period: str) -> str:
    """Extract sharpe ratio from a trial dict, handling multiple formats."""
    # Format 1: training_sharpe / testing_sharpe keys
    key = f'{period}_sharpe'
    if key in trial:
        v = trial[key]
        return f'{v:.2f}' if v is not None else 'N/A'

    # Format 2: training_metrics / testing_metrics nested dict
    metrics_key = f'{period}_metrics'
    if metrics_key in trial and isinstance(trial[metrics_key], dict):
        v = trial[metrics_key].get('sharpe_ratio')
        return f'{v:.2f}' if v is not None else 'N/A'

    # Format 3: training / testing as direct sharpe values
    if period in trial:
        v = trial[period]
        if isinstance(v, (int, float)):
            return f'{v:.2f}'

    return 'N/A'


@cli.command('data')
def data() -> None:
    """Show available candle data for all symbols.

    Example:

        jesse data
    """
    from openquant.services.db import database
    if database.is_closed():
        database.open_connection()
    from openquant.models import Candle
    from datetime import datetime

    symbols = list(Candle.select(Candle.symbol).distinct())
    if not symbols:
        click.echo('No candle data in database.')
        return

    click.echo(f'{"Symbol":>12}  {"From":>12}  {"To":>12}  {"Candles":>10}  {"Months":>6}')
    click.echo('-' * 60)
    for s in sorted(symbols, key=lambda x: x.symbol):
        first = Candle.select(Candle.timestamp).where(Candle.symbol == s.symbol).order_by(Candle.timestamp.asc()).limit(1).first()
        last = Candle.select(Candle.timestamp).where(Candle.symbol == s.symbol).order_by(Candle.timestamp.desc()).limit(1).first()
        count = Candle.select().where(Candle.symbol == s.symbol).count()
        start = datetime.fromtimestamp(first.timestamp / 1000)
        end = datetime.fromtimestamp(last.timestamp / 1000)
        months = round((end - start).days / 30, 1)
        click.echo(
            f'{s.symbol:>12}  {start.strftime("%Y-%m-%d"):>12}  '
            f'{end.strftime("%Y-%m-%d"):>12}  {count:>10}  {months:>5.1f}m'
        )


@cli.command('import-candles')
@click.argument('symbol')
@click.option('--start', required=True, help='Start date (YYYY-MM-DD)')
@click.option('--exchange', default='Bybit USDT Perpetual')
def import_candles(symbol, start, exchange) -> None:
    """Import historical candles for a symbol.

    Examples:

        jesse import-candles SOL-USDT --start 2024-06-01

        jesse import-candles BNB-USDT --start 2024-06-01
    """
    server_url = _get_server_url()
    token = _get_auth_token(server_url)
    session_id = str(uuid.uuid4())

    payload = {
        'id': session_id,
        'exchange': exchange,
        'symbol': symbol,
        'start_date': start,
    }

    _api_post('/candles/import', payload, server_url, token)
    click.echo(f'Importing {symbol} from {exchange} starting {start}...')
    click.echo(f'Check progress in the dashboard (Import Candles tab).')


@cli.command('new-strategy')
@click.argument('name')
@click.option('--simple', is_flag=True, help='Create a simple (non-composite) strategy')
def new_strategy(name, simple) -> None:
    """Scaffold a new strategy with boilerplate files.

    Creates strategies/NAME/ with __init__.py, config.yaml (composite)
    or __init__.py (simple), plus thesis.md template.

    Examples:

        jesse new-strategy MyTrendRanger

        jesse new-strategy SimpleMA --simple
    """
    strategy_dir = os.path.join('strategies', name)
    if os.path.exists(strategy_dir):
        click.echo(f'Error: {strategy_dir} already exists.')
        sys.exit(1)

    os.makedirs(strategy_dir)

    if simple:
        init_content = f'''from openquant.strategies import Strategy
import openquant.indicators as ta


class {name}(Strategy):

    def hyperparameters(self):
        return [
            {{'name': 'sma_period', 'type': int, 'min': 10, 'max': 100, 'default': 20}},
        ]

    def should_long(self) -> bool:
        return self.price > ta.sma(self.candles, period=self.hp['sma_period'])

    def should_short(self) -> bool:
        return False

    def go_long(self):
        qty = (self.balance * 0.05) / self.price
        self.buy = qty, self.price
        self.stop_loss = qty, self.price * 0.95
        self.take_profit = qty, self.price * 1.10

    def go_short(self):
        pass

    def update_position(self):
        pass

    def should_cancel_entry(self):
        return False

    def filters(self):
        return []
'''
        with open(os.path.join(strategy_dir, '__init__.py'), 'w') as f:
            f.write(init_content)
    else:
        init_content = f'''from openquant.regime.composite import CompositeStrategy


class {name}(CompositeStrategy):
    config_file = 'config.yaml'
'''
        with open(os.path.join(strategy_dir, '__init__.py'), 'w') as f:
            f.write(init_content)

        config_content = f'''# {name} — composite strategy configuration

detector:
  type: ema_adx
  params:
    fast_period: 13
    slow_period: 34
    macd_fast: 12
    macd_slow: 26
    macd_signal: 9
    separation_pct: 0.3
    confirm_bars: 2

regimes:
  trending-up: trend_pullback
  trending-down: trend_pullback_short
  ranging-up: bb_mean_reversion
  ranging-down: bb_mean_reversion

transitions:
  on_switch: close_all
  cooldown_bars: 8

params:
  # Trend pullback (operates on daily candles)
  pb_timeframe: '1D'
  pb_fast_ema:
    default: 13
    min: 5
    max: 21
  pb_slow_ema:
    default: 34
    min: 20
    max: 55
  pb_rsi_period:
    default: 14
    min: 7
    max: 21
  pb_rsi_max:
    default: 70
    min: 60
    max: 85
  pb_rsi_min:
    default: 30
    min: 15
    max: 40
  pb_atr_period:
    default: 14
    min: 7
    max: 21
  pb_atr_sl_mult:
    default: 2.0
    min: 1.0
    max: 4.0

  # BB mean-reversion (operates on route timeframe)
  bb_window:
    default: 20
    min: 10
    max: 50
  bb_mult:
    default: 2.0
    min: 1.5
    max: 3.0
  bb_sl_pct:
    default: 0.015
    min: 0.005
    max: 0.03
  rsi_period:
    default: 14
    min: 7
    max: 21
  rsi_oversold:
    default: 35
    min: 20
    max: 45
  rsi_overbought:
    default: 65
    min: 55
    max: 85

  # Shared risk
  risk_pct:
    default: 0.05
    min: 0.02
    max: 0.15
  trail_pct:
    default: 0.03
    min: 0.01
    max: 0.10
  sl_pct:
    default: 0.05
    min: 0.02
    max: 0.10
  tp_pct:
    default: 0.10
    min: 0.05
    max: 0.30
'''
        with open(os.path.join(strategy_dir, 'config.yaml'), 'w') as f:
            f.write(config_content)

    # Write thesis.md template
    thesis_content = f'''# Strategy: {name}

## Thesis
<!-- 1-2 sentences, falsifiable -->

## Evidence
<!-- Academic papers, historical data, backtest results -->

## Premises
<!-- Numbered, each challengeable -->
1.

## Entry Rules

## Exit Rules

## Regime Mapping
<!-- Which detector, which behavior per regime -->

## Known Weaknesses

## Backtest Results

| Period | Asset | PNL | Sharpe | B&H Return | Alpha | Trades |
|--------|-------|-----|--------|------------|-------|--------|
|        |       |     |        |            |       |        |

## Status
DRAFT
'''
    with open(os.path.join(strategy_dir, 'thesis.md'), 'w') as f:
        f.write(thesis_content)

    files = ['__init__.py', 'thesis.md']
    if not simple:
        files.insert(1, 'config.yaml')
    click.echo(f'Created {strategy_dir}/')
    for f_name in files:
        click.echo(f'  {f_name}')
    click.echo(f'\nNext: edit thesis.md, then jesse backtest {name} --start ... --finish ...')
    click.echo(f'\nBacktest: jesse backtest {name} --start 2025-06-01 --finish 2025-09-30')


@cli.command()
@click.option(
    "--strict/--no-strict",
    default=True,
    help="Default is the strict mode which will raise an exception if the values for license is not set.",
)
def install_live(strict: bool) -> None:
    """Install and configure the live trading plugin."""
    from openquant.services.installer import install

    install(is_live_plugin_already_installed=jh.has_live_trade_plugin(), strict=strict)


@cli.command()
def run() -> None:
    """Start the Jesse application server."""
    # Display welcome message
    welcome_message = """
     ██╗███████╗███████╗███████╗███████╗
     ██║██╔════╝██╔════╝██╔════╝██╔════╝
     ██║█████╗  ███████╗███████╗█████╗  
██   ██║██╔══╝  ╚════██║╚════██║██╔══╝  
╚█████╔╝███████╗███████║███████║███████╗
 ╚════╝ ╚══════╝╚══════╝╚══════╝╚══════╝
                                        
    """
    version = get_version("openquant")
    print(welcome_message)
    print(f"Main Framework Version: {version}")

    # Check if jesse-live is installed and display its version
    if jh.has_live_trade_plugin():
        try:
            from openquant_live.version import __version__ as live_version

            print(f"Live Plugin Version: {live_version}")
        except ImportError:
            pass

    jh.validate_cwd()

    print("")

    # run all the db migrations
    from openquant.services.migrator import run as run_migrations
    import peewee

    try:
        run_migrations()
    except peewee.OperationalError:
        sleep_seconds = 10
        print(f"Database wasn't ready. Sleep for {sleep_seconds} seconds and try again.")
        time.sleep(sleep_seconds)
        run_migrations()

    # Install Python Language Server if needed
    try:
        from openquant.services.lsp import install_lsp_server

        install_lsp_server()
    except Exception as e:
        print(jh.color(f"Error installing Python Language Server: {str(e)}", "red"))
        pass

    # read port from .env file, if not found, use default
    from openquant.services.env import ENV_VALUES

    if "APP_PORT" in ENV_VALUES:
        port = int(ENV_VALUES["APP_PORT"])
    else:
        port = 9000

    if "APP_HOST" in ENV_VALUES:
        host = ENV_VALUES["APP_HOST"]
    else:
        host = "0.0.0.0"

    # run the lsp server
    try:
        from openquant.services.lsp import run_lsp_server

        run_lsp_server()
    except Exception as e:
        print(jh.color(f"Error running Python Language Server: {str(e)}", "red"))
        pass

    # run the main application
    process_manager.flush()
    uvicorn.run(fastapi_app, host=host, port=port, log_level="info")

