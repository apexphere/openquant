"""Donchian channel breakout behavior.

Goes long on break above the N-period high, short on break below
the N-period low. ATR-based stops. Suitable for trending/high-volatility
regimes.

Reads from strategy.hp:
    risk_pct, sl_pct, trail_pct
    donchian_period (default 20)
"""
import numpy as np
import openquant.indicators as ta


class BreakoutBehavior:
    """Donchian breakout: long on new highs, short on new lows."""

    def should_long(self, strategy) -> bool:
        if _in_cooldown(strategy):
            return False
        period = strategy.hp.get('donchian_period', 20)
        if len(strategy.candles) < period + 1:
            return False
        upper = np.max(strategy.candles[-(period + 1):-1, 3])  # highest high excluding current
        return strategy.price > upper

    def should_short(self, strategy) -> bool:
        if _in_cooldown(strategy):
            return False
        period = strategy.hp.get('donchian_period', 20)
        if len(strategy.candles) < period + 1:
            return False
        lower = np.min(strategy.candles[-(period + 1):-1, 4])  # lowest low excluding current
        return strategy.price < lower

    def go_long(self, strategy) -> None:
        qty = _size(strategy)
        strategy.buy = qty, strategy.price
        strategy.stop_loss = qty, strategy.price * (1 - strategy.hp.get('sl_pct', 0.05))
        tp = strategy.hp.get('tp_pct', 0)
        if tp > 0:
            strategy.take_profit = qty, strategy.price * (1 + tp)

    def go_short(self, strategy) -> None:
        qty = _size(strategy)
        strategy.sell = qty, strategy.price
        strategy.stop_loss = qty, strategy.price * (1 + strategy.hp.get('sl_pct', 0.05))
        tp = strategy.hp.get('tp_pct', 0)
        if tp > 0:
            strategy.take_profit = qty, strategy.price * (1 - tp)

    def update_position(self, strategy) -> None:
        trail_pct = strategy.hp.get('trail_pct', 0)
        if trail_pct <= 0:
            return
        if strategy.is_long:
            trail_price = strategy.price * (1 - trail_pct)
            if trail_price > strategy.average_stop_loss:
                strategy.stop_loss = strategy.position.qty, trail_price
        elif strategy.is_short:
            trail_price = strategy.price * (1 + trail_pct)
            if trail_price < strategy.average_stop_loss:
                strategy.stop_loss = abs(strategy.position.qty), trail_price


def _size(strategy) -> float:
    capital = strategy.balance * strategy.hp.get('risk_pct', 0.05)
    return max(0.001, round(capital / strategy.price, 3))


def _in_cooldown(strategy) -> bool:
    cooldown_bars = strategy.vars.get('cooldown_bars', 8)
    last_exit = strategy.vars.get('last_exit_index', -999999)
    return (strategy.index - last_exit) < cooldown_bars
