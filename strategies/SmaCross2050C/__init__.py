"""SmaCross2050C — SMA 20/50 crossover trend-following on BTC 4h.

Iteration 3: Added SMA slope filter and faster exit on momentum loss.
- Higher ADX threshold (25) for trend confirmation
- SMA 50 slope must be positive (longs) or negative (shorts) 
- Exit on SMA convergence (not just crossover) to cut losers faster
- ATR-based stop loss with moderate trailing
"""
from openquant.strategies import Strategy
import openquant.indicators as ta
import numpy as np


class SmaCross2050C(Strategy):

    def __init__(self):
        super().__init__()
        self._prev_sma_fast = None
        self._prev_sma_slow = None
        self._last_exit_index = -999999

    def hyperparameters(self):
        return [
            {'name': 'sma_fast', 'type': int, 'min': 10, 'max': 30, 'default': 20},
            {'name': 'sma_slow', 'type': int, 'min': 30, 'max': 80, 'default': 50},
            {'name': 'adx_min', 'type': float, 'min': 15, 'max': 40, 'default': 25},
            {'name': 'atr_period', 'type': int, 'min': 10, 'max': 30, 'default': 14},
            {'name': 'atr_sl_mult', 'type': float, 'min': 1.5, 'max': 5.0, 'default': 2.5},
            {'name': 'atr_trail_mult', 'type': float, 'min': 2.0, 'max': 6.0, 'default': 3.5},
            {'name': 'risk_pct', 'type': float, 'min': 0.01, 'max': 0.10, 'default': 0.02},
            {'name': 'cooldown_bars', 'type': int, 'min': 0, 'max': 24, 'default': 6},
            {'name': 'slope_lookback', 'type': int, 'min': 3, 'max': 15, 'default': 5},
            {'name': 'convergence_pct', 'type': float, 'min': 0.001, 'max': 0.02, 'default': 0.005},
        ]

    # -- Trend Filter (D1 ADX) --

    def _is_trending(self) -> bool:
        d1 = self.get_candles(self.exchange, self.symbol, '1D')
        if len(d1) < 30:
            return False
        adx = ta.adx(d1, period=14)
        return adx >= self.hp['adx_min']

    # -- SMA Crossover Detection (4h) --

    def _get_4h_candles(self):
        return self.get_candles(self.exchange, self.symbol, '4h')

    def _sma_values(self):
        c4h = self._get_4h_candles()
        if len(c4h) < self.hp['sma_slow'] + 2:
            return None, None
        sma_fast = ta.sma(c4h, period=self.hp['sma_fast'])
        sma_slow = ta.sma(c4h, period=self.hp['sma_slow'])
        return sma_fast, sma_slow

    def _sma_cross(self):
        sma_fast, sma_slow = self._sma_values()
        if sma_fast is None:
            return 'none'

        prev_fast = self._prev_sma_fast
        prev_slow = self._prev_sma_slow
        self._prev_sma_fast = sma_fast
        self._prev_sma_slow = sma_slow

        if prev_fast is None or prev_slow is None:
            return 'none'

        if prev_fast <= prev_slow and sma_fast > sma_slow:
            return 'golden'
        if prev_fast >= prev_slow and sma_fast < sma_slow:
            return 'death'
        return 'none'

    def _sma_slow_slope_up(self) -> bool:
        """Check if SMA slow is sloping upward over lookback period."""
        c4h = self._get_4h_candles()
        if len(c4h) < self.hp['sma_slow'] + self.hp['slope_lookback'] + 2:
            return False
        closes = c4h[:, 2]  # close prices
        n = len(closes)
        lookback = self.hp['slope_lookback']
        # Calculate SMA slow at current and lookback bars ago
        sma_now = np.mean(closes[n - self.hp['sma_slow']:n])
        sma_prev = np.mean(closes[n - self.hp['sma_slow'] - lookback:n - lookback])
        return sma_now > sma_prev

    def _sma_slow_slope_down(self) -> bool:
        """Check if SMA slow is sloping downward over lookback period."""
        c4h = self._get_4h_candles()
        if len(c4h) < self.hp['sma_slow'] + self.hp['slope_lookback'] + 2:
            return False
        closes = c4h[:, 2]
        n = len(closes)
        lookback = self.hp['slope_lookback']
        sma_now = np.mean(closes[n - self.hp['sma_slow']:n])
        sma_prev = np.mean(closes[n - self.hp['sma_slow'] - lookback:n - lookback])
        return sma_now < sma_prev

    def _atr_4h(self) -> float:
        c4h = self._get_4h_candles()
        return ta.atr(c4h, period=self.hp['atr_period'])

    def _in_cooldown(self) -> bool:
        return (self.index - self._last_exit_index) < self.hp['cooldown_bars']

    # -- Entry --

    def should_long(self) -> bool:
        if self._in_cooldown():
            self._sma_cross()
            return False
        if not self._is_trending():
            self._sma_cross()
            return False
        cross = self._sma_cross()
        if cross != 'golden':
            return False
        return self._sma_slow_slope_up()

    def should_short(self) -> bool:
        if self._in_cooldown():
            return False
        if not self._is_trending():
            return False
        cross = self._sma_cross()
        if cross != 'death':
            return False
        return self._sma_slow_slope_down()

    # -- Execution --

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

    # -- Position Management --

    def update_position(self):
        if not self.is_long and not self.is_short:
            return

        atr = self._atr_4h()
        trail_distance = atr * self.hp['atr_trail_mult']
        sma_fast, sma_slow = self._sma_values()

        if sma_fast is None:
            return

        if self.is_long:
            # Trailing stop
            new_sl = self.price - trail_distance
            if new_sl > self.average_stop_loss:
                self.stop_loss = self.position.qty, new_sl
            # Exit on SMA convergence (SMAs getting close = momentum dying)
            gap_pct = (sma_fast - sma_slow) / sma_slow
            if gap_pct < self.hp['convergence_pct']:
                self.liquidate()

        elif self.is_short:
            new_sl = self.price + trail_distance
            if new_sl < self.average_stop_loss:
                self.stop_loss = abs(self.position.qty), new_sl
            gap_pct = (sma_slow - sma_fast) / sma_slow
            if gap_pct < self.hp['convergence_pct']:
                self.liquidate()

    def on_close_position(self, order, closed_trade=None):
        self._last_exit_index = self.index

    # -- Helpers --

    def _size(self, sl_distance: float) -> float:
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
