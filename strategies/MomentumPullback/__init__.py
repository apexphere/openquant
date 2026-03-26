"""MomentumPullback — Trend-following with pullback entries for BTC.

Timeframe hierarchy:
  D1:  Trend direction via EMA crossover + ADX strength filter
  4h:  RSI pullback entry signals within the trend
  4h:  ATR for dynamic stop loss and trailing stop

Logic:
  - Daily EMA fast > slow + ADX above threshold → uptrend → long-only
  - Daily EMA fast < slow + ADX above threshold → downtrend → short-only
  - Long entry: RSI dips below oversold threshold then recovers above it
  - Short entry: RSI rises above overbought threshold then drops below it
  - Stop loss: entry +/- ATR * atr_sl_mult
  - Trailing stop: ratchets using ATR * atr_trail_mult
  - Take profit: entry +/- ATR * atr_tp_mult (wider than stop for positive expectancy)

Design rationale:
  Pullback entries within confirmed trends get better prices than breakout entries.
  RSI-based timing catches mean-reversion dips within the dominant trend.
  ATR-based exits adapt to changing volatility automatically.
"""
from openquant.strategies import Strategy
import openquant.indicators as ta
import numpy as np


class MomentumPullback(Strategy):

    def __init__(self):
        super().__init__()
        self._prev_rsi = None
        self._last_exit_index = -999999

    def hyperparameters(self):
        return [
            # Trend filter (D1)
            {'name': 'ema_fast', 'type': int, 'min': 8, 'max': 30, 'default': 12},
            {'name': 'ema_slow', 'type': int, 'min': 21, 'max': 60, 'default': 26},
            {'name': 'adx_min', 'type': float, 'min': 15, 'max': 35, 'default': 20},
            # RSI pullback (4h)
            {'name': 'rsi_period', 'type': int, 'min': 7, 'max': 21, 'default': 14},
            {'name': 'rsi_oversold', 'type': float, 'min': 25, 'max': 45, 'default': 35},
            {'name': 'rsi_overbought', 'type': float, 'min': 55, 'max': 75, 'default': 65},
            # ATR risk management (4h)
            {'name': 'atr_period', 'type': int, 'min': 10, 'max': 30, 'default': 14},
            {'name': 'atr_sl_mult', 'type': float, 'min': 1.0, 'max': 4.0, 'default': 2.0},
            {'name': 'atr_trail_mult', 'type': float, 'min': 1.5, 'max': 5.0, 'default': 3.0},
            {'name': 'atr_tp_mult', 'type': float, 'min': 3.0, 'max': 8.0, 'default': 5.0},
            # Position sizing
            {'name': 'risk_pct', 'type': float, 'min': 0.01, 'max': 0.10, 'default': 0.03},
            # Cooldown (4h bars)
            {'name': 'cooldown_bars', 'type': int, 'min': 0, 'max': 12, 'default': 4},
        ]

    # -- Trend Direction (D1) --

    def _trend_direction(self) -> str:
        d1 = self.get_candles(self.exchange, self.symbol, '1D')

        min_bars = self.hp['ema_slow'] * 2
        if len(d1) < min_bars:
            return 'neutral'

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

    # -- RSI Pullback Detection (4h) --

    def _get_4h_candles(self):
        return self.get_candles(self.exchange, self.symbol, '4h')

    def _rsi_4h(self) -> float:
        c4h = self._get_4h_candles()
        return ta.rsi(c4h, period=self.hp['rsi_period'])

    def _rsi_crossed_above(self, threshold: float) -> bool:
        """RSI just crossed above threshold (was below, now above)."""
        current_rsi = self._rsi_4h()
        crossed = (self._prev_rsi is not None
                   and self._prev_rsi <= threshold
                   and current_rsi > threshold)
        self._prev_rsi = current_rsi
        return crossed

    def _rsi_crossed_below(self, threshold: float) -> bool:
        """RSI just crossed below threshold (was above, now below)."""
        current_rsi = self._rsi_4h()
        crossed = (self._prev_rsi is not None
                   and self._prev_rsi >= threshold
                   and current_rsi < threshold)
        self._prev_rsi = current_rsi
        return crossed

    def _atr_4h(self) -> float:
        c4h = self._get_4h_candles()
        return ta.atr(c4h, period=self.hp['atr_period'])

    def _in_cooldown(self) -> bool:
        return (self.index - self._last_exit_index) < self.hp['cooldown_bars']

    # -- Entry --

    def should_long(self) -> bool:
        if self._in_cooldown():
            return False

        trend = self._trend_direction()
        if trend != 'up':
            self._rsi_4h()  # keep prev_rsi updated
            return False

        # RSI dipped below oversold then recovered above it = pullback complete
        return self._rsi_crossed_above(self.hp['rsi_oversold'])

    def should_short(self) -> bool:
        if self._in_cooldown():
            return False

        trend = self._trend_direction()
        if trend != 'down':
            # prev_rsi already updated by should_long
            return False

        # RSI rose above overbought then dropped below it = rally exhausted
        return self._rsi_crossed_below(self.hp['rsi_overbought'])

    # -- Execution --

    def go_long(self):
        atr = self._atr_4h()
        sl_distance = atr * self.hp['atr_sl_mult']
        tp_distance = atr * self.hp['atr_tp_mult']

        qty = self._size(sl_distance)
        self.buy = qty, self.price
        self.stop_loss = qty, self.price - sl_distance
        self.take_profit = qty, self.price + tp_distance

    def go_short(self):
        atr = self._atr_4h()
        sl_distance = atr * self.hp['atr_sl_mult']
        tp_distance = atr * self.hp['atr_tp_mult']

        qty = self._size(sl_distance)
        self.sell = qty, self.price
        self.stop_loss = qty, self.price + sl_distance
        self.take_profit = qty, self.price - tp_distance

    # -- Position Management --

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
