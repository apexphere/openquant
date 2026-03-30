"""V5 SuperTrend regime detector.

Uses SuperTrend (ATR-based trailing stop) for fast direction detection,
ADX for trend strength gating, and Choppiness Index to filter noise.

Detection logic:
    TRENDING-UP:
        SuperTrend bullish (price > ST line)
        + ADX > adx_threshold (trend has strength)
        + CHOP < chop_trending (market is directional, not choppy)

    TRENDING-DOWN:
        SuperTrend bearish (price < ST line)
        + ADX > adx_threshold
        + CHOP < chop_trending

    RANGING:
        ADX < adx_threshold OR CHOP > chop_ranging (no trend strength or choppy)
        ranging-up if SuperTrend bullish, ranging-down if bearish

    EXIT:
        SuperTrend flips direction = exit to ranging
        ADX drops below threshold = exit to ranging
        CHOP rises above ranging threshold = exit to ranging

Why better than EMA-based detectors:
    - SuperTrend adapts to volatility via ATR (widens in vol, tightens in calm)
    - Flips in 1-3 bars vs EMA crossover taking 5-10 bars
    - CHOP filter prevents trading during choppy conditions
    - No MACD dependency (MACD is EMA of EMA — inherently lagging)

Regimes:
    trending-up    — SuperTrend bullish + ADX confirms + not choppy
    trending-down  — SuperTrend bearish + ADX confirms + not choppy
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
        confirm_bars: int = 2,
        exit_confirm_bars: int = 5,
        timeframe: str = '1D',
    ) -> None:
        self.st_period = st_period
        self.st_factor = st_factor
        self.adx_period = adx_period
        self.adx_threshold = adx_threshold
        self.chop_period = chop_period
        self.chop_ranging = chop_ranging
        self.chop_trending = chop_trending
        self.confirm_bars = confirm_bars
        self.exit_confirm_bars = exit_confirm_bars
        self.timeframe = timeframe

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

        # Is the market trending? ADX confirms strength OR CHOP confirms direction
        # Both are trend filters — either one is enough evidence
        has_trend_strength = adx_val > self.adx_threshold or chop_val < self.chop_trending

        if has_trend_strength:
            return 'trending-up' if st_bullish else 'trending-down'
        else:
            return 'ranging-up' if st_bullish else 'ranging-down'

    def _apply_confirmation(self, raw_regime: str) -> str:
        """Asymmetric confirmation: easy to enter trends, hard to exit.

        Entry (ranging → trending): confirm_bars
        Exit (trending → anything else): exit_confirm_bars (higher)

        A confirmed trend is assumed to continue until strongly proven
        otherwise. A small bounce shouldn't kill a bear trend.
        """
        if self._confirmed_regime is None:
            self._confirmed_regime = raw_regime
            return raw_regime

        if raw_regime == self._confirmed_regime:
            self._pending_regime = None
            self._pending_count = 0
            return self._confirmed_regime

        # How many bars to confirm this change?
        is_trend_exit = self._confirmed_regime in ('trending-up', 'trending-down')
        required = self.exit_confirm_bars if is_trend_exit else self.confirm_bars

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
