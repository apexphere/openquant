"""Bollinger Band mean-reversion behavior for ranging markets.

Extracted from RegimeRouter's ranging-regime logic. Fades BB band extremes
with RSI + volume confirmation. Trailing stop only exit (no mid-band).

Used as a sub-behavior in composite strategies:
    regimes = {
        'ranging-up': BBMeanReversionBehavior,
        'ranging-down': BBMeanReversionBehavior,
    }
"""
import numpy as np
import openquant.indicators as ta


class BBMeanReversionBehavior:
    """BB mean-reversion: long below lower band, short above upper band.

    Reads hyperparameters from the parent strategy's self.hp dict:
        bb_window, bb_mult, rsi_period, rsi_oversold, rsi_overbought,
        vol_mult, risk_pct, sl_pct, tp_pct, trail_pct
    """

    def should_long(self, strategy) -> bool:
        if _in_cooldown(strategy):
            return False
        bb = ta.bollinger_bands(strategy.candles, period=strategy.hp['bb_window'],
                                 devup=strategy.hp['bb_mult'], devdn=strategy.hp['bb_mult'])
        if strategy.price >= bb[2]:  # above lower band
            return False
        if ta.rsi(strategy.candles, period=strategy.hp['rsi_period']) > strategy.hp['rsi_oversold']:
            return False
        if not _volume_spike(strategy):
            return False
        return True

    def should_short(self, strategy) -> bool:
        if _in_cooldown(strategy):
            return False
        bb = ta.bollinger_bands(strategy.candles, period=strategy.hp['bb_window'],
                                 devup=strategy.hp['bb_mult'], devdn=strategy.hp['bb_mult'])
        if strategy.price <= bb[1]:  # below upper band
            return False
        if ta.rsi(strategy.candles, period=strategy.hp['rsi_period']) < strategy.hp['rsi_overbought']:
            return False
        if not _volume_spike(strategy):
            return False
        return True

    def go_long(self, strategy) -> None:
        bb = ta.bollinger_bands(strategy.candles, period=strategy.hp['bb_window'],
                                 devup=strategy.hp['bb_mult'], devdn=strategy.hp['bb_mult'])
        qty = _size(strategy)
        sl_pct = strategy.hp.get('bb_sl_pct', strategy.hp.get('sl_pct', 0.03))
        strategy.buy = qty, strategy.price
        strategy.stop_loss = qty, strategy.price * (1 - sl_pct)
        # TP targets the middle band (SMA) — natural mean-reversion target
        strategy.take_profit = qty, bb[0]

    def go_short(self, strategy) -> None:
        bb = ta.bollinger_bands(strategy.candles, period=strategy.hp['bb_window'],
                                 devup=strategy.hp['bb_mult'], devdn=strategy.hp['bb_mult'])
        qty = _size(strategy)
        sl_pct = strategy.hp.get('bb_sl_pct', strategy.hp.get('sl_pct', 0.03))
        strategy.sell = qty, strategy.price
        strategy.stop_loss = qty, strategy.price * (1 + sl_pct)
        # TP targets the middle band (SMA)
        strategy.take_profit = qty, bb[0]

    def update_position(self, strategy) -> None:
        pass  # Fixed TP at middle band — no trailing needed for mean-reversion


# ── Shared helpers ──────────────────────────────────────────────────

def _size(strategy) -> float:
    capital = strategy.balance * strategy.hp['risk_pct']
    return max(0.001, round(capital / strategy.price, 3))


def _in_cooldown(strategy) -> bool:
    cooldown_bars = strategy.vars.get('cooldown_bars', 8)
    last_exit = strategy.vars.get('last_exit_index', -999999)
    return (strategy.index - last_exit) < cooldown_bars


def _volume_spike(strategy) -> bool:
    if len(strategy.candles) < 20:
        return True
    avg_vol = np.mean(strategy.candles[-20:, 5])
    return strategy.candles[-1, 5] >= avg_vol * strategy.hp['vol_mult']
