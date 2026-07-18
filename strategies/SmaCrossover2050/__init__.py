
from openquant.strategies import Strategy
import openquant.indicators as ta


class SmaCrossover2050(Strategy):
    def hyperparameters(self):
        return [
            {'name': 'fast_period', 'type': int, 'min': 5, 'max': 50, 'default': 20},
            {'name': 'slow_period', 'type': int, 'min': 20, 'max': 200, 'default': 50},
            {'name': 'risk_pct', 'type': float, 'min': 0.01, 'max': 0.1, 'default': 0.05},
            {'name': 'stop_pct', 'type': float, 'min': 0.01, 'max': 0.1, 'default': 0.05},
            {'name': 'tp_pct', 'type': float, 'min': 0.02, 'max': 0.3, 'default': 0.10},
        ]

    def _sma_fast(self):
        return ta.sma(self.candles, period=self.hp['fast_period'])

    def _sma_slow(self):
        return ta.sma(self.candles, period=self.hp['slow_period'])

    def _prev_sma_fast(self):
        return ta.sma(self.candles[:-1], period=self.hp['fast_period'])

    def _prev_sma_slow(self):
        return ta.sma(self.candles[:-1], period=self.hp['slow_period'])

    def should_long(self) -> bool:
        return self._prev_sma_fast() < self._prev_sma_slow() and self._sma_fast() > self._sma_slow()

    def should_short(self) -> bool:
        return self._prev_sma_fast() > self._prev_sma_slow() and self._sma_fast() < self._sma_slow()

    def go_long(self):
        qty = (self.balance * self.hp['risk_pct']) / self.price
        self.buy = qty, self.price
        self.stop_loss = qty, self.price * (1 - self.hp['stop_pct'])
        self.take_profit = qty, self.price * (1 + self.hp['tp_pct'])

    def go_short(self):
        qty = (self.balance * self.hp['risk_pct']) / self.price
        self.sell = qty, self.price
        self.stop_loss = qty, self.price * (1 + self.hp['stop_pct'])
        self.take_profit = qty, self.price * (1 - self.hp['tp_pct'])

    def update_position(self):
        pass

    def should_cancel_entry(self):
        return False

    def filters(self):
        return []
