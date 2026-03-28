"""Donchian channel breakout behavior for trend starts.

Enters long on break above N-period high, short on break below N-period
low. Catches the first move of a new trend that pullback misses.

Uses a configurable timeframe for the Donchian channel (default 4h) to
avoid noise from shorter timeframes. ATR-based stops adapt to volatility.

Entry:
    Long:  price breaks above the highest high of last N bars (on bo_timeframe)
    Short: price breaks below the lowest low of last N bars (on bo_timeframe)

Exit:
    SL: ATR-based (configurable multiplier)
    Trailing stop: percentage-based
    No fixed TP — let breakout trends run

Reads from strategy.hp:
    bo_timeframe (default '4h'), bo_period (default 20)
    bo_atr_period (default 14), bo_atr_sl_mult (default 2.0)
    risk_pct, trail_pct
"""
import numpy as np
import openquant.indicators as ta


class BreakoutBehavior:
    """Donchian breakout: long on new highs, short on new lows.

    Uses higher timeframe for channel to filter noise.
    ATR-based stops. Trailing stop lets trends run.
    """

    def should_long(self, strategy) -> bool:
        if _in_cooldown(strategy):
            return False
        candles = _get_candles(strategy)
        period = strategy.hp.get('bo_period', 20)
        if candles is None or len(candles) < period + 2:
            return False
        # Highest high of completed bars (exclude current in-progress bar)
        upper = np.max(candles[-(period + 1):-1, 3])
        return strategy.price > upper

    def should_short(self, strategy) -> bool:
        if _in_cooldown(strategy):
            return False
        candles = _get_candles(strategy)
        period = strategy.hp.get('bo_period', 20)
        if candles is None or len(candles) < period + 2:
            return False
        # Lowest low of completed bars
        lower = np.min(candles[-(period + 1):-1, 4])
        return strategy.price < lower

    def go_long(self, strategy) -> None:
        candles = _get_candles(strategy)
        atr_period = strategy.hp.get('bo_atr_period', 14)
        atr_mult = strategy.hp.get('bo_atr_sl_mult', 2.0)
        atr = ta.atr(candles, period=atr_period)
        qty = _size(strategy)

        strategy.buy = qty, strategy.price
        strategy.stop_loss = qty, strategy.price - (atr * atr_mult)

    def go_short(self, strategy) -> None:
        candles = _get_candles(strategy)
        atr_period = strategy.hp.get('bo_atr_period', 14)
        atr_mult = strategy.hp.get('bo_atr_sl_mult', 2.0)
        atr = ta.atr(candles, period=atr_period)
        qty = _size(strategy)

        strategy.sell = qty, strategy.price
        strategy.stop_loss = qty, strategy.price + (atr * atr_mult)

    def update_position(self, strategy) -> None:
        trail_pct = strategy.hp.get('trail_pct', 0.03)
        if strategy.is_long:
            trail_price = strategy.price * (1 - trail_pct)
            if trail_price > strategy.average_stop_loss:
                strategy.stop_loss = strategy.position.qty, trail_price
        elif strategy.is_short:
            trail_price = strategy.price * (1 + trail_pct)
            if trail_price < strategy.average_stop_loss:
                strategy.stop_loss = abs(strategy.position.qty), trail_price


def _get_candles(strategy):
    tf = strategy.hp.get('bo_timeframe', '4h')
    return strategy.get_candles(strategy.exchange, strategy.symbol, tf)


def _size(strategy) -> float:
    capital = strategy.balance * strategy.hp.get('risk_pct', 0.05)
    return max(0.001, round(capital / strategy.price, 3))


def _in_cooldown(strategy) -> bool:
    cooldown_bars = strategy.vars.get('cooldown_bars', 8)
    last_exit = strategy.vars.get('last_exit_index', -999999)
    return (strategy.index - last_exit) < cooldown_bars
