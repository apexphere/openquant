"""EMA + MACD composite regime detector.

Combines EMA crossover (fast direction) with MACD histogram (leading
momentum signal). MACD histogram detects trend exhaustion before it's
visible in price, unlike ADX which lags 2-3 weeks.

Detection logic:
    separation = (ema_fast - ema_slow) / price * 100
    macd_hist  = MACD histogram value

    Trending-up:   EMA bullish + MACD line > 0
    Trending-down: EMA bearish + MACD line < 0 + MACD histogram < 0
    Ranging-up:    no trend alignment, price >= slow EMA
    Ranging-down:  no trend alignment, price < slow EMA

    Asymmetric MACD confirmation:
    - Uptrends use MACD LINE only (zero-line bounce handles pullbacks)
    - Downtrends require BOTH line < 0 AND histogram < 0
      When a downtrend exhausts, histogram turns positive first
      (selling momentum fading) while line is still negative.
      This catches downtrend-to-range transitions earlier.

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

    def detect_all(self, candles: np.ndarray) -> list:
        """Bulk detection: precompute indicators once, classify every bar.

        Returns a list of regime labels (one per candle). Early bars that lack
        sufficient data are None.
        """
        self.reset()
        n = len(candles)
        labels = [None] * n

        # Precompute all indicators once over the full array
        fast_ema_arr = ta.ema(candles, period=self.fast_period, sequential=True)
        slow_ema_arr = ta.ema(candles, period=self.slow_period, sequential=True)
        macd_result = ta.macd(candles, fast_period=self.macd_fast,
                              slow_period=self.macd_slow,
                              signal_period=self.macd_signal, sequential=True)
        macd_line_arr = macd_result[0]
        macd_hist_arr = macd_result[2]

        min_bars = max(self.slow_period, self.macd_slow + self.macd_signal) * 2
        # Walk bar-by-bar using precomputed values
        # detect() uses candles[:-1] (completed bars), so for bar i we classify i-1
        for i in range(1, n):
            if i < min_bars:
                continue
            # Classify on completed bar (index i-1, same as candles[:i+1][:-1][-1])
            idx = i - 1
            fast_ema = fast_ema_arr[idx]
            slow_ema = slow_ema_arr[idx]
            current_close = candles[idx, 2]
            macd_line = macd_line_arr[idx]
            macd_hist = macd_hist_arr[idx]

            if np.isnan(fast_ema) or np.isnan(slow_ema) or np.isnan(macd_line) or np.isnan(macd_hist) or np.isnan(current_close):
                raw = self._confirmed_regime or 'ranging-up'
            elif current_close <= 0:
                raw = self._confirmed_regime or 'ranging-up'
            else:
                separation = (fast_ema - slow_ema) / current_close * 100
                ema_bullish = separation > self.separation_pct
                ema_bearish = separation < -self.separation_pct

                if ema_bullish and macd_line > 0:
                    raw = 'trending-up'
                elif ema_bearish and macd_line < 0 and macd_hist < 0:
                    raw = 'trending-down'
                elif current_close >= slow_ema:
                    raw = 'ranging-up'
                else:
                    raw = 'ranging-down'

            labels[i] = self._apply_confirmation(raw)

        return labels

    def _classify(self, candles: np.ndarray) -> str:
        fast_ema = ta.ema(candles, period=self.fast_period, sequential=True)[-1]
        slow_ema = ta.ema(candles, period=self.slow_period, sequential=True)[-1]
        current_close = candles[-1, 2]

        # Asymmetric MACD confirmation:
        #
        # Uptrend:   MACD LINE > 0 confirms.
        #   Line stays positive during pullbacks (zero-line bounce).
        #   Only crosses zero when trend genuinely exhausts.
        #
        # Downtrend: MACD LINE < 0 AND HISTOGRAM < 0 confirms.
        #   When downtrend exhausts into range, histogram turns positive
        #   first (selling momentum fading), even while line is still
        #   negative. Requiring both catches exhaustion earlier.
        macd_result = ta.macd(candles, fast_period=self.macd_fast,
                              slow_period=self.macd_slow,
                              signal_period=self.macd_signal)
        macd_line = macd_result[0]
        macd_hist = macd_result[2]

        if np.isnan(fast_ema) or np.isnan(slow_ema) or np.isnan(macd_line) or np.isnan(macd_hist) or np.isnan(current_close):
            return self._confirmed_regime or 'ranging-up'

        if current_close <= 0:
            return self._confirmed_regime or 'ranging-up'

        separation = (fast_ema - slow_ema) / current_close * 100
        ema_bullish = separation > self.separation_pct
        ema_bearish = separation < -self.separation_pct

        if ema_bullish and macd_line > 0:
            return 'trending-up'
        elif ema_bearish and macd_line < 0 and macd_hist < 0:
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
