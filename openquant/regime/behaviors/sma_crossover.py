"""SMA crossover behavior for trending regimes.

Goes long on SMA 20/50 golden cross, exits on death cross.
Uses ATR-based stops and trailing. Designed for 4h timeframe.

Reads from strategy.hp:
    sma_fast (default 20), sma_slow (default 50)
    atr_period (default 14), atr_sl_mult (default 3.0), atr_trail_mult (default 4.0)
    risk_pct (default 0.02)
"""
import openquant.indicators as ta


class SmaCrossoverBehavior:
    """SMA 20/50 crossover: long on golden cross, exit on death cross."""

    def should_long(self, strategy) -> bool:
        if _in_cooldown(strategy):
            return False
        return _sma_cross(strategy) == 'golden'

    def should_short(self, strategy) -> bool:
        if _in_cooldown(strategy):
            return False
        return _sma_cross(strategy) == 'death'

    def go_long(self, strategy) -> None:
        atr = ta.atr(strategy.candles, period=strategy.hp.get('atr_period', 14))
        sl_distance = atr * strategy.hp.get('atr_sl_mult', 3.0)
        qty = _size(strategy, sl_distance)
        strategy.buy = qty, strategy.price
        strategy.stop_loss = qty, strategy.price - sl_distance

    def go_short(self, strategy) -> None:
        atr = ta.atr(strategy.candles, period=strategy.hp.get('atr_period', 14))
        sl_distance = atr * strategy.hp.get('atr_sl_mult', 3.0)
        qty = _size(strategy, sl_distance)
        strategy.sell = qty, strategy.price
        strategy.stop_loss = qty, strategy.price + sl_distance

    def update_position(self, strategy) -> None:
        if not strategy.is_long and not strategy.is_short:
            return

        atr = ta.atr(strategy.candles, period=strategy.hp.get('atr_period', 14))
        trail_distance = atr * strategy.hp.get('atr_trail_mult', 4.0)

        sma_fast = ta.sma(strategy.candles, period=strategy.hp.get('sma_fast', 20))
        sma_slow = ta.sma(strategy.candles, period=strategy.hp.get('sma_slow', 50))

        if strategy.is_long:
            new_sl = strategy.price - trail_distance
            if new_sl > strategy.average_stop_loss:
                strategy.stop_loss = strategy.position.qty, new_sl
            if sma_fast < sma_slow:
                strategy.liquidate()

        elif strategy.is_short:
            new_sl = strategy.price + trail_distance
            if new_sl < strategy.average_stop_loss:
                strategy.stop_loss = abs(strategy.position.qty), new_sl
            if sma_fast > sma_slow:
                strategy.liquidate()

    def trace(self, strategy) -> dict:
        sma_fast = ta.sma(strategy.candles, period=strategy.hp.get('sma_fast', 20))
        sma_slow = ta.sma(strategy.candles, period=strategy.hp.get('sma_slow', 50))
        return {
            'sma_fast': round(float(sma_fast), 2),
            'sma_slow': round(float(sma_slow), 2),
            'sma_spread_pct': round((sma_fast - sma_slow) / sma_slow * 100, 3),
            'cross': _sma_cross(strategy),
        }


def _sma_cross(strategy) -> str:
    """Detect SMA crossover using previous bar comparison."""
    fast_period = strategy.hp.get('sma_fast', 20)
    slow_period = strategy.hp.get('sma_slow', 50)

    candles = strategy.candles
    if len(candles) < slow_period + 2:
        return 'none'

    sma_fast_now = ta.sma(candles, period=fast_period)
    sma_slow_now = ta.sma(candles, period=slow_period)

    # Use previous candle's values for crossover detection
    candles_prev = candles[:-1]
    if len(candles_prev) < slow_period + 1:
        return 'none'

    sma_fast_prev = ta.sma(candles_prev, period=fast_period)
    sma_slow_prev = ta.sma(candles_prev, period=slow_period)

    if sma_fast_prev <= sma_slow_prev and sma_fast_now > sma_slow_now:
        return 'golden'
    if sma_fast_prev >= sma_slow_prev and sma_fast_now < sma_slow_now:
        return 'death'
    return 'none'


def _size(strategy, sl_distance: float) -> float:
    risk_amount = strategy.balance * strategy.hp.get('risk_pct', 0.02)
    if sl_distance <= 0:
        return 0.001
    qty = risk_amount / sl_distance
    max_qty = (strategy.available_margin * 0.95) / strategy.price
    qty = min(qty, max_qty)
    return max(0.001, round(qty, 3))


def _in_cooldown(strategy) -> bool:
    cooldown_bars = strategy.vars.get('cooldown_bars', 6)
    last_exit = strategy.vars.get('last_exit_index', -999999)
    return (strategy.index - last_exit) < cooldown_bars
