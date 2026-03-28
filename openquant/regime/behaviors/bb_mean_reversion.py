"""Bollinger Band mean-reversion behavior for ranging markets.

Quick in, quick out. Fades BB band extremes in ranges.

Entry:
    Long:  price touches lower band + RSI confirms oversold
    Short: price touches upper band + RSI confirms overbought

Exit:
    TP: opposite band (full range capture)
    SL: just outside the entry band (range is breaking)

Operates on the route timeframe (15m) for fast reaction.
No trailing stop — mean-reversion targets are fixed.

Reads from strategy.hp:
    bb_window (default 20), bb_mult (default 2.0)
    rsi_period (default 14), rsi_oversold (default 35), rsi_overbought (default 65)
    bb_sl_pct (default 0.01), risk_pct
"""
import numpy as np
import openquant.indicators as ta


class BBMeanReversionBehavior:
    """BB mean-reversion: long at lower band, short at upper band.

    TP targets opposite band. SL just outside entry band.
    """

    def should_long(self, strategy) -> bool:
        if _in_cooldown(strategy):
            return False
        bb = _get_bb(strategy)
        # Price at or below lower band
        if strategy.price > bb[2]:
            return False
        # RSI confirms oversold
        rsi = ta.rsi(strategy.candles, period=strategy.hp.get('rsi_period', 14))
        if rsi > strategy.hp.get('rsi_oversold', 35):
            return False
        return True

    def should_short(self, strategy) -> bool:
        if _in_cooldown(strategy):
            return False
        bb = _get_bb(strategy)
        # Price at or above upper band
        if strategy.price < bb[1]:
            return False
        # RSI confirms overbought
        rsi = ta.rsi(strategy.candles, period=strategy.hp.get('rsi_period', 14))
        if rsi < strategy.hp.get('rsi_overbought', 65):
            return False
        return True

    def go_long(self, strategy) -> None:
        bb = _get_bb(strategy)
        qty = _size(strategy)

        strategy.buy = qty, strategy.price
        # SL: below the lower band — if price breaks the band, range is over
        strategy.stop_loss = qty, bb[2] * (1 - strategy.hp.get('bb_sl_pct', 0.005))
        # TP: middle band (SMA) — quick, reliable target
        strategy.take_profit = qty, bb[0]

    def go_short(self, strategy) -> None:
        bb = _get_bb(strategy)
        qty = _size(strategy)

        strategy.sell = qty, strategy.price
        # SL: above the upper band
        strategy.stop_loss = qty, bb[1] * (1 + strategy.hp.get('bb_sl_pct', 0.005))
        # TP: middle band (SMA)
        strategy.take_profit = qty, bb[0]

    def update_position(self, strategy) -> None:
        pass  # Fixed TP/SL — no trailing in ranges


def _get_bb(strategy):
    return ta.bollinger_bands(
        strategy.candles,
        period=strategy.hp.get('bb_window', 20),
        devup=strategy.hp.get('bb_mult', 2.0),
        devdn=strategy.hp.get('bb_mult', 2.0),
    )


def _size(strategy) -> float:
    capital = strategy.balance * strategy.hp.get('risk_pct', 0.05)
    return max(0.001, round(capital / strategy.price, 3))


def _in_cooldown(strategy) -> bool:
    cooldown_bars = strategy.vars.get('cooldown_bars', 4)
    last_exit = strategy.vars.get('last_exit_index', -999999)
    return (strategy.index - last_exit) < cooldown_bars
