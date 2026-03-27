"""Trend strength detector using EMA crossover.

Simpler than ADX. Uses fast/slow EMA crossover to determine trend
direction, with optional minimum separation threshold for confirmation.

Regimes:
  trending-up    — fast EMA above slow EMA by at least the threshold
  trending-down  — fast EMA below slow EMA by at least the threshold
  ranging        — EMAs too close together (no clear trend)
  cold-start     — insufficient data

Usage:
    detector = TrendStrengthDetector(fast_period=13, slow_period=34)
    regime = detector.detect(candles)
"""
import numpy as np
import openquant.indicators as ta


REGIMES = frozenset({'trending-up', 'trending-down', 'ranging', 'cold-start'})


class TrendStrengthDetector:
    """Stateful trend detector using EMA crossover with separation threshold.

    Parameters
    ----------
    fast_period : int
        Fast EMA period. Default 13.
    slow_period : int
        Slow EMA period. Default 34.
    separation_pct : float
        Minimum separation between EMAs as % of price to qualify as trending.
        Default 0.5 (0.5% of price). Set to 0 for pure crossover.
    confirm_bars : int
        Confirmation delay before switching regime. Default 2.
    """

    def __init__(
        self,
        fast_period: int = 13,
        slow_period: int = 34,
        separation_pct: float = 0.5,
        confirm_bars: int = 2,
    ) -> None:
        self.fast_period = fast_period
        self.slow_period = slow_period
        self.separation_pct = separation_pct
        self.confirm_bars = confirm_bars

        self._confirmed_regime = 'cold-start'
        self._pending_regime: str | None = None
        self._pending_count = 0

    @property
    def regime(self) -> str:
        return self._confirmed_regime

    def detect(self, candles: np.ndarray) -> str:
        raw = self._classify(candles)
        return self._apply_confirmation(raw)

    def reset(self) -> None:
        self._confirmed_regime = 'cold-start'
        self._pending_regime = None
        self._pending_count = 0

    def _classify(self, candles: np.ndarray) -> str:
        min_bars = self.slow_period * 2
        if candles is None or len(candles) < min_bars:
            return 'cold-start'

        fast_ema = ta.ema(candles, period=self.fast_period, sequential=True)[-1]
        slow_ema = ta.ema(candles, period=self.slow_period, sequential=True)[-1]
        current_close = candles[-1, 2]

        if np.isnan(fast_ema) or np.isnan(slow_ema) or np.isnan(current_close):
            return self._confirmed_regime

        # Calculate separation as % of price
        if current_close > 0:
            separation = (fast_ema - slow_ema) / current_close * 100
        else:
            return self._confirmed_regime

        if separation > self.separation_pct:
            return 'trending-up'
        elif separation < -self.separation_pct:
            return 'trending-down'
        else:
            return 'ranging'

    def _apply_confirmation(self, raw_regime: str) -> str:
        if raw_regime == 'cold-start':
            self._confirmed_regime = 'cold-start'
            self._pending_regime = None
            self._pending_count = 0
            return 'cold-start'

        if self.confirm_bars <= 0:
            self._confirmed_regime = raw_regime
            return raw_regime

        if raw_regime != self._confirmed_regime:
            if raw_regime == self._pending_regime:
                self._pending_count += 1
            else:
                self._pending_regime = raw_regime
                self._pending_count = 1
            if self._pending_count >= self.confirm_bars:
                self._confirmed_regime = raw_regime
                self._pending_regime = None
                self._pending_count = 0
        else:
            self._pending_regime = None
            self._pending_count = 0

        return self._confirmed_regime
