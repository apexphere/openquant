"""SmaCross2050D — SMA 20/50 trend-following on BTC 4h.

Entry: when SMA20 crosses above SMA50 OR when SMA20 > SMA50 and price 
pulls back to SMA20 (re-entry after pullback in uptrend).
Uses ADX trending filter. Exit: death cross or trailing stop.
"""
from openquant.strategies import Strategy
import openquant.indicators as ta


class SmaCross2050D(Strategy):

    def __init__(self):
        super().__init__()
        self._prev_sma_fast = None
        self._prev_sma_slow = None
        self._prev_price_near_sma = False
        self._last_exit_index = -999999
        self._cached_cross = None
        self._cached_cross_index = -1
        self._highest_since_entry = 0.0

    def hyperparameters(self):
        return [
            {'name': 'sma_fast', 'type': int, 'min': 10, 'max': 30, 'default': 20},
            {'name': 'sma_slow', 'type': int, 'min': 30, 'max': 80, 'default': 50},
            {'name': 'adx_min', 'type': float, 'min': 15, 'max': 40, 'default': 20},
            {'name': 'adx_period', 'type': int, 'min': 10, 'max': 20, 'default': 14},
            {'name': 'atr_period', 'type': int, 'min': 10, 'max': 30, 'default': 14},
            {'name': 'atr_sl_mult', 'type': float, 'min': 1.5, 'max': 5.0, 'default': 2.5},
            {'name': 'atr_trail_mult', 'type': float, 'min': 2.0, 'max': 6.0, 'default': 3.0},
            {'name': 'risk_pct', 'type': float, 'min': 0.01, 'max': 0.10, 'default': 0.02},
            {'name': 'cooldown_bars', 'type': int, 'min': 0, 'max': 24, 'default': 6},
            {'name': 'pullback_atr_mult', 'type': float, 'min': 0.3, 'max': 2.0, 'default': 0.5},
        ]

    def _get_4h_candles(self):
        return self.get_candles(self.exchange, self.symbol, '4h')

    def _is_trending(self) -> bool:
        c4h = self._get_4h_candles()
        if len(c4h) < self.hp['adx_period'] + 10:
            return False
        adx = ta.adx(c4h, period=self.hp['adx_period'])
        return adx >= self.hp['adx_min']

    def _sma_values(self):
        c4h = self._get_4h_candles()
        if len(c4h) < self.hp['sma_slow'] + 2:
            return None, None
        sma_fast = ta.sma(c4h, period=self.hp['sma_fast'])
        sma_slow = ta.sma(c4h, period=self.hp['sma_slow'])
        return sma_fast, sma_slow

    def _sma_cross(self):
        if self._cached_cross_index == self.index:
            return self._cached_cross

        sma_fast, sma_slow = self._sma_values()
        if sma_fast is None:
            self._cached_cross = 'none'
            self._cached_cross_index = self.index
            return 'none'

        prev_fast = self._prev_sma_fast
        prev_slow = self._prev_sma_slow
        self._prev_sma_fast = sma_fast
        self._prev_sma_slow = sma_slow

        if prev_fast is None or prev_slow is None:
            result = 'none'
        elif prev_fast <= prev_slow and sma_fast > sma_slow:
            result = 'golden'
        elif prev_fast >= prev_slow and sma_fast < sma_slow:
            result = 'death'
        else:
            result = 'none'

        self._cached_cross = result
        self._cached_cross_index = self.index
        return result

    def _atr_4h(self) -> float:
        c4h = self._get_4h_candles()
        return ta.atr(c4h, period=self.hp['atr_period'])

    def _in_cooldown(self) -> bool:
        return (self.index - self._last_exit_index) < self.hp['cooldown_bars']

    def _pullback_to_sma(self) -> bool:
        """Price pulled back near SMA20 in an existing uptrend."""
        sma_fast, sma_slow = self._sma_values()
        if sma_fast is None:
            return False
        # Must be in bullish alignment
        if sma_fast <= sma_slow:
            return False
        # Price near or touched SMA20 (within pullback_atr_mult * ATR)
        atr = self._atr_4h()
        distance = self.price - sma_fast
        threshold = atr * self.hp['pullback_atr_mult']
        
        # Price is within threshold of SMA fast (pullback zone) and bouncing
        was_near = self._prev_price_near_sma
        is_near = abs(distance) < threshold
        self._prev_price_near_sma = is_near
        
        # Enter when price was near SMA and now bounced above
        return was_near and self.price > sma_fast

    def should_long(self) -> bool:
        cross = self._sma_cross()

        if self._in_cooldown():
            return False

        # Require trending on 4h ADX
        if not self._is_trending():
            return False

        # Entry 1: Golden cross
        if cross == 'golden':
            sma_fast, sma_slow = self._sma_values()
            if sma_fast is not None and self.price >= sma_fast:
                return True

        # Entry 2: Pullback in existing uptrend
        if self._pullback_to_sma():
            return True

        return False

    def should_short(self) -> bool:
        return False

    def go_long(self):
        atr = self._atr_4h()
        sl_distance = atr * self.hp['atr_sl_mult']
        qty = self._size(sl_distance)
        self.buy = qty, self.price
        self.stop_loss = qty, self.price - sl_distance
        self._highest_since_entry = self.price

    def go_short(self):
        pass

    def update_position(self):
        if not self.is_long:
            return

        if self.price > self._highest_since_entry:
            self._highest_since_entry = self.price

        atr = self._atr_4h()
        trail_distance = atr * self.hp['atr_trail_mult']
        new_sl = self._highest_since_entry - trail_distance
        if new_sl > self.average_stop_loss:
            self.stop_loss = self.position.qty, new_sl

        # Exit on death cross
        sma_fast, sma_slow = self._sma_values()
        if sma_fast is not None and sma_fast < sma_slow:
            self.liquidate()

    def on_close_position(self, order, closed_trade=None):
        self._last_exit_index = self.index
        self._highest_since_entry = 0.0
        self._prev_price_near_sma = False

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
