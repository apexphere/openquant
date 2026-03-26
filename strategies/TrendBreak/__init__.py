"""TrendBreak — Donchian Channel breakout with multi-TF trend filter.

Timeframe hierarchy:
  D1:  Trend direction via EMA crossover (fast/slow)
  4h:  Donchian Channel breakout for entry signals
  4h:  ATR for dynamic stop loss and trailing stop

Logic:
  - Daily EMA fast > slow → uptrend → long-only
  - Daily EMA fast < slow → downtrend → short-only
  - Enter long when price breaks above prior Donchian upper (in uptrend)
  - Enter short when price breaks below prior Donchian lower (in downtrend)
  - Volatility filter: ATR must be expanding (above its own SMA) to enter
  - Stop loss: entry ± ATR * atr_sl_mult
  - Trailing stop: ratchets using ATR * atr_trail_mult
  - No fixed take profit — let winners run
  - Cooldown after exit to avoid re-entering same broken range

Design rationale:
  Trend-following breakout strategies capture large moves by trading in the
  direction of the dominant trend. Lower win rate but large avg win/loss ratio.
  ATR-based risk management adapts to volatility regimes automatically.
  Volatility expansion filter reduces false breakouts in choppy markets.
"""
from openquant.strategies import Strategy
import openquant.indicators as ta
import numpy as np


class TrendBreak(Strategy):

    def __init__(self):
        super().__init__()
        self._last_exit_index = -999999

    def hyperparameters(self):
        return [
            # Trend filter (D1)
            {'name': 'ema_fast', 'type': int, 'min': 8, 'max': 30, 'default': 13},
            {'name': 'ema_slow', 'type': int, 'min': 21, 'max': 60, 'default': 34},
            {'name': 'adx_min', 'type': float, 'min': 15, 'max': 40, 'default': 20},
            # Breakout detection (4h)
            {'name': 'donchian_period', 'type': int, 'min': 15, 'max': 50, 'default': 30},
            # Risk management (4h ATR)
            {'name': 'atr_period', 'type': int, 'min': 10, 'max': 30, 'default': 14},
            {'name': 'atr_sl_mult', 'type': float, 'min': 1.5, 'max': 5.0, 'default': 2.5},
            {'name': 'atr_trail_mult', 'type': float, 'min': 1.5, 'max': 5.0, 'default': 3.0},
            # Volatility filter
            {'name': 'atr_sma_period', 'type': int, 'min': 10, 'max': 40, 'default': 20},
            # Position sizing
            {'name': 'risk_pct', 'type': float, 'min': 0.01, 'max': 0.10, 'default': 0.02},
            # Cooldown (in 4h bars)
            {'name': 'cooldown_bars', 'type': int, 'min': 0, 'max': 12, 'default': 6},
        ]

    # ── Trend Direction (D1) ───────────────────────────────────────────

    def _trend_direction(self) -> str:
        """Return 'up', 'down', or 'neutral' based on daily EMA crossover + ADX."""
        d1 = self.get_candles(self.exchange, self.symbol, '1D')

        min_bars = self.hp['ema_slow'] * 2
        if len(d1) < min_bars:
            return 'neutral'

        # ADX must confirm a real trend exists
        adx = ta.adx(d1, period=14)
        if adx < self.hp['adx_min']:
            return 'neutral'

        ema_fast = ta.ema(d1, period=self.hp['ema_fast'])
        ema_slow = ta.ema(d1, period=self.hp['ema_slow'])

        if ema_fast > ema_slow:
            return 'up'
        elif ema_fast < ema_slow:
            return 'down'
        return 'neutral'

    # ── Breakout Detection (4h) ────────────────────────────────────────

    def _get_4h_candles(self):
        return self.get_candles(self.exchange, self.symbol, '4h')

    def _donchian_4h(self):
        """Return Donchian upper/lower from the PREVIOUS 4h bar.

        Exclude the current bar so a breakout is 'price crosses above
        the prior channel boundary' — otherwise the current bar's high
        is already baked into the channel.
        """
        c4h = self._get_4h_candles()
        if len(c4h) < self.hp['donchian_period'] + 1:
            from collections import namedtuple
            DC = namedtuple('DC', ['upperband', 'middleband', 'lowerband'])
            return DC(np.nan, np.nan, np.nan)
        return ta.donchian(c4h[:-1], period=self.hp['donchian_period'])

    def _atr_4h(self) -> float:
        """Return current ATR on 4h candles."""
        c4h = self._get_4h_candles()
        return ta.atr(c4h, period=self.hp['atr_period'])

    def _volatility_expanding(self) -> bool:
        """True when current ATR is above its own SMA — volatility is expanding."""
        c4h = self._get_4h_candles()
        sma_period = self.hp['atr_sma_period']
        atr_period = self.hp['atr_period']

        if len(c4h) < atr_period + sma_period:
            return False

        atr_series = ta.atr(c4h, period=atr_period, sequential=True)
        current_atr = atr_series[-1]
        atr_sma = np.nanmean(atr_series[-sma_period:])

        return current_atr > atr_sma

    def _in_cooldown(self) -> bool:
        return (self.index - self._last_exit_index) < self.hp['cooldown_bars']

    # ── Entry ──────────────────────────────────────────────────────────

    def should_long(self) -> bool:
        if self._in_cooldown():
            return False

        trend = self._trend_direction()
        if trend != 'up':
            return False

        if not self._volatility_expanding():
            return False

        dc = self._donchian_4h()
        if np.isnan(dc.upperband):
            return False

        return self.price > dc.upperband

    def should_short(self) -> bool:
        if self._in_cooldown():
            return False

        trend = self._trend_direction()
        if trend != 'down':
            return False

        if not self._volatility_expanding():
            return False

        dc = self._donchian_4h()
        if np.isnan(dc.lowerband):
            return False

        return self.price < dc.lowerband

    # ── Execution ──────────────────────────────────────────────────────

    def go_long(self):
        atr = self._atr_4h()
        sl_distance = atr * self.hp['atr_sl_mult']

        qty = self._size(sl_distance)
        self.buy = qty, self.price
        self.stop_loss = qty, self.price - sl_distance

    def go_short(self):
        atr = self._atr_4h()
        sl_distance = atr * self.hp['atr_sl_mult']

        qty = self._size(sl_distance)
        self.sell = qty, self.price
        self.stop_loss = qty, self.price + sl_distance

    # ── Position Management ────────────────────────────────────────────

    def update_position(self):
        if not self.is_long and not self.is_short:
            return

        atr = self._atr_4h()
        trail_distance = atr * self.hp['atr_trail_mult']

        if self.is_long:
            new_sl = self.price - trail_distance
            if new_sl > self.average_stop_loss:
                self.stop_loss = self.position.qty, new_sl

            if self._trend_direction() == 'down':
                self.liquidate()

        elif self.is_short:
            new_sl = self.price + trail_distance
            if new_sl < self.average_stop_loss:
                self.stop_loss = abs(self.position.qty), new_sl

            if self._trend_direction() == 'up':
                self.liquidate()

    def on_close_position(self, order, closed_trade=None):
        self._last_exit_index = self.index

    # ── Helpers ─────────────────────────────────────────────────────────

    def _size(self, sl_distance: float) -> float:
        """Risk-based position sizing: risk_pct of balance per trade.

        Caps at 95% of available margin to avoid margin errors.
        """
        risk_amount = self.balance * self.hp['risk_pct']
        if sl_distance <= 0:
            return 0.001
        qty = risk_amount / sl_distance
        max_qty = (self.available_margin * 0.95) / self.price
        qty = min(qty, max_qty)
        return max(0.001, round(qty, 3))

    def should_cancel_entry(self):
        return True

    def filters(self):
        return []
