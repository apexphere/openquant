"""Trend pullback behavior for trending markets.

In a confirmed uptrend (regime already detected), waits for price to
pull back to the fast EMA, then enters long when price bounces back
above it. The pullback creates a better entry price and the bounce
confirms buyers are still in control.

Entry (long):
    1. Price touches or dips below the fast EMA (pullback)
    2. Price closes back above the fast EMA (bounce confirmation)
    3. RSI is not overbought (avoid chasing)

Exit:
    - ATR-based stop loss (2x ATR below entry)
    - Trailing stop that widens with profit (ATR-based)
    - No fixed take-profit — let trends run

Reads from strategy.hp:
    risk_pct, trail_pct
    pb_fast_ema (default 13), pb_slow_ema (default 34)
    pb_rsi_period (default 14), pb_rsi_max (default 70)
    pb_atr_period (default 14), pb_atr_sl_mult (default 2.0)
"""
import numpy as np
import openquant.indicators as ta


class TrendPullbackBehavior:
    """Long pullback entries in trending-up markets.

    Entry: price pulled back to fast EMA and bounced.
    Stop: ATR-based, trails with profit.
    No fixed TP — let trends run.
    """

    def should_long(self, strategy) -> bool:
        if _in_cooldown(strategy):
            return False

        fast_period = strategy.hp.get('pb_fast_ema', 13)
        slow_period = strategy.hp.get('pb_slow_ema', 34)
        rsi_period = strategy.hp.get('pb_rsi_period', 14)
        rsi_max = strategy.hp.get('pb_rsi_max', 70)

        # Use 4h candles for pullback detection (15m is too noisy)
        candles_4h = strategy.get_candles(strategy.exchange, strategy.symbol, strategy.hp.get('pb_timeframe', '4h'))
        if candles_4h is None or len(candles_4h) < slow_period + 5:
            return False

        fast_ema = ta.ema(candles_4h, period=fast_period, sequential=True)
        slow_ema = ta.ema(candles_4h, period=slow_period, sequential=True)
        rsi = ta.rsi(candles_4h, period=rsi_period)

        # Trend structure: fast EMA above slow EMA (confirmed uptrend)
        if fast_ema[-1] <= slow_ema[-1]:
            return False

        # Current 4h bar closes above fast EMA (bounce confirmed)
        if candles_4h[-1, 2] <= fast_ema[-1]:
            return False

        # Previous 4h bar's low touched or dipped below fast EMA (the pullback)
        if candles_4h[-2, 4] > fast_ema[-2]:
            return False

        # RSI not overbought
        if rsi > rsi_max:
            return False

        return True

    def should_short(self, strategy) -> bool:
        return False

    def go_long(self, strategy) -> None:
        atr_period = strategy.hp.get('pb_atr_period', 14)
        atr_mult = strategy.hp.get('pb_atr_sl_mult', 2.0)

        # Use 4h ATR for stop sizing (matches entry timeframe)
        candles_4h = strategy.get_candles(strategy.exchange, strategy.symbol, strategy.hp.get('pb_timeframe', '4h'))
        atr = ta.atr(candles_4h, period=atr_period)
        qty = _size(strategy)

        strategy.buy = qty, strategy.price
        strategy.stop_loss = qty, strategy.price - (atr * atr_mult)
        # No fixed take-profit — trailing stop lets trends run

    def go_short(self, strategy) -> None:
        pass

    def update_position(self, strategy) -> None:
        if not strategy.is_long:
            return

        atr_period = strategy.hp.get('pb_atr_period', 14)
        trail_pct = strategy.hp.get('trail_pct', 0.03)

        candles_4h = strategy.get_candles(strategy.exchange, strategy.symbol, strategy.hp.get('pb_timeframe', '4h'))
        atr = ta.atr(candles_4h, period=atr_period)

        # Trail stop: max of percentage-based and ATR-based
        pct_trail = strategy.price * (1 - trail_pct)
        atr_trail = strategy.price - (atr * 1.5)
        trail_price = max(pct_trail, atr_trail)

        if trail_price > strategy.average_stop_loss:
            strategy.stop_loss = strategy.position.qty, trail_price


def _size(strategy) -> float:
    capital = strategy.balance * strategy.hp.get('risk_pct', 0.05)
    return max(0.001, round(capital / strategy.price, 3))


def _in_cooldown(strategy) -> bool:
    cooldown_bars = strategy.vars.get('cooldown_bars', 8)
    last_exit = strategy.vars.get('last_exit_index', -999999)
    return (strategy.index - last_exit) < cooldown_bars
