"""Regime Router — composite strategy with multi-TF regime-switched routing.

Timeframe hierarchy:
  D1:  Regime classification (SMA42 + ADX14)
  4h:  Momentum rotation ranking + rebalance
  15m: BB-MR signal execution

Regimes:
  trending-up:    Momentum rotation — hold top K coins, rebalance every N days
  trending-down:  Flat (no trading)
  ranging:        BB-MR long only — fade dips to BB lower band

Rules:
  - Long only (no shorts)
  - Trailing stop on all positions
  - Cold start protection (no trading until D1 has enough history)
  - Rebalance lock: momentum rank evaluated once per rebalance period
"""
from openquant.strategies import Strategy
import openquant.indicators as ta
import numpy as np


UNIVERSE = [
    'BTC-USDT', 'ETH-USDT', 'SOL-USDT', 'BNB-USDT', 'XRP-USDT',
    'DOGE-USDT', 'ADA-USDT', 'AVAX-USDT', 'LINK-USDT', 'DOT-USDT',
]
MOMENTUM_TOP_K = 3
REBALANCE_BARS = 96 * 7  # 7 days in 15m bars (96 bars/day)


class RegimeRouter(Strategy):

    def __init__(self):
        super().__init__()
        self._last_rebalance_index = -999999
        self._selected_coins = []

    def hyperparameters(self):
        return [
            {'name': 'bb_window', 'type': int, 'min': 10, 'max': 30, 'default': 15},
            {'name': 'bb_mult', 'type': float, 'min': 1.5, 'max': 3.5, 'default': 2.5},
            {'name': 'regime_sma', 'type': int, 'min': 20, 'max': 60, 'default': 42},
            {'name': 'regime_adx_min', 'type': float, 'min': 10, 'max': 35, 'default': 20},
            {'name': 'momentum_lookback', 'type': int, 'min': 10, 'max': 200, 'default': 42},
            {'name': 'risk_pct', 'type': float, 'min': 0.01, 'max': 0.2, 'default': 0.05},
        ]

    # ── Regime (D1) ──────────────────────────────────────────────────────

    def _get_regime(self) -> str:
        d1 = self.get_candles(self.exchange, self.symbol, '1D')

        min_bars = self.hp['regime_sma'] * 2
        if len(d1) < min_bars:
            return 'cold-start'

        sma = ta.sma(d1, period=self.hp['regime_sma'])
        adx = ta.adx(d1, period=14)
        current_close = d1[-1, 2]
        is_trending = adx >= self.hp['regime_adx_min']

        if is_trending and current_close > sma:
            regime = 'trending-up'
        elif is_trending and current_close < sma:
            regime = 'trending-down'
        elif current_close >= sma:
            regime = 'ranging-up'
        else:
            regime = 'ranging-down'

        if self.index % 96 == 0:
            print(f'[{self.symbol} bar={self.index:>5}] price={self.price:.0f} D1: sma={sma:.0f} adx={adx:.1f} regime={regime} selected={self._selected_coins}')

        return regime

    # ── Momentum Rotation (4h, with rebalance lock) ──────────────────────

    def _rebalance_if_needed(self):
        """Rebalance momentum ranking every REBALANCE_BARS bars."""
        if self.index - self._last_rebalance_index < REBALANCE_BARS:
            return  # not time yet

        lookback = self.hp['momentum_lookback']
        scores = {}
        for sym in UNIVERSE:
            try:
                c = self.get_candles(self.exchange, sym, '4h')
                if len(c) < lookback + 5:
                    scores[sym] = 0.0
                    continue
                scores[sym] = (c[-1, 2] - c[-lookback, 2]) / c[-lookback, 2]
            except Exception:
                scores[sym] = 0.0

        ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        self._selected_coins = [s for s, _ in ranked[:MOMENTUM_TOP_K]]
        self._last_rebalance_index = self.index

        if self.index % 96 == 0:
            top_scores = [(s, f'{sc:.1%}') for s, sc in ranked[:MOMENTUM_TOP_K]]
            print(f'[REBALANCE bar={self.index}] top {MOMENTUM_TOP_K}: {top_scores}')

    def _is_selected(self) -> bool:
        """Check if this symbol is in the current momentum selection."""
        self._rebalance_if_needed()
        return self.symbol in self._selected_coins

    # ── BB (15m) ─────────────────────────────────────────────────────────

    def _bb(self):
        return ta.bollinger_bands(
            self.candles, period=self.hp['bb_window'],
            devup=self.hp['bb_mult'], devdn=self.hp['bb_mult'],
        )

    # ── Entry ─────────────────────────────────────────────────────────────

    def should_long(self) -> bool:
        regime = self._get_regime()

        if regime in ('cold-start', 'trending-down'):
            return False

        if regime == 'trending-up':
            # Momentum: long only if selected in current rebalance
            return self._is_selected()

        # Ranging: BB-MR long
        return self.price < self._bb()[2]

    def should_short(self) -> bool:
        regime = self._get_regime()

        # Only short in ranging (BB-MR fade overbought)
        if regime not in ('ranging-up', 'ranging-down'):
            return False

        return self.price > self._bb()[1]  # above upper band

    # ── Execution ─────────────────────────────────────────────────────────

    def go_long(self):
        qty = self._size()
        regime = self._get_regime()

        if regime == 'trending-up':
            self.buy = qty, self.price
            self.stop_loss = qty, self.price * 0.93
            self.take_profit = qty, self.price * 1.20
        else:
            self.buy = qty, self.price
            self.stop_loss = qty, self.price * 0.95
            self.take_profit = qty, self.price * 1.10

    def go_short(self):
        qty = self._size()
        self.sell = qty, self.price
        self.stop_loss = qty, self.price * 1.05
        self.take_profit = qty, self.price * 0.90

    # ── Exit ──────────────────────────────────────────────────────────────

    def update_position(self):
        if not self.is_long and not self.is_short:
            return

        regime = self._get_regime()

        if self.is_long:
            # Trailing stop: 3% below current price
            trail_price = self.price * 0.97
            if trail_price > self.average_stop_loss:
                self.stop_loss = self.position.qty, trail_price

            if regime == 'trending-up':
                # Momentum: exit at rebalance if no longer selected
                self._rebalance_if_needed()
                if not self._is_selected():
                    self.liquidate()
                return

            if regime == 'trending-down':
                # Regime flipped: exit long
                self.liquidate()
                return

            # Ranging BB-MR long: hold until mid band
            bb = self._bb()
            if self.price >= bb[0]:
                self.liquidate()

        elif self.is_short:
            # Trailing stop for shorts: 3% above current price
            trail_price = self.price * 1.03
            if trail_price < self.average_stop_loss:
                self.stop_loss = abs(self.position.qty), trail_price

            if regime in ('trending-up', 'trending-down'):
                # Regime changed from ranging: exit short
                self.liquidate()
                return

            # Ranging BB-MR short: hold until mid band
            bb = self._bb()
            if self.price <= bb[0]:
                self.liquidate()

    # ── Helpers ───────────────────────────────────────────────────────────

    def should_cancel_entry(self):
        return False

    def filters(self):
        return []

    def _size(self):
        capital = self.balance * self.hp['risk_pct']
        return max(0.001, round(capital / self.price, 3))
