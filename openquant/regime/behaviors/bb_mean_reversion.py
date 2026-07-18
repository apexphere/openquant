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
        # Only long in ranging-up — don't catch falling knives in ranging-down
        regime = getattr(strategy, '_current_regime', None)
        if regime == 'ranging-down':
            return False
        bb = _get_bb(strategy)
        # Skip when bands are too narrow — stop loss will exceed band width
        if not _bands_wide_enough(bb, strategy):
            return False
        if strategy.price > bb[2]:
            return False
        candles = _get_candles(strategy)
        rsi = ta.rsi(candles, period=strategy.hp.get('rsi_period', 14))
        if rsi > strategy.hp.get('rsi_oversold', 35):
            return False
        return True

    def should_short(self, strategy) -> bool:
        if _in_cooldown(strategy):
            return False
        # Only short in ranging-down — don't short rallies in ranging-up
        regime = getattr(strategy, '_current_regime', None)
        if regime == 'ranging-up':
            return False
        bb = _get_bb(strategy)
        # Skip when bands are too narrow — stop loss will exceed band width
        if not _bands_wide_enough(bb, strategy):
            return False
        if strategy.price < bb[1]:
            return False
        candles = _get_candles(strategy)
        rsi = ta.rsi(candles, period=strategy.hp.get('rsi_period', 14))
        if rsi < strategy.hp.get('rsi_overbought', 65):
            return False
        return True

    def go_long(self, strategy) -> None:
        bb = _get_bb(strategy)
        qty = _size(strategy)

        # SL: just below the lower band (range is breaking)
        band_width = float(bb[1] - bb[2])
        sl_offset = band_width * strategy.hp.get('bb_sl_band_pct', 0.1)

        strategy.buy = qty, strategy.price
        strategy.stop_loss = qty, float(bb[2]) - sl_offset
        # TP: upper band (full range capture, not just middle)
        strategy.take_profit = qty, float(bb[1])

    def go_short(self, strategy) -> None:
        bb = _get_bb(strategy)
        qty = _size(strategy)

        # SL: just above the upper band (range is breaking)
        band_width = float(bb[1] - bb[2])
        sl_offset = band_width * strategy.hp.get('bb_sl_band_pct', 0.1)

        strategy.sell = qty, strategy.price
        strategy.stop_loss = qty, float(bb[1]) + sl_offset
        # TP: lower band (full range capture)
        strategy.take_profit = qty, float(bb[2])

    def trace(self, strategy) -> dict:
        bb = _get_bb(strategy)
        candles = _get_candles(strategy)
        rsi = ta.rsi(candles, period=strategy.hp.get('rsi_period', 14))
        band_width_pct = round(float(bb[1] - bb[2]) / float(bb[2]) * 100, 3)
        return {
            'bb_upper': round(float(bb[1]), 2),
            'bb_middle': round(float(bb[0]), 2),
            'bb_lower': round(float(bb[2]), 2),
            'band_width_pct': band_width_pct,
            'rsi': round(float(rsi), 2),
            'price_vs_bb_lower_pct': round(
                (strategy.price - float(bb[2])) / float(bb[2]) * 100, 3),
            'price_vs_bb_upper_pct': round(
                (strategy.price - float(bb[1])) / float(bb[1]) * 100, 3),
            'bands_wide_enough': bool(_bands_wide_enough(bb, strategy)),
            'price_at_lower': bool(float(strategy.price) <= float(bb[2])),
            'price_at_upper': bool(float(strategy.price) >= float(bb[1])),
            'rsi_oversold': bool(float(rsi) <= float(strategy.hp.get('rsi_oversold', 35))),
            'rsi_overbought': bool(float(rsi) >= float(strategy.hp.get('rsi_overbought', 65))),
        }

    def update_position(self, strategy) -> None:
        pass  # Fixed TP/SL — no trailing in ranges


def _bands_wide_enough(bb, strategy) -> bool:
    """Reject entries when BB bands are narrower than the stop loss.

    When band width < 2x the SL percentage, the stop will be hit before
    price can reach the middle band target. This filters out compressed
    ranges where mean-reversion has no edge.
    """
    band_width_pct = float(bb[1] - bb[2]) / float(bb[2]) * 100
    sl_pct = float(strategy.hp.get('bb_sl_pct', 0.02)) * 100
    min_width = float(strategy.hp.get('bb_min_width_pct', sl_pct * 2))
    return band_width_pct >= min_width


def _get_candles(strategy):
    """Get candles for BB calculation — uses bb_timeframe if set, else route timeframe."""
    tf = strategy.hp.get('bb_timeframe', None)
    if tf:
        return strategy.get_candles(strategy.exchange, strategy.symbol, tf)
    return strategy.candles


def _get_rsi_candles(strategy):
    """Get candles for RSI — uses bb_rsi_timeframe if set, else route timeframe.

    BB and RSI often need different timeframes: BB on 1D for range structure,
    RSI on 4h for entry timing. Daily RSI is too smooth to reach extremes.
    """
    tf = strategy.hp.get('bb_rsi_timeframe', None)
    if tf:
        return strategy.get_candles(strategy.exchange, strategy.symbol, tf)
    return strategy.candles


def _get_bb(strategy):
    return ta.bollinger_bands(
        _get_candles(strategy),
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
