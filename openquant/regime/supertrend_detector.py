"""V5 SuperTrend regime detector.

Uses SuperTrend (ATR-based trailing stop) for fast direction detection,
ADX for trend strength gating, and Choppiness Index to filter noise.

Detection logic:
    TRENDING-UP:
        SuperTrend bullish (price > ST line)
        + ADX > adx_threshold (trend has strength)
        + CHOP < chop_trending (market is directional, not choppy)
        + close > SMA(trend_sma_period) (macro trend filter)

    TRENDING-DOWN:
        SuperTrend bearish (price < ST line)
        + ADX > adx_threshold
        + CHOP < chop_trending
        + close < SMA(trend_sma_period) (macro trend filter)

    RANGING:
        ADX < adx_threshold OR CHOP > chop_ranging (no trend strength or choppy)
        ranging-up if SuperTrend bullish, ranging-down if bearish

    EXIT:
        SuperTrend flips direction = exit to ranging
        ADX drops below threshold = exit to ranging
        CHOP rises above ranging threshold = exit to ranging

    MACRO TREND FILTER (SMA):
        Prevents trending-up when price is structurally below SMA
        (e.g., bear bounce in a sustained downtrend → downgrades to ranging-up).
        Prevents trending-down when price is structurally above SMA
        (e.g., bull dip in a sustained uptrend → downgrades to ranging-down).
        Controlled by use_trend_filter (default True) and trend_sma_period (default 50).

Why better than EMA-based detectors:
    - SuperTrend adapts to volatility via ATR (widens in vol, tightens in calm)
    - Flips in 1-3 bars vs EMA crossover taking 5-10 bars
    - CHOP filter prevents trading during choppy conditions
    - No MACD dependency (MACD is EMA of EMA — inherently lagging)
    - SMA macro filter prevents false regime flips during counter-trend bounces

Regimes:
    trending-up    — SuperTrend bullish + ADX confirms + not choppy + price > SMA
    trending-down  — SuperTrend bearish + ADX confirms + not choppy + price < SMA
    ranging-up     — weak trend or choppy + SuperTrend bullish
    ranging-down   — weak trend or choppy + SuperTrend bearish

Usage:
    detector = SuperTrendDetector(st_period=10, st_factor=3.0)
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


def _apply_sma_filter(raw_regime: str, close: float, sma_val: float) -> str:
    """Downgrade trending regimes when price disagrees with slow SMA.

    The SMA determines the macro direction. When a trend is downgraded,
    the ranging direction follows the SMA position (macro trend), not
    the local SuperTrend direction:

    - trending-up + close < SMA → ranging-down (structurally bearish)
    - trending-down + close > SMA → ranging-up (structurally bullish)
    - NaN SMA → no filter applied (insufficient data)
    """
    if np.isnan(sma_val):
        return raw_regime
    if raw_regime == 'trending-up' and close < sma_val:
        return 'ranging-down'
    if raw_regime == 'trending-down' and close > sma_val:
        return 'ranging-up'
    return raw_regime


class SuperTrendDetector:
    """Stateful SuperTrend + ADX + CHOP detector.

    Parameters
    ----------
    st_period : int
        SuperTrend ATR period. Default 10.
    st_factor : float
        SuperTrend ATR multiplier. Default 3.0.
    adx_period : int
        ADX calculation period. Default 14.
    adx_threshold : float
        Minimum ADX to classify as trending. Default 20.
    chop_period : int
        Choppiness Index period. Default 14.
    chop_ranging : float
        CHOP above this = ranging (choppy). Default 55.
    chop_trending : float
        CHOP below this = trending (directional). Default 45.
    confirm_bars : int
        Bars a new regime must hold before confirming. Default 1.
    timeframe : str
        Candle timeframe. Default '1D'.
    trend_sma_period : int
        Slow SMA period for macro trend filter. Default 100.
    use_trend_filter : bool
        Enable SMA macro trend filter. Default True.
    """

    def __init__(
        self,
        st_period: int = 10,
        st_factor: float = 3.0,
        adx_period: int = 14,
        adx_threshold: float = 25.0,
        chop_period: int = 14,
        chop_ranging: float = 55.0,
        chop_trending: float = 38.2,
        bull_entry_bars: int = 5,
        bull_exit_bars: int = 5,
        bear_entry_bars: int = 2,
        bear_exit_bars: int = 5,
        timeframe: str = '1D',
        trend_sma_period: int = 100,
        use_trend_filter: bool = True,
    ) -> None:
        self.st_period = st_period
        self.st_factor = st_factor
        self.adx_period = adx_period
        self.adx_threshold = adx_threshold
        self.chop_period = chop_period
        self.chop_ranging = chop_ranging
        self.chop_trending = chop_trending
        self.bull_entry_bars = bull_entry_bars
        self.bull_exit_bars = bull_exit_bars
        self.bear_entry_bars = bear_entry_bars
        self.bear_exit_bars = bear_exit_bars
        self.timeframe = timeframe
        self.trend_sma_period = trend_sma_period
        self.use_trend_filter = use_trend_filter

        self._confirmed_regime = None
        self._pending_regime: str | None = None
        self._pending_count = 0
        self._last_candle_timestamp = None

    @property
    def regime(self) -> str | None:
        return self._confirmed_regime

    def detect(self, candles: np.ndarray) -> str:
        """Classify the current market regime."""
        min_bars = max(self.st_period, self.adx_period, self.chop_period) * 3
        if candles is None or len(candles) < min_bars:
            raise ValueError(
                f'SuperTrendDetector needs at least {min_bars} candles '
                f'(got {len(candles) if candles is not None else 0}).'
            )

        last_completed_ts = candles[-2, 0] if len(candles) >= 2 else None
        if last_completed_ts == self._last_candle_timestamp and self._confirmed_regime is not None:
            return self._confirmed_regime
        self._last_candle_timestamp = last_completed_ts

        raw = self._classify(candles[:-1])
        return self._apply_confirmation(raw)

    def reset(self) -> None:
        self._confirmed_regime = None
        self._pending_regime = None
        self._pending_count = 0
        self._last_candle_timestamp = None

    def detect_all(self, candles: np.ndarray, debug: bool = False) -> list | tuple:
        """Bulk detection: precompute indicators once, classify every bar.

        When debug=True, returns (labels, debug_rows) where debug_rows is a
        list of dicts with per-bar indicator values for diagnosis.
        """
        self.reset()
        n = len(candles)
        labels = [None] * n
        debug_rows = [] if debug else None

        # Precompute all indicators once
        st_result = ta.supertrend(candles, period=self.st_period, factor=self.st_factor, sequential=True)
        st_trend_arr = st_result.trend
        adx_arr = ta.adx(candles, period=self.adx_period, sequential=True)
        chop_arr = ta.chop(candles, period=self.chop_period, sequential=True)
        sma_arr = (
            ta.sma(candles, period=self.trend_sma_period, sequential=True)
            if self.use_trend_filter else None
        )

        min_bars = max(self.st_period, self.adx_period, self.chop_period) * 3
        for i in range(1, n):
            if i < min_bars:
                continue
            idx = i - 1
            current_close = candles[idx, 2]
            st_trend = st_trend_arr[idx]
            adx_val = adx_arr[idx]
            chop_val = chop_arr[idx]

            if np.isnan(adx_val) or np.isnan(chop_val) or np.isnan(st_trend):
                raw = self._confirmed_regime or 'ranging-up'
            else:
                st_bullish = current_close > st_trend
                is_ranging = adx_val < self.adx_threshold and chop_val > self.chop_ranging

                if is_ranging:
                    raw = 'ranging-up' if st_bullish else 'ranging-down'
                else:
                    raw = 'trending-up' if st_bullish else 'trending-down'
                    if sma_arr is not None:
                        raw = _apply_sma_filter(raw, current_close, sma_arr[idx])

            labels[i] = self._apply_confirmation(raw)

            if debug:
                debug_rows.append({
                    'ts': candles[idx, 0],
                    'close': current_close,
                    'st_trend': st_trend,
                    'st_bullish': current_close > st_trend if not np.isnan(st_trend) else None,
                    'adx': adx_val,
                    'chop': chop_val,
                    'sma': sma_arr[idx] if sma_arr is not None else None,
                    'raw': raw,
                    'confirmed': labels[i],
                })

        if debug:
            return labels, debug_rows
        return labels

    def _classify(self, candles: np.ndarray) -> str:
        current_close = candles[-1, 2]

        # SuperTrend — fast direction via ATR-based trailing stop
        st = ta.supertrend(candles, period=self.st_period, factor=self.st_factor)
        st_bullish = current_close > st.trend

        # ADX — trend strength
        adx_val = ta.adx(candles, period=self.adx_period)

        # Choppiness Index — is market choppy or directional?
        chop_val = ta.chop(candles, period=self.chop_period)

        if np.isnan(adx_val) or np.isnan(chop_val) or np.isnan(st.trend):
            return self._confirmed_regime or 'ranging-up'

        # SuperTrend direction IS the trend. It already incorporates ATR
        # (volatility-adaptive) and only flips on meaningful breaks.
        #
        # ADX/CHOP distinguish ranging (choppy, no direction) from trending:
        # - Ranging: ADX low AND CHOP high (both say "no trend")
        # - Trending: everything else (SuperTrend already picked the direction)
        is_ranging = adx_val < self.adx_threshold and chop_val > self.chop_ranging

        if is_ranging:
            return 'ranging-up' if st_bullish else 'ranging-down'

        raw = 'trending-up' if st_bullish else 'trending-down'

        # SMA macro trend filter — prevent false regime flips during
        # counter-trend bounces (e.g., bear bounce → false trending-up)
        if self.use_trend_filter:
            sma_val = ta.sma(candles, period=self.trend_sma_period)
            raw = _apply_sma_filter(raw, current_close, sma_val)

        return raw

    def _apply_confirmation(self, raw_regime: str) -> str:
        """Directional asymmetric confirmation.

        Bull and bear trends have different characteristics:

        Bull entry:  SLOW (5 bars) — bulls build gradually, a +5% day isn't a trend
        Bull exit:   SLOW (5 bars) — pullbacks of 10-15% are normal in bull trends
        Bear entry:  FAST (2 bars) — crashes start sharp, need to catch them quick
        Bear exit:   SLOW (5 bars) — dead cat bounces are traps

        Ranging transitions are fast (1-2 bars).
        """
        if self._confirmed_regime is None:
            self._confirmed_regime = raw_regime
            return raw_regime

        if raw_regime == self._confirmed_regime:
            self._pending_regime = None
            self._pending_count = 0
            return self._confirmed_regime

        # Determine required confirmation bars based on the transition
        required = self._get_required_bars(self._confirmed_regime, raw_regime)

        if required <= 0:
            self._confirmed_regime = raw_regime
            return raw_regime

        if raw_regime == self._pending_regime:
            self._pending_count += 1
        else:
            self._pending_regime = raw_regime
            self._pending_count = 1

        if self._pending_count >= required:
            self._confirmed_regime = raw_regime
            self._pending_regime = None
            self._pending_count = 0

        return self._confirmed_regime

    def _get_required_bars(self, old: str, new: str) -> int:
        """Get confirmation bars for a specific transition."""
        # Entering trending-up (from anything)
        if new == 'trending-up':
            return self.bull_entry_bars

        # Entering trending-down (from anything)
        if new == 'trending-down':
            return self.bear_entry_bars

        # Exiting trending-up (to anything)
        if old == 'trending-up':
            return self.bull_exit_bars

        # Exiting trending-down (to anything)
        if old == 'trending-down':
            return self.bear_exit_bars

        # Ranging ↔ ranging transitions: fast
        return 1
