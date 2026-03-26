"""BB Mean Reversion — fade Bollinger Band extremes with hold-until-revert.

Logic:
  1. Price < lower band → long (fade oversold)
  2. Price > upper band → short (fade overbought)
  3. Hold until price reverts to SMA (mid band)
  4. SL at 5%, TP at 10%
"""
from openquant.strategies import Strategy
import openquant.indicators as ta


class BBMeanReversion(Strategy):

    def hyperparameters(self):
        return [
            {'name': 'bb_window', 'type': int, 'min': 10, 'max': 30, 'default': 15},
            {'name': 'bb_mult', 'type': float, 'min': 1.5, 'max': 3.5, 'default': 2.5},
            {'name': 'risk_pct', 'type': float, 'min': 0.01, 'max': 0.2, 'default': 0.05},
        ]

    def should_long(self) -> bool:
        bb = ta.bollinger_bands(self.candles, period=self.hp['bb_window'],
                                devup=self.hp['bb_mult'], devdn=self.hp['bb_mult'])
        lower = bb[2]
        return self.price < lower

    def should_short(self) -> bool:
        bb = ta.bollinger_bands(self.candles, period=self.hp['bb_window'],
                                devup=self.hp['bb_mult'], devdn=self.hp['bb_mult'])
        upper = bb[1]
        return self.price > upper

    def go_long(self):
        risk = self.hp['risk_pct']
        qty = self._size(risk)
        self.buy = qty, self.price
        self.stop_loss = qty, self.price * 0.95
        self.take_profit = qty, self.price * 1.10

    def go_short(self):
        risk = self.hp['risk_pct']
        qty = self._size(risk)
        self.sell = qty, self.price
        self.stop_loss = qty, self.price * 1.05
        self.take_profit = qty, self.price * 0.90

    def update_position(self):
        """Hold until price reverts to SMA (mid band)."""
        bb = ta.bollinger_bands(self.candles, period=self.hp['bb_window'],
                                devup=self.hp['bb_mult'], devdn=self.hp['bb_mult'])
        mid = bb[0]

        if self.is_long and self.price >= mid:
            self.liquidate()
        elif self.is_short and self.price <= mid:
            self.liquidate()

    def should_cancel_entry(self):
        return False

    def filters(self):
        return []

    def _size(self, risk_pct):
        capital = self.balance * risk_pct
        qty = capital / self.price
        return max(0.001, round(qty, 3))
