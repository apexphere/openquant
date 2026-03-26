"""ADX + SMA regime detector.

Classifies market regime based on trend strength (ADX) and price position
relative to a simple moving average. Supports confirmation delay to prevent
whipsaw regime switches.

Regimes:
  trending-up    — ADX above threshold AND price above SMA
  trending-down  — ADX above threshold AND price below SMA
  ranging-up     — ADX below threshold AND price above SMA
  ranging-down   — ADX below threshold AND price below SMA
  cold-start     — insufficient candle data for indicators

Usage:
    detector = ADXRegimeDetector(sma_period=42, adx_period=14, adx_min=25)
    regime = detector.detect(daily_candles)
"""
import numpy as np
import openquant.indicators as ta


REGIMES = frozenset({
    'cold-start',
    'trending-up',
    'trending-down',
    'ranging-up',
    'ranging-down',
})


class ADXRegimeDetector:
    """Stateful regime detector using ADX trend strength + SMA direction.

    Stateful because of the confirmation delay: the detector tracks pending
    regime transitions and only confirms after N consecutive bars in the
    new regime. Call detect() once per bar on the detector's timeframe.

    Parameters
    ----------
    sma_period : int
        SMA lookback period for trend direction. Default 42.
    adx_period : int
        ADX indicator period. Default 14.
    adx_min : float
        ADX threshold — above this is "trending", below is "ranging". Default 25.
    confirm_bars : int
        Number of consecutive bars a new regime must persist before switching.
        0 = instant switching (no confirmation). Default 3.
    """

    def __init__(
        self,
        sma_period: int = 42,
        adx_period: int = 14,
        adx_min: float = 25,
        confirm_bars: int = 3,
    ) -> None:
        self.sma_period = sma_period
        self.adx_period = adx_period
        self.adx_min = adx_min
        self.confirm_bars = confirm_bars

        # Confirmation state
        self._confirmed_regime = 'cold-start'
        self._pending_regime: str | None = None
        self._pending_count = 0

    @property
    def regime(self) -> str:
        """The current confirmed regime."""
        return self._confirmed_regime

    def detect(self, candles: np.ndarray) -> str:
        """Classify the current market regime from candle data.

        Parameters
        ----------
        candles : np.ndarray
            Candle array with shape (n, 6): [timestamp, open, close, high, low, volume].
            Should be the detector's analysis timeframe (e.g., daily candles).

        Returns
        -------
        str
            One of: 'cold-start', 'trending-up', 'trending-down',
            'ranging-up', 'ranging-down'.
        """
        raw = self._classify(candles)
        return self._apply_confirmation(raw)

    def reset(self) -> None:
        """Reset confirmation state. Call when starting a new backtest session."""
        self._confirmed_regime = 'cold-start'
        self._pending_regime = None
        self._pending_count = 0

    def _classify(self, candles: np.ndarray) -> str:
        """Raw regime classification without confirmation delay."""
        min_bars = self.sma_period * 2
        if candles is None or len(candles) < min_bars:
            return 'cold-start'

        sma = ta.sma(candles, period=self.sma_period)
        adx = ta.adx(candles, period=self.adx_period)
        current_close = candles[-1, 2]

        if np.isnan(sma) or np.isnan(adx) or np.isnan(current_close):
            return self._confirmed_regime

        is_trending = adx >= self.adx_min

        if is_trending and current_close > sma:
            return 'trending-up'
        elif is_trending and current_close < sma:
            return 'trending-down'
        elif current_close >= sma:
            return 'ranging-up'
        else:
            return 'ranging-down'

    def _apply_confirmation(self, raw_regime: str) -> str:
        """Apply confirmation delay to prevent whipsaw regime switches."""
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
