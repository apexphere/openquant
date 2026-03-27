"""Volatility regime detector using ATR relative to price.

Classifies market volatility as low, medium, or high based on
ATR as a percentage of price compared to its own moving average.

Regimes:
  high-volatility  — ATR% above upper threshold (expanding, breakout-prone)
  low-volatility   — ATR% below lower threshold (contracting, mean-reversion-prone)
  normal           — ATR% between thresholds

Usage:
    detector = VolatilityRegimeDetector(atr_period=14, lookback=50)
    regime = detector.detect(candles)
"""
import numpy as np
import openquant.indicators as ta


REGIMES = frozenset({'high-volatility', 'low-volatility', 'normal', 'cold-start'})


class VolatilityRegimeDetector:
    """Stateful volatility regime detector using ATR percentile ranking.

    Compares current ATR% (ATR / close price) against its recent history
    to classify as high, normal, or low volatility.

    Parameters
    ----------
    atr_period : int
        ATR indicator period. Default 14.
    lookback : int
        Number of bars to rank ATR% against. Default 50.
    high_percentile : float
        Percentile threshold for high volatility (0-100). Default 75.
    low_percentile : float
        Percentile threshold for low volatility (0-100). Default 25.
    confirm_bars : int
        Confirmation delay before switching regime. Default 2.
    """

    def __init__(
        self,
        atr_period: int = 14,
        lookback: int = 50,
        high_percentile: float = 75,
        low_percentile: float = 25,
        confirm_bars: int = 2,
    ) -> None:
        self.atr_period = atr_period
        self.lookback = lookback
        self.high_percentile = high_percentile
        self.low_percentile = low_percentile
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
        min_bars = self.lookback + self.atr_period
        if candles is None or len(candles) < min_bars:
            return 'cold-start'

        # Compute ATR% for each bar in the lookback window
        atr_pcts = []
        for i in range(len(candles) - self.lookback, len(candles)):
            slice_candles = candles[:i + 1]
            atr_val = ta.atr(slice_candles, period=self.atr_period, sequential=True)[-1]
            close = slice_candles[-1, 2]
            if close > 0 and not np.isnan(atr_val):
                atr_pcts.append(atr_val / close * 100)

        if len(atr_pcts) < 10:
            return 'cold-start'

        current_atr_pct = atr_pcts[-1]
        high_threshold = np.percentile(atr_pcts, self.high_percentile)
        low_threshold = np.percentile(atr_pcts, self.low_percentile)

        if current_atr_pct >= high_threshold:
            return 'high-volatility'
        elif current_atr_pct <= low_threshold:
            return 'low-volatility'
        else:
            return 'normal'

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
