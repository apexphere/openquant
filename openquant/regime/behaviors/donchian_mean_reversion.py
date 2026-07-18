"""Donchian channel mean-reversion behavior for ranging markets.

Fades the Donchian channel edges: buy at the lower channel, sell at the upper.
Unlike BB mean-reversion, Donchian uses actual high/low of last N bars — no
standard deviation, no regime-boundary lag from a moving average.

Entry:
    Long:  price touches lower channel + RSI confirms oversold
    Short: price touches upper channel + RSI confirms overbought
    Rejection required: current bar must close INSIDE the channel
    (if it closes outside, it's a breakout, not a mean-reversion setup)

Exit:
    TP: opposite channel edge (full range capture)
    SL: beyond the entry channel edge by a fraction of the channel width

Uses a configurable timeframe for the channel (default 4h) and RSI
confirmation on the same timeframe.

Reads from strategy.hp:
    dc_timeframe (default '4h'), dc_period (default 30)
    dc_rsi_period (default 14)
    dc_rsi_oversold (default 30), dc_rsi_overbought (default 70)
    dc_sl_pct (default 0.1) — SL as fraction of channel width beyond edge
    risk_pct
"""
import numpy as np
import openquant.indicators as ta


class DonchianMeanReversionBehavior:
    """Donchian mean-reversion: long at lower channel, short at upper channel.

    TP targets opposite channel edge. SL just beyond the entry edge.
    Requires RSI confirmation and price rejection (close inside channel).
    """

    def should_long(self, strategy) -> bool:
        if _in_cooldown(strategy):
            return False
        channel = _get_channel(strategy)
        if channel is None:
            return False

        lower = channel['lower']
        upper = channel['upper']
        width = upper - lower
        if width <= 0:
            return False

        # Price must be near the lower channel edge
        touch_pct = strategy.hp.get('dc_touch_zone', 0.08)
        touch_zone = width * touch_pct
        if strategy.price > lower + touch_zone:
            return False

        # Reject overly wide channels — TP too far to reach
        max_width = strategy.hp.get('dc_max_width_pct', 6.0)
        if (width / lower * 100) > max_width:
            return False

        # Price must still be INSIDE the channel (rejection, not breakout)
        if strategy.price <= lower:
            return False

        # RSI confirms oversold
        candles = _get_candles(strategy)
        rsi = ta.rsi(candles, period=strategy.hp.get('dc_rsi_period', 14))
        if float(rsi) > float(strategy.hp.get('dc_rsi_oversold', 30)):
            return False

        return True

    def should_short(self, strategy) -> bool:
        if _in_cooldown(strategy):
            return False
        channel = _get_channel(strategy)
        if channel is None:
            return False

        lower = channel['lower']
        upper = channel['upper']
        width = upper - lower
        if width <= 0:
            return False

        # Price must be near the upper channel edge
        touch_pct = strategy.hp.get('dc_touch_zone', 0.08)
        touch_zone = width * touch_pct
        if strategy.price < upper - touch_zone:
            return False

        # Reject overly wide channels
        max_width = strategy.hp.get('dc_max_width_pct', 6.0)
        if (width / lower * 100) > max_width:
            return False

        # Price must still be INSIDE the channel (rejection, not breakout)
        if strategy.price >= upper:
            return False

        # RSI confirms overbought
        candles = _get_candles(strategy)
        rsi = ta.rsi(candles, period=strategy.hp.get('dc_rsi_period', 14))
        if float(rsi) < float(strategy.hp.get('dc_rsi_overbought', 70)):
            return False

        return True

    def go_long(self, strategy) -> None:
        channel = _get_channel(strategy)
        qty = _size(strategy)
        width = channel['upper'] - channel['lower']
        sl_pct = strategy.hp.get('dc_sl_pct', 0.1)

        strategy.buy = qty, strategy.price
        # SL: just below the lower channel edge
        strategy.stop_loss = qty, channel['lower'] - (width * sl_pct)
        # TP: upper channel edge (full range capture)
        strategy.take_profit = qty, channel['upper']

    def go_short(self, strategy) -> None:
        channel = _get_channel(strategy)
        qty = _size(strategy)
        width = channel['upper'] - channel['lower']
        sl_pct = strategy.hp.get('dc_sl_pct', 0.1)

        strategy.sell = qty, strategy.price
        # SL: just above the upper channel edge
        strategy.stop_loss = qty, channel['upper'] + (width * sl_pct)
        # TP: lower channel edge
        strategy.take_profit = qty, channel['lower']

    def trace(self, strategy) -> dict:
        channel = _get_channel(strategy)
        if channel is None:
            return {'error': 'insufficient data'}

        candles = _get_candles(strategy)
        rsi = ta.rsi(candles, period=strategy.hp.get('dc_rsi_period', 14))
        width = channel['upper'] - channel['lower']

        return {
            'channel_high': round(float(channel['upper']), 2),
            'channel_low': round(float(channel['lower']), 2),
            'channel_mid': round(float(channel['mid']), 2),
            'channel_width_pct': round(float(width) / float(channel['lower']) * 100, 2),
            'rsi': round(float(rsi), 2),
            'price_position_pct': round(
                (strategy.price - float(channel['lower'])) / float(width) * 100, 1),
            'price_in_channel': bool(
                float(channel['lower']) < strategy.price < float(channel['upper'])),
            'rsi_oversold': bool(
                float(rsi) <= float(strategy.hp.get('dc_rsi_oversold', 30))),
            'rsi_overbought': bool(
                float(rsi) >= float(strategy.hp.get('dc_rsi_overbought', 70))),
        }

    def update_position(self, strategy) -> None:
        pass  # Fixed TP/SL — no trailing in ranges


def _get_candles(strategy):
    tf = strategy.hp.get('dc_timeframe', '4h')
    return strategy.get_candles(strategy.exchange, strategy.symbol, tf)


def _get_channel(strategy):
    """Compute Donchian channel from actual high/low of last N bars."""
    candles = _get_candles(strategy)
    period = strategy.hp.get('dc_period', 30)

    if candles is None or len(candles) < period + 2:
        return None

    # Use completed bars only (exclude current in-progress bar)
    highs = candles[-(period + 1):-1, 3]
    lows = candles[-(period + 1):-1, 4]
    upper = float(np.max(highs))
    lower = float(np.min(lows))
    mid = (upper + lower) / 2

    return {'upper': upper, 'lower': lower, 'mid': mid}


def _size(strategy) -> float:
    capital = strategy.balance * strategy.hp.get('risk_pct', 0.05)
    return max(0.001, round(capital / strategy.price, 3))


def _in_cooldown(strategy) -> bool:
    cooldown_bars = strategy.vars.get('cooldown_bars', 4)
    last_exit = strategy.vars.get('last_exit_index', -999999)
    return (strategy.index - last_exit) < cooldown_bars
