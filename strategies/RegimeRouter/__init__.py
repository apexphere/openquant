"""Regime Router — composite strategy with multi-TF regime-switched routing.

Timeframe hierarchy:
  D1:  Regime classification (SMA42 + ADX30, 3-day confirmation)
  4h:  Momentum rotation ranking + rebalance
  15m: BB-MR signal execution

Regimes:
  trending-up:    Momentum rotation (long only) — hold top K coins
  trending-down:  Flat (no trading)
  ranging:        BB-MR long + short — fade BB band extremes, trail-only exit

Rules:
  - Trailing stop on all positions (no mid-band exit)
  - trending-up: long only (no shorts)
  - ranging: both directions allowed
  - Cold start protection (no trading until D1 has enough history)
  - Rebalance lock: momentum rank evaluated once per rebalance period

Backtest results (Sep 2025 — Mar 2026, BTC-USDT 15m):
  PnL: +46.1% | Sharpe: 0.58 | WR: 29.7% | Max DD: -9.1%
  74 trades (35L/39S) | Win/Loss ratio: 2.72x | Annual: +81.8%
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
        self._last_exit_index = -999999
        self._cooldown_bars = 8  # 8 bars = 2 hours after exit before re-entry
        self._pending_regime = None
        self._pending_regime_count = 0
        self._confirmed_regime = 'cold-start'

    def hyperparameters(self):
        return [
            # BB-MR signal
            {'name': 'bb_window', 'type': int, 'min': 10, 'max': 30, 'default': 15},
            {'name': 'bb_mult', 'type': float, 'min': 1.5, 'max': 3.5, 'default': 2.5},
            # Regime classification
            {'name': 'regime_sma', 'type': int, 'min': 20, 'max': 100, 'default': 42},
            {'name': 'regime_adx_min', 'type': float, 'min': 15, 'max': 40, 'default': 30},
            {'name': 'regime_confirm', 'type': int, 'min': 0, 'max': 10, 'default': 3},
            # Momentum rotation
            {'name': 'momentum_lookback', 'type': int, 'min': 10, 'max': 200, 'default': 42},
            # Risk / position sizing
            {'name': 'risk_pct', 'type': float, 'min': 0.01, 'max': 0.2, 'default': 0.05},
            {'name': 'trail_pct', 'type': float, 'min': 0.005, 'max': 0.08, 'default': 0.02},
            {'name': 'sl_pct', 'type': float, 'min': 0.02, 'max': 0.10, 'default': 0.05},
            {'name': 'tp_pct', 'type': float, 'min': 0.05, 'max': 0.30, 'default': 0.10},
            # BB-MR entry confirmation
            {'name': 'rsi_period', 'type': int, 'min': 7, 'max': 21, 'default': 14},
            {'name': 'rsi_oversold', 'type': float, 'min': 20, 'max': 45, 'default': 30},
            {'name': 'rsi_overbought', 'type': float, 'min': 55, 'max': 80, 'default': 70},
            {'name': 'vol_mult', 'type': float, 'min': 0.5, 'max': 3.0, 'default': 1.2},
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
            raw_regime = 'trending-up'
        elif is_trending and current_close < sma:
            raw_regime = 'trending-down'
        elif current_close >= sma:
            raw_regime = 'ranging-up'
        else:
            raw_regime = 'ranging-down'

        # Confirmation delay: require N consecutive bars in new regime before switching
        confirm_days = self.hp['regime_confirm']
        if confirm_days > 0:
            if raw_regime != self._confirmed_regime:
                if raw_regime == self._pending_regime:
                    self._pending_regime_count += 1
                else:
                    self._pending_regime = raw_regime
                    self._pending_regime_count = 1

                if self._pending_regime_count >= confirm_days:
                    self._confirmed_regime = raw_regime
                    self._pending_regime = None
                    self._pending_regime_count = 0
            else:
                self._pending_regime = None
                self._pending_regime_count = 0
            regime = self._confirmed_regime
        else:
            regime = raw_regime

        return regime

    # ── Momentum Rotation (4h, with rebalance lock) ──────────────────────

    def _rebalance_if_needed(self):
        """Rebalance momentum ranking every REBALANCE_BARS bars."""
        if self.index - self._last_rebalance_index < REBALANCE_BARS:
            return

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

    def _is_selected(self) -> bool:
        """Check if this symbol is in the current momentum selection."""
        self._rebalance_if_needed()
        return self.symbol in self._selected_coins

    # ── BB / RSI / Volume (15m) ─────────────────────────────────────────

    def _bb(self):
        return ta.bollinger_bands(
            self.candles, period=self.hp['bb_window'],
            devup=self.hp['bb_mult'], devdn=self.hp['bb_mult'],
        )

    def _rsi(self):
        return ta.rsi(self.candles, period=self.hp['rsi_period'])

    def _volume_spike(self) -> bool:
        """Current volume >= vol_mult × 20-bar average."""
        if len(self.candles) < 20:
            return True
        avg_vol = np.mean(self.candles[-20:, 5])
        return self.candles[-1, 5] >= avg_vol * self.hp['vol_mult']

    # ── Entry ─────────────────────────────────────────────────────────────

    def _in_cooldown(self) -> bool:
        return (self.index - self._last_exit_index) < self._cooldown_bars

    def should_long(self) -> bool:
        if self._in_cooldown():
            return False

        regime = self._get_regime()

        if regime in ('cold-start', 'trending-down'):
            return False

        if regime == 'trending-up':
            return self._is_selected()

        # Ranging: BB-MR long — below lower band + RSI oversold + volume spike
        if self.price >= self._bb()[2]:
            return False
        if self._rsi() > self.hp['rsi_oversold']:
            return False
        if not self._volume_spike():
            return False
        return True

    def should_short(self) -> bool:
        if self._in_cooldown():
            return False

        regime = self._get_regime()

        if regime not in ('ranging-up', 'ranging-down'):
            return False

        # Ranging: BB-MR short — above upper band + RSI overbought + volume spike
        if self.price <= self._bb()[1]:
            return False
        if self._rsi() < self.hp['rsi_overbought']:
            return False
        if not self._volume_spike():
            return False
        return True

    # ── Execution ─────────────────────────────────────────────────────────

    def go_long(self):
        qty = self._size()
        self.buy = qty, self.price
        self.stop_loss = qty, self.price * (1 - self.hp['sl_pct'])
        self.take_profit = qty, self.price * (1 + self.hp['tp_pct'])

    def go_short(self):
        qty = self._size()
        self.sell = qty, self.price
        self.stop_loss = qty, self.price * (1 + self.hp['sl_pct'])
        self.take_profit = qty, self.price * (1 - self.hp['tp_pct'])

    # ── Exit ──────────────────────────────────────────────────────────────

    def update_position(self):
        if not self.is_long and not self.is_short:
            return

        regime = self._get_regime()

        if self.is_long:
            # Trailing stop
            trail_price = self.price * (1 - self.hp['trail_pct'])
            if trail_price > self.average_stop_loss:
                self.stop_loss = self.position.qty, trail_price

            if regime == 'trending-up':
                self._rebalance_if_needed()
                if not self._is_selected():
                    self.liquidate()
                return

            if regime == 'trending-down':
                self.liquidate()
                return

            # Ranging: exit via trailing stop only

        elif self.is_short:
            # Trailing stop
            trail_price = self.price * (1 + self.hp['trail_pct'])
            if trail_price < self.average_stop_loss:
                self.stop_loss = abs(self.position.qty), trail_price

            if regime in ('trending-up', 'trending-down'):
                self.liquidate()
                return

            # Ranging: exit via trailing stop only

    # ── Position Events ───────────────────────────────────────────────────

    def on_close_position(self, order, closed_trade=None):
        """Track exit time for cooldown."""
        self._last_exit_index = self.index

    # ── Helpers ───────────────────────────────────────────────────────────

    def should_cancel_entry(self):
        return False

    def filters(self):
        return []

    def _size(self):
        capital = self.balance * self.hp['risk_pct']
        return max(0.001, round(capital / self.price, 3))
