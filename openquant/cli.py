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
                       poll_interval: float = 2.0, timeout: float = 300) -> dict:
    """Poll until a backtest/optimization session finishes."""
    import requests
    elapsed = 0.0
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
                return session
        except Exception:
            pass
    click.echo(f'Timeout after {timeout}s waiting for session {session_id}')
    return {}


def _format_metrics(m: dict) -> str:
    """Format a metrics dict as a readable table."""
    if not m:
        return '  No metrics available.'
    lines = [
        f'  Net PnL:        {m.get("net_profit_percentage", 0):+.2f}%',
        f'  Annual Return:   {m.get("annual_return", 0):.1f}%',
        f'  Sharpe Ratio:    {m.get("sharpe_ratio", 0):.2f}',
        f'  Sortino Ratio:   {m.get("sortino_ratio", 0):.2f}',
        f'  Calmar Ratio:    {m.get("calmar_ratio", 0):.2f}',
        f'  Max Drawdown:    {m.get("max_drawdown", 0):.1f}%',
        f'  Win Rate:        {m.get("win_rate", 0) * 100:.1f}%',
        f'  Total Trades:    {m.get("total", 0)} '
        f'({m.get("longs_count", 0)}L/{m.get("shorts_count", 0)}S)',
        f'  Avg Win/Loss:    {m.get("ratio_avg_win_loss", 0):.2f}x',
        f'  Expectancy:      {m.get("expectancy_percentage", 0):.2f}%/trade',
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
        'benchmark': False,
    }

    click.echo(f'Backtesting {strategy} on {symbol} ({timeframe})')
    click.echo(f'Period: {start} → {finish} | Balance: ${balance:,.0f} | Fee: {fee*100:.2f}%')

    _api_post('/backtest', payload, server_url, token)

    click.echo('Running...', nl=False)
    session = _wait_for_session(session_id, server_url, token)
    click.echo(' done.')

    status = session.get('status', 'unknown')
    if status == 'stopped' and session.get('exception'):
        click.echo(f'Error: {session["exception"][:500]}')
        sys.exit(1)

    metrics = session.get('metrics')
    if json_output:
        click.echo(json.dumps(session, indent=2, default=str))
    elif metrics:
        click.echo(f'\n{_format_metrics(metrics)}')
        click.echo(f'\n  Session ID: {session_id}')
    else:
        click.echo('No trades executed in this period.')


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
            click.echo(f'\n{_format_metrics(session.get("metrics"))}')
            trades = session.get('trades', [])
            if trades:
                click.echo(f'\n  Trade count: {len(trades)}')
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
            'exchanges': {
                exchange: {
                    'name': exchange, 'fee': fee, 'type': 'futures',
                    'futures_leverage_mode': 'cross', 'futures_leverage': 1,
                    'balance': balance,
                }
            },
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


@cli.command('create-composite')
@click.argument('name')
def create_composite(name) -> None:
    """Scaffold a new YAML-configured composite strategy.

    Creates strategies/NAME/__init__.py and strategies/NAME/config.yaml
    with a working template.

    Example:

        jesse create-composite MyTrendRanger
    """
    strategy_dir = os.path.join('strategies', name)
    if os.path.exists(strategy_dir):
        click.echo(f'Error: {strategy_dir} already exists.')
        sys.exit(1)

    os.makedirs(strategy_dir)

    # Write __init__.py
    init_content = f'''from openquant.regime.composite import CompositeStrategy


class {name}(CompositeStrategy):
    config_file = 'config.yaml'
'''
    with open(os.path.join(strategy_dir, '__init__.py'), 'w') as f:
        f.write(init_content)

    # Write config.yaml template
    config_content = f'''# {name} — composite strategy configuration
# Docs: see CLAUDE.md "Regime-Aware Composition" section

detector:
  type: adx
  timeframe: 1D
  params:
    sma_period: 42
    adx_period: 14
    adx_min: 25
    confirm_bars: 3

regimes:
  trending-up:
    behavior: momentum_rotation
  trending-down: null              # flat — no trading
  ranging-up:
    behavior: bb_mean_reversion
  ranging-down:
    behavior: bb_mean_reversion
  cold-start: null

params:
  # Risk management
  risk_pct: 0.05
  sl_pct: 0.05
  tp_pct: 0.10
  trail_pct: 0.02
  # BB mean reversion
  bb_window: 15
  bb_mult: 2.5
  rsi_period: 14
  rsi_oversold: 30
  rsi_overbought: 70
  vol_mult: 1.2
  # Momentum rotation
  momentum_lookback: 42

transitions:
  on_switch: close_all             # close_all | close_opposite | hold
  cooldown_bars: 8

data_routes: [1D, 4h]
'''
    with open(os.path.join(strategy_dir, 'config.yaml'), 'w') as f:
        f.write(config_content)

    click.echo(f'Created {strategy_dir}/')
    click.echo(f'  __init__.py  — 3-line boilerplate')
    click.echo(f'  config.yaml  — edit this to define your strategy')
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

