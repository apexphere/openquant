"""Micro-trend behavior for ranging markets.

Same logic as trend pullback, but on a faster scale. Inside a range,
price makes mini-trends (up-swings and down-swings). Instead of fading
the range edges (mean-reversion), we ride these micro-trends.

Uses shorter EMA periods and a faster timeframe than the macro
pullback behaviors. Entries on pullbacks within micro-trends,
exits via tight trailing stops.

Entry (long):
    1. Fast EMA above slow EMA on the micro timeframe (micro-uptrend)
    2. Previous bar touched fast EMA (pullback)
    3. Current bar bounced above fast EMA (confirmation)
    4. RSI not overbought

Entry (short): mirror of long.

This is the fractal principle: trending behavior works at any scale.
The same pullback logic that works for macro bullish/bearish regimes
works for micro-trends within ranging regimes.

Reads from strategy.hp:
    mt_timeframe (default '1h'), mt_fast_ema (default 8), mt_slow_ema (default 21)
    mt_rsi_period (default 14), mt_rsi_max (default 65), mt_rsi_min (default 35)
    mt_atr_period (default 14), mt_atr_sl_mult (default 1.5)
    mt_min_ema_spread (default 0.1)
    risk_pct, trail_pct
"""
import openquant.indicators as ta


class MicroTrendBehavior:
    """Micro-trend following within ranges.

    Rides short-lived trends inside a ranging regime using fast EMAs.
    Both long and short — captures both up-swings and down-swings.
    """

    def should_long(self, strategy) -> bool:
        if _in_cooldown(strategy):
            return False

        candles = _get_candles(strategy)
        if candles is None or len(candles) < strategy.hp.get('mt_slow_ema', 21) + 5:
            return False

        fast_ema = ta.ema(candles, period=strategy.hp.get('mt_fast_ema', 8), sequential=True)
        slow_ema = ta.ema(candles, period=strategy.hp.get('mt_slow_ema', 21), sequential=True)
        rsi = ta.rsi(candles, period=strategy.hp.get('mt_rsi_period', 14))

        # Micro-uptrend: fast EMA above slow EMA
        if fast_ema[-1] <= slow_ema[-1]:
            return False

        # Minimum trend strength
        spread_pct = (float(fast_ema[-1]) - float(slow_ema[-1])) / float(slow_ema[-1]) * 100
        if spread_pct < strategy.hp.get('mt_min_ema_spread', 0.1):
            return False

        # Pullback: previous bar touched fast EMA
        if candles[-2, 4] > fast_ema[-2]:  # low didn't reach EMA
            return False

        # Bounce: current bar closes above fast EMA
        if candles[-1, 2] <= fast_ema[-1]:
            return False

        # RSI not overbought
        if rsi > strategy.hp.get('mt_rsi_max', 65):
            return False

        return True

    def should_short(self, strategy) -> bool:
        if _in_cooldown(strategy):
            return False

        candles = _get_candles(strategy)
        if candles is None or len(candles) < strategy.hp.get('mt_slow_ema', 21) + 5:
            return False

        fast_ema = ta.ema(candles, period=strategy.hp.get('mt_fast_ema', 8), sequential=True)
        slow_ema = ta.ema(candles, period=strategy.hp.get('mt_slow_ema', 21), sequential=True)
        rsi = ta.rsi(candles, period=strategy.hp.get('mt_rsi_period', 14))

        # Micro-downtrend: fast EMA below slow EMA
        if fast_ema[-1] >= slow_ema[-1]:
            return False

        # Minimum trend strength
        spread_pct = (float(slow_ema[-1]) - float(fast_ema[-1])) / float(slow_ema[-1]) * 100
        if spread_pct < strategy.hp.get('mt_min_ema_spread', 0.1):
            return False

        # Rally: previous bar's high touched fast EMA
        if candles[-2, 3] < fast_ema[-2]:
            return False

        # Rejection: current bar closes below fast EMA
        if candles[-1, 2] >= fast_ema[-1]:
            return False

        # RSI not oversold
        if rsi < strategy.hp.get('mt_rsi_min', 35):
            return False

        return True

    def go_long(self, strategy) -> None:
        candles = _get_candles(strategy)
        atr = ta.atr(candles, period=strategy.hp.get('mt_atr_period', 14))
        sl_mult = strategy.hp.get('mt_atr_sl_mult', 1.5)
        qty = _size(strategy)

        strategy.buy = qty, strategy.price
        strategy.stop_loss = qty, strategy.price - (float(atr) * sl_mult)

    def go_short(self, strategy) -> None:
        candles = _get_candles(strategy)
        atr = ta.atr(candles, period=strategy.hp.get('mt_atr_period', 14))
        sl_mult = strategy.hp.get('mt_atr_sl_mult', 1.5)
        qty = _size(strategy)

        strategy.sell = qty, strategy.price
        strategy.stop_loss = qty, strategy.price + (float(atr) * sl_mult)

    def update_position(self, strategy) -> None:
        trail_pct = strategy.hp.get('trail_pct', 0.03)
        candles = _get_candles(strategy)
        atr = ta.atr(candles, period=strategy.hp.get('mt_atr_period', 14))

        if strategy.is_long:
            pct_trail = strategy.price * (1 - trail_pct)
            atr_trail = strategy.price - (float(atr) * 1.0)
            trail_price = max(pct_trail, atr_trail)
            if trail_price > strategy.average_stop_loss:
                strategy.stop_loss = strategy.position.qty, trail_price
        elif strategy.is_short:
            pct_trail = strategy.price * (1 + trail_pct)
            atr_trail = strategy.price + (float(atr) * 1.0)
            trail_price = min(pct_trail, atr_trail)
            if trail_price < strategy.average_stop_loss:
                strategy.stop_loss = abs(strategy.position.qty), trail_price

    def trace(self, strategy) -> dict:
        candles = _get_candles(strategy)
        fast_ema = ta.ema(candles, period=strategy.hp.get('mt_fast_ema', 8), sequential=True)
        slow_ema = ta.ema(candles, period=strategy.hp.get('mt_slow_ema', 21), sequential=True)
        rsi = ta.rsi(candles, period=strategy.hp.get('mt_rsi_period', 14))
        atr = ta.atr(candles, period=strategy.hp.get('mt_atr_period', 14))

        fast_val = float(fast_ema[-1])
        slow_val = float(slow_ema[-1])
        spread = abs(fast_val - slow_val) / slow_val * 100
        direction = 'up' if fast_val > slow_val else 'down'

        return {
            'fast_ema': round(fast_val, 2),
            'slow_ema': round(slow_val, 2),
            'rsi': round(float(rsi), 2),
            'atr': round(float(atr), 2),
            'ema_spread_pct': round(spread, 3),
            'micro_trend': direction,
            'price_vs_fast_ema_pct': round(
                (strategy.price - fast_val) / fast_val * 100, 3),
            'prev_touched_ema': bool(
                float(candles[-2, 4]) <= fast_val if direction == 'up'
                else float(candles[-2, 3]) >= fast_val),
        }


def _get_candles(strategy):
    tf = strategy.hp.get('mt_timeframe', '1h')
    return strategy.get_candles(strategy.exchange, strategy.symbol, tf)


def _size(strategy) -> float:
    capital = strategy.balance * strategy.hp.get('risk_pct', 0.05)
    return max(0.001, round(capital / strategy.price, 3))


def _in_cooldown(strategy) -> bool:
    cooldown_bars = strategy.vars.get('cooldown_bars', 4)
    last_exit = strategy.vars.get('last_exit_index', -999999)
    return (strategy.index - last_exit) < cooldown_bars
