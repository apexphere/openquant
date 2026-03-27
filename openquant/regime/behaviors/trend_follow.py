"""Simple trend following behavior.

Goes long when price is above a moving average, short when below.
Uses ATR-based stops. Suitable for trending regimes.

Reads from strategy.hp:
    risk_pct, sl_pct, tp_pct, trail_pct
    trend_ma_period (default 50), trend_ma_type (default 'ema')
"""
import openquant.indicators as ta


class TrendFollowBehavior:
    """Trend following: long above MA, short below MA with ATR stops."""

    def should_long(self, strategy) -> bool:
        if _in_cooldown(strategy):
            return False
        ma = _get_ma(strategy)
        return strategy.price > ma

    def should_short(self, strategy) -> bool:
        if _in_cooldown(strategy):
            return False
        ma = _get_ma(strategy)
        return strategy.price < ma

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


def _get_ma(strategy):
    ma_type = strategy.hp.get('trend_ma_type', 'ema')
    period = strategy.hp.get('trend_ma_period', 50)
    if ma_type == 'sma':
        return ta.sma(strategy.candles, period=period)
    else:
        return ta.ema(strategy.candles, period=period)


def _size(strategy) -> float:
    capital = strategy.balance * strategy.hp.get('risk_pct', 0.05)
    return max(0.001, round(capital / strategy.price, 3))


def _in_cooldown(strategy) -> bool:
    cooldown_bars = strategy.vars.get('cooldown_bars', 8)
    last_exit = strategy.vars.get('last_exit_index', -999999)
    return (strategy.index - last_exit) < cooldown_bars
