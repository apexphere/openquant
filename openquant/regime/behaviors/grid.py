"""Grid trading behavior for ranging markets.

Places buy/sell orders at fixed price intervals (grid levels) within
a detected range. Profits from price oscillation without predicting
direction. Each trade targets the next grid level as TP.

Grid levels are computed from Bollinger Bands:
    upper_bound = upper BB band
    lower_bound = lower BB band
    grid_step = (upper - lower) / num_grids

Entry:
    Long:  price at or below a grid buy level + below middle band
    Short: price at or above a grid sell level + above middle band

Exit:
    TP: next grid level (one step profit)
    SL: beyond the range boundary (range is breaking)

Operates on route timeframe (15m) for fast oscillation capture.

Reads from strategy.hp:
    grid_bb_window (default 34), grid_bb_mult (default 2.0)
    grid_num_levels (default 5), grid_sl_pct (default 0.02)
    risk_pct
"""
import numpy as np
import openquant.indicators as ta


class GridBehavior:
    """Grid trading: buy at lower grid levels, sell at upper grid levels.

    Each trade targets one grid step of profit. Many small wins.
    """

    def should_long(self, strategy) -> bool:
        if _in_cooldown(strategy):
            return False
        bb = _get_bb(strategy)
        mid = bb[0]
        # Only buy below the middle band
        if strategy.price >= mid:
            return False
        # Check if price is at or below a grid buy level
        grid = _get_grid_levels(strategy, bb)
        for level in grid['buy_levels']:
            if strategy.price <= level:
                return True
        return False

    def should_short(self, strategy) -> bool:
        if _in_cooldown(strategy):
            return False
        bb = _get_bb(strategy)
        mid = bb[0]
        # Only sell above the middle band
        if strategy.price <= mid:
            return False
        # Check if price is at or above a grid sell level
        grid = _get_grid_levels(strategy, bb)
        for level in grid['sell_levels']:
            if strategy.price >= level:
                return True
        return False

    def go_long(self, strategy) -> None:
        grid = _get_grid_levels(strategy, _get_bb(strategy))
        qty = _size(strategy)
        step = grid['step']
        sl_mult = strategy.hp.get('grid_sl_mult', 1.5)

        strategy.buy = qty, strategy.price
        # SL: 1.5 grid steps below entry (not full range)
        strategy.stop_loss = qty, strategy.price - (step * sl_mult)
        # TP: one grid step above entry
        strategy.take_profit = qty, strategy.price + step

    def go_short(self, strategy) -> None:
        grid = _get_grid_levels(strategy, _get_bb(strategy))
        qty = _size(strategy)
        step = grid['step']
        sl_mult = strategy.hp.get('grid_sl_mult', 1.5)

        strategy.sell = qty, strategy.price
        # SL: 1.5 grid steps above entry
        strategy.stop_loss = qty, strategy.price + (step * sl_mult)
        # TP: one grid step below entry
        strategy.take_profit = qty, strategy.price - step

    def update_position(self, strategy) -> None:
        pass  # Fixed TP/SL per trade — no trailing


def _get_bb(strategy):
    return ta.bollinger_bands(
        strategy.candles,
        period=strategy.hp.get('grid_bb_window', 34),
        devup=strategy.hp.get('grid_bb_mult', 2.0),
        devdn=strategy.hp.get('grid_bb_mult', 2.0),
    )


def _get_grid_levels(strategy, bb):
    """Compute grid price levels from BB bands."""
    upper = bb[1]  # upper band
    lower = bb[2]  # lower band
    mid = bb[0]    # middle band (SMA)
    num_levels = strategy.hp.get('grid_num_levels', 5)

    total_range = upper - lower
    step = total_range / (num_levels + 1)

    # Buy levels: below mid, from mid down to lower band
    buy_levels = [mid - step * i for i in range(1, num_levels // 2 + 2)]
    # Sell levels: above mid, from mid up to upper band
    sell_levels = [mid + step * i for i in range(1, num_levels // 2 + 2)]

    return {
        'buy_levels': buy_levels,
        'sell_levels': sell_levels,
        'step': step,
        'upper': upper,
        'lower': lower,
        'mid': mid,
    }


def _size(strategy) -> float:
    # Smaller position size for grid trades (many simultaneous small bets)
    risk_pct = strategy.hp.get('risk_pct', 0.05) * 0.5  # half size per grid trade
    capital = strategy.balance * risk_pct
    return max(0.001, round(capital / strategy.price, 3))


def _in_cooldown(strategy) -> bool:
    cooldown_bars = strategy.vars.get('cooldown_bars', 2)  # shorter cooldown for grid
    last_exit = strategy.vars.get('last_exit_index', -999999)
    return (strategy.index - last_exit) < cooldown_bars
