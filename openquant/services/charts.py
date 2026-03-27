from datetime import datetime, timedelta
from openquant.routes import router
from openquant.store import store
from openquant.services.candle_service import get_candles_from_db
from openquant.utils import prices_to_returns


# Regime color palette — visually distinct, accessible
REGIME_COLORS = {
    # Trending regimes (greens/blues)
    'trending-up': '#22C55E',
    'trending-down': '#EF4444',
    # Ranging regimes (yellows/ambers)
    'ranging': '#F59E0B',
    'ranging-up': '#F59E0B',
    'ranging-down': '#FB923C',
    # Volatility regimes
    'high-volatility': '#EF4444',
    'low-volatility': '#60A5FA',
    'normal': '#818CF8',
    # Inactive states (grays)
    'cold-start': '#6B7280',
    'all': '#818CF8',
}

DEFAULT_REGIME_COLOR = '#818CF8'


def _regime_color(regime: str) -> str:
    return REGIME_COLORS.get(regime, DEFAULT_REGIME_COLOR)


def _calculate_equity_curve(daily_balance, start_date, name: str, color: str):
    date_list = [start_date + timedelta(days=x) for x in range(len(daily_balance))]
    eq = [{
        'time': date.timestamp(),
        'value': balance,
        'color': color
    } for date, balance in zip(date_list, daily_balance)]
    return {
        'name': name,
        'data': eq,
        'color': color,
    }


def _calculate_regime_equity_curve(daily_balance, start_date, regime_log):
    """Build equity curve with per-point colors based on active regime.

    Each data point gets the color of the regime that was active at that time.
    Regime transitions are stored as [{timestamp, regime}, ...] — we walk
    through them to assign colors to each daily balance point.
    """
    date_list = [start_date + timedelta(days=x) for x in range(len(daily_balance))]

    # Build a sorted list of (timestamp_seconds, regime) transitions
    transitions = sorted(
        (entry['timestamp'] / 1000, entry['regime']) for entry in regime_log
    )

    eq = []
    tx_idx = 0
    current_color = _regime_color(transitions[0][1]) if transitions else DEFAULT_REGIME_COLOR

    for date, balance in zip(date_list, daily_balance):
        ts = date.timestamp()
        # Advance through transitions that have occurred by this date
        while tx_idx < len(transitions) and transitions[tx_idx][0] <= ts:
            current_color = _regime_color(transitions[tx_idx][1])
            tx_idx += 1
        eq.append({
            'time': ts,
            'value': balance,
            'color': current_color,
        })

    return {
        'name': 'Portfolio',
        'data': eq,
        'color': DEFAULT_REGIME_COLOR,
    }


def _generate_color(previous_color):
    # Convert the previous color from hex to RGB
    previous_color = previous_color.lstrip('#')
    r, g, b = tuple(int(previous_color[i:i+2], 16) for i in (0, 2, 4))

    # Modify the RGB values to generate a new color
    r = (r + 50) % 256
    g = (g + 50) % 256
    b = (b + 50) % 256

    # Convert the new color from RGB to hex
    new_color = '#{:02x}{:02x}{:02x}'.format(r, g, b)

    return new_color


def equity_curve(benchmark: bool = False) -> list:
    if store.closed_trades.count == 0:
        return None

    result = []
    start_date = datetime.fromtimestamp(store.app.starting_time / 1000)
    daily_balance = store.app.daily_balance

    # Define the first 10 colors
    colors = ['#818CF8', '#fbbf24', '#fb7185', '#60A5FA', '#f472b6', '#A78BFA', '#f87171', '#6EE7B7', '#93C5FD', '#FCA5A5']

    # Check if the primary route's strategy has regime data
    regime_log = _collect_regime_log()
    if regime_log:
        result.append(_calculate_regime_equity_curve(daily_balance, start_date, regime_log))
    else:
        result.append(_calculate_equity_curve(daily_balance, start_date, 'Portfolio', colors[0]))

    if benchmark:
        initial_balance = daily_balance[0]
        for i, r in enumerate(router.routes):
            _, daily_candles = get_candles_from_db(
                r.exchange, r.symbol, '1D', store.app.starting_time,
                store.app.ending_time + 1000 * 60 * 60 * 24, is_for_jesse=False, warmup_candles_num=0, caching=True
            )
            daily_returns = prices_to_returns(daily_candles[:, 2])
            daily_returns[0] = 0
            daily_balance_benchmark = initial_balance * (1 + daily_returns/100).cumprod()

            # If there are more than 10 routes, generate new colors
            if i + 1 >= 10:
                colors.append(_generate_color(colors[-1]))

            result.append(_calculate_equity_curve(daily_balance_benchmark, start_date, r.symbol, colors[(i + 1) % len(colors)]))

    return result


def _collect_regime_log() -> list:
    """Collect regime log from the first route's strategy.

    Returns the log if the strategy has regime data (more than just 'all'),
    empty list otherwise.
    """
    if not router.routes:
        return []
    strategy = router.routes[0].strategy
    if strategy is None:
        return []
    log = getattr(strategy, '_regime_log', [])
    # Skip if strategy has no real regime detection (just 'all')
    if not log or (len(log) == 1 and log[0].get('regime') == 'all'):
        return []
    return log


def regime_periods() -> list | None:
    """Build a list of regime periods for API/CLI consumption.

    Returns:
        List of {start, end, regime, color} dicts, or None if no regime data.
        Timestamps are in milliseconds (matching the rest of the framework).
    """
    log = _collect_regime_log()
    if not log:
        return None

    sorted_log = sorted(log, key=lambda e: e['timestamp'])
    ending_time = store.app.ending_time if store.app.ending_time else store.app.time

    periods = []
    for i, entry in enumerate(sorted_log):
        end_ts = sorted_log[i + 1]['timestamp'] if i + 1 < len(sorted_log) else ending_time
        periods.append({
            'start': entry['timestamp'],
            'end': end_ts,
            'regime': entry['regime'],
            'color': _regime_color(entry['regime']),
        })

    return periods
