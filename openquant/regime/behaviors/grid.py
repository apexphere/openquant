"""Grid trading behavior for ranging markets.

Places buy/sell orders at fixed price intervals (grid levels) within
a detected range. Profits from price oscillation without predicting
direction. Each trade targets the next grid level as TP.

Grid levels computed from Donchian channel (actual high/low of last N bars).
Unlike Bollinger Bands, Donchian is anchored to real price extremes and adapts
in exactly N bars after a regime change — no regime-boundary lag problem.

Entry:
    Long:  price at or below a grid buy level (lower half of range)
    Short: price at or above a grid sell level (upper half of range)

Exit:
    TP: next grid level (one step profit)
    SL: beyond the range boundary + buffer (range is breaking)

Reads from strategy.hp:
    grid_timeframe (default '4h') — timeframe for Donchian channel
    grid_period (default 30) — Donchian lookback period
    grid_num_levels (default 5) — number of grid lines per side
    grid_sl_mult (default 1.5) — SL = grid_step * this multiplier
    risk_pct
"""
import numpy as np
import openquant.indicators as ta


class GridBehavior:
    """Grid trading: buy at lower grid levels, sell at upper grid levels.

    Uses Donchian channel for range bounds. Each trade targets one grid step.
    """

    def should_long(self, strategy) -> bool:
        if _in_cooldown(strategy):
            return False
        grid = _get_grid(strategy)
        if grid is None:
            return False
        # Reject if price has broken out of the channel
        if strategy.price <= grid['lower'] or strategy.price >= grid['upper']:
            return False
        # Only buy in lower half of range
        if strategy.price >= grid['mid']:
            return False
        for level in grid['buy_levels']:
            if strategy.price <= level:
                return True
        return False

    def should_short(self, strategy) -> bool:
        if _in_cooldown(strategy):
            return False
        grid = _get_grid(strategy)
        if grid is None:
            return False
        # Reject if price has broken out of the channel
        if strategy.price <= grid['lower'] or strategy.price >= grid['upper']:
            return False
        # Only sell in upper half of range
        if strategy.price <= grid['mid']:
            return False
        for level in grid['sell_levels']:
            if strategy.price >= level:
                return True
        return False

    def go_long(self, strategy) -> None:
        grid = _get_grid(strategy)
        qty = _size(strategy)
        step = grid['step']
        sl_mult = strategy.hp.get('grid_sl_mult', 1.0)
        tp_mult = strategy.hp.get('grid_tp_mult', 2.0)

        strategy.buy = qty, strategy.price
        strategy.stop_loss = qty, strategy.price - (step * sl_mult)
        strategy.take_profit = qty, strategy.price + (step * tp_mult)

    def go_short(self, strategy) -> None:
        grid = _get_grid(strategy)
        qty = _size(strategy)
        step = grid['step']
        sl_mult = strategy.hp.get('grid_sl_mult', 1.0)
        tp_mult = strategy.hp.get('grid_tp_mult', 2.0)

        strategy.sell = qty, strategy.price
        strategy.stop_loss = qty, strategy.price + (step * sl_mult)
        strategy.take_profit = qty, strategy.price - (step * tp_mult)

    def trace(self, strategy) -> dict:
        grid = _get_grid(strategy)
        if grid is None:
            return {'error': 'insufficient data'}
        return {
            'channel_high': round(float(grid['upper']), 2),
            'channel_low': round(float(grid['lower']), 2),
            'channel_mid': round(float(grid['mid']), 2),
            'channel_width_pct': round(float(grid['upper'] - grid['lower']) / float(grid['lower']) * 100, 2),
            'grid_step': round(float(grid['step']), 2),
            'grid_step_pct': round(float(grid['step']) / strategy.price * 100, 2),
            'sl_mult': float(strategy.hp.get('grid_sl_mult', 1.0)),
            'tp_mult': float(strategy.hp.get('grid_tp_mult', 2.0)),
            'num_levels': grid['num_levels'],
            'price_in_channel': bool(float(grid['lower']) < strategy.price < float(grid['upper'])),
            'price_position': round((strategy.price - float(grid['lower'])) / (float(grid['upper']) - float(grid['lower'])) * 100, 1),
        }

    def update_position(self, strategy) -> None:
        pass  # Fixed TP/SL per trade — no trailing


def _get_candles(strategy):
    tf = strategy.hp.get('grid_timeframe', '4h')
    return strategy.get_candles(strategy.exchange, strategy.symbol, tf)


def _get_grid(strategy):
    """Compute grid levels from Donchian channel (actual high/low)."""
    candles = _get_candles(strategy)
    period = strategy.hp.get('grid_period', 30)

    if candles is None or len(candles) < period + 2:
        return None

    # Donchian channel: highest high and lowest low of last N completed bars
    highs = candles[-(period + 1):-1, 3]
    lows = candles[-(period + 1):-1, 4]
    upper = float(np.max(highs))
    lower = float(np.min(lows))
    mid = (upper + lower) / 2

    num_levels = strategy.hp.get('grid_num_levels', 5)
    total_range = upper - lower
    if total_range <= 0:
        return None

    step = total_range / (num_levels + 1)

    # Buy levels: evenly spaced from mid down to lower
    buy_levels = [mid - step * i for i in range(1, num_levels // 2 + 2)]
    # Sell levels: evenly spaced from mid up to upper
    sell_levels = [mid + step * i for i in range(1, num_levels // 2 + 2)]

    return {
        'buy_levels': buy_levels,
        'sell_levels': sell_levels,
        'step': step,
        'upper': upper,
        'lower': lower,
        'mid': mid,
        'num_levels': num_levels,
    }


def _size(strategy) -> float:
    risk_pct = strategy.hp.get('risk_pct', 0.05) * 0.5
    capital = strategy.balance * risk_pct
    return max(0.001, round(capital / strategy.price, 3))


def _in_cooldown(strategy) -> bool:
    cooldown_bars = strategy.vars.get('cooldown_bars', 2)
    last_exit = strategy.vars.get('last_exit_index', -999999)
    return (strategy.index - last_exit) < cooldown_bars
