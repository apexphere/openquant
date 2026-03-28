"""EMA + MACD composite regime detector.

Combines EMA crossover (fast direction) with MACD histogram (leading
momentum signal). MACD histogram detects trend exhaustion before it's
visible in price, unlike ADX which lags 2-3 weeks.

Detection logic:
    separation = (ema_fast - ema_slow) / price * 100
    macd_hist  = MACD histogram value

    Trending-up:   EMA bullish (separation > threshold) AND MACD line > 0
    Trending-down: EMA bearish (separation < -threshold) AND MACD line < 0
    Ranging-up:    no trend alignment, price >= slow EMA
    Ranging-down:  no trend alignment, price < slow EMA

    Key insight: uses MACD LINE (not histogram) for the energy gate.
    The MACD line stays positive during normal pullbacks in uptrends
    (zero-line bounce). It only crosses zero when the trend genuinely
    exhausts. The histogram goes negative on every pullback, causing
    false ranging signals.

Regimes:
    trending-up    — EMA bullish + MACD momentum confirms
    trending-down  — EMA bearish + MACD momentum confirms
    ranging-up     — no alignment + price above slow EMA
    ranging-down   — no alignment + price below slow EMA

Usage:
    detector = EmaAdxDetector(fast_period=13, slow_period=34)
    regime = detector.detect(daily_candles)
"""
import numpy as np
import openquant.indicators as ta


REGIMES = frozenset({
    'trending-up',
    'trending-down',
    'ranging-up',
    'ranging-down',
})


class EmaAdxDetector:
    """Stateful composite detector: EMA direction + MACD momentum gate.

    Parameters
    ----------
    fast_period : int
        Fast EMA period for direction. Default 13.
    slow_period : int
        Slow EMA period for direction. Default 34.
    macd_fast : int
        MACD fast period. Default 12.
    macd_slow : int
        MACD slow period. Default 26.
    macd_signal : int
        MACD signal smoothing period. Default 9.
    separation_pct : float
        Minimum EMA separation as % of price to confirm direction.
        Default 0.3.
    confirm_bars : int
        Consecutive completed bars a new regime must persist before
        switching. Default 2.
    timeframe : str
        Candle timeframe. Strategy._detect_regime() reads this.
        Default '1D'.
    """

    def __init__(
        self,
        fast_period: int = 13,
        slow_period: int = 34,
        macd_fast: int = 12,
        macd_slow: int = 26,
        macd_signal: int = 9,
        separation_pct: float = 0.3,
        confirm_bars: int = 2,
        timeframe: str = '1D',
    ) -> None:
        self.fast_period = fast_period
        self.slow_period = slow_period
        self.macd_fast = macd_fast
        self.macd_slow = macd_slow
        self.macd_signal = macd_signal
        self.separation_pct = separation_pct
        self.confirm_bars = confirm_bars
        self.timeframe = timeframe

        self._confirmed_regime = None
        self._pending_regime: str | None = None
        self._pending_count = 0
        self._last_candle_timestamp = None

    @property
    def regime(self) -> str | None:
        return self._confirmed_regime

    def detect(self, candles: np.ndarray) -> str:
        """Classify the current market regime.

        Only reclassifies on completed bar boundaries to avoid
        intra-bar whipsaw when called on every 15m tick with
        daily candles.

        Raises ValueError if insufficient data.
        """
        min_bars = max(self.slow_period, self.macd_slow + self.macd_signal) * 2
        if candles is None or len(candles) < min_bars:
            raise ValueError(
                f'EmaAdxDetector needs at least {min_bars} candles '
                f'(got {len(candles) if candles is not None else 0}). '
                f'Check your warmup period or data range.'
            )

        # Only reclassify on new completed bar
        last_completed_ts = candles[-2, 0] if len(candles) >= 2 else None
        if last_completed_ts == self._last_candle_timestamp and self._confirmed_regime is not None:
            return self._confirmed_regime
        self._last_candle_timestamp = last_completed_ts

        # Classify on completed candles (exclude in-progress last bar)
        raw = self._classify(candles[:-1])
        return self._apply_confirmation(raw)

    def reset(self) -> None:
        self._confirmed_regime = None
        self._pending_regime = None
        self._pending_count = 0
        self._last_candle_timestamp = None

    def _classify(self, candles: np.ndarray) -> str:
        fast_ema = ta.ema(candles, period=self.fast_period, sequential=True)[-1]
        slow_ema = ta.ema(candles, period=self.slow_period, sequential=True)[-1]
        current_close = candles[-1, 2]

        # MACD line position relative to zero — NOT histogram.
        # MACD line stays positive during normal pullbacks in uptrends
        # (zero-line bounce). It only crosses zero when the trend is
        # genuinely exhausted. Histogram goes negative on every pullback,
        # causing false ranging signals.
        macd_result = ta.macd(candles, fast_period=self.macd_fast,
                              slow_period=self.macd_slow,
                              signal_period=self.macd_signal)
        macd_line = macd_result[0]  # MACD line (not histogram)

        if np.isnan(fast_ema) or np.isnan(slow_ema) or np.isnan(macd_line) or np.isnan(current_close):
            return self._confirmed_regime or 'ranging-up'

        if current_close <= 0:
            return self._confirmed_regime or 'ranging-up'

        separation = (fast_ema - slow_ema) / current_close * 100

        # Trending: EMA direction + MACD line same side of zero
        # MACD line > 0 = bullish momentum intact (even during pullbacks)
        # MACD line < 0 = bearish momentum intact
        # MACD line crosses zero = trend exhausted → ranging
        ema_bullish = separation > self.separation_pct
        ema_bearish = separation < -self.separation_pct

        if ema_bullish and macd_line > 0:
            return 'trending-up'
        elif ema_bearish and macd_line < 0:
            return 'trending-down'
        elif current_close >= slow_ema:
            return 'ranging-up'
        else:
            return 'ranging-down'

    def _apply_confirmation(self, raw_regime: str) -> str:
        """Confirmation state machine. See module docstring."""
        if self._confirmed_regime is None:
            self._confirmed_regime = raw_regime
            return raw_regime

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
