"""V6 SuperTrend regime detector — confidence-based smoothing.

Replaces V5's confirmation counter with a continuous confidence score
derived from weighted indicator signals + exponential smoothing. This
eliminates the oscillation deadlock bug where alternating raw signals
reset the counter indefinitely.

Core concept:
    Each bar, 4 indicators are normalized to a bullish confidence
    score (0.0 = max bearish, 1.0 = max bullish). A weighted sum
    produces raw_confidence, which is exponentially smoothed for
    inertia. The smoothed score is mapped to regime tiers via
    hysteresis thresholds.

Signals (default weights):
    SuperTrend direction (0.40) — binary 1.0/0.0
    ADX strength (0.20)        — clamp((adx - 15) / 30, 0, 1)
    CHOP directionality (0.15) — clamp((70 - chop) / 30, 0, 1)
    SMA position (0.25)        — distance-weighted, ATR-normalized

Smoothing:
    smoothed = alpha * raw + (1 - alpha) * prev_smoothed
    alpha = 0.3 (default), alpha_boost = 0.6 when breaking out of ranging

Tier thresholds (with hysteresis):
    Strong trending: enter > 0.70, exit < 0.55
    Weak trending:   enter > 0.40, exit < 0.25
    Ranging:         default state
    Chaotic:         4+ direction flips in 10 bars AND elevated ATR

Output labels:
    trending-up, trending-down, ranging-up, ranging-down, chaotic

Usage:
    detector = SuperTrendDetectorV6()
    regime = detector.detect(daily_candles)
"""
from collections import deque

import numpy as np
import openquant.indicators as ta


REGIMES = frozenset({
    'trending-up',
    'trending-down',
    'ranging-up',
    'ranging-down',
    'chaotic',
})


def _clamp(value: float, lo: float, hi: float) -> float:
    """Clamp a value between lo and hi."""
    if value < lo:
        return lo
    if value > hi:
        return hi
    return value


def _normalize_st(close: float, st_trend: float) -> float:
    """SuperTrend direction: binary 1.0 (bullish) or 0.0 (bearish)."""
    return 1.0 if close > st_trend else 0.0


def _normalize_adx(adx_val: float) -> float:
    """ADX strength: maps 15-45 to 0-1. Note: ADX measures strength
    regardless of direction, so high ADX = strong trend (bullish for
    the confidence score when combined with direction)."""
    return _clamp((adx_val - 15.0) / 30.0, 0.0, 1.0)


def _normalize_chop(chop_val: float) -> float:
    """CHOP directionality: maps 40-70 to 1-0 (inverted).
    Low CHOP = directional = high confidence."""
    return _clamp((70.0 - chop_val) / 30.0, 0.0, 1.0)


def _normalize_sma(close: float, sma_val: float, atr_val: float) -> float:
    """SMA position: distance-weighted, ATR-normalized.
    Returns 0-1 where 0.5 = at SMA, 1.0 = far above, 0.0 = far below."""
    if np.isnan(sma_val) or atr_val < 1e-10:
        return 0.5
    raw = _clamp((close - sma_val) / (atr_val * 3.0), -1.0, 1.0)
    return raw * 0.5 + 0.5


def _compute_raw_confidence(
    st_signal: float, adx_signal: float, chop_signal: float, sma_signal: float,
    w_st: float, w_adx: float, w_chop: float, w_sma: float,
) -> float:
    """Weighted sum of normalized signals.

    ADX and CHOP are strength/directionality signals, not direction signals.
    They modify confidence magnitude: when SuperTrend is bearish (st=0.0),
    high ADX should INCREASE bearish confidence (push toward 0.0), not
    toward 1.0. We achieve this by using ADX/CHOP as multipliers on
    the directional component.
    """
    # Direction signals (have bull/bear polarity)
    direction_score = w_st * st_signal + w_sma * sma_signal

    # Strength signals (amplify or dampen the directional conviction)
    # When strength is high, push confidence toward the extreme (0 or 1)
    # When strength is low, push confidence toward 0.5 (neutral)
    strength = (w_adx * adx_signal + w_chop * chop_signal)
    strength_weight = w_adx + w_chop

    # Normalize direction component to 0-1 range within its weight budget
    dir_weight = w_st + w_sma
    if dir_weight > 0:
        dir_normalized = direction_score / dir_weight
    else:
        dir_normalized = 0.5

    # Blend: strength signals scale how far from 0.5 we go
    # strength=1.0 → full directional conviction
    # strength=0.0 → pulled toward 0.5 (ranging)
    if strength_weight > 0:
        avg_strength = strength / strength_weight
    else:
        avg_strength = 0.5

    # Final confidence: direction component weighted by total,
    # with strength modulating distance from neutral
    base = dir_normalized
    modulated = 0.5 + (base - 0.5) * (0.5 + 0.5 * avg_strength)

    return _clamp(modulated, 0.0, 1.0)


def _count_flips(history: deque) -> int:
    """Count direction flips (0.5-crossings) in the confidence history."""
    if len(history) < 2:
        return 0
    flips = 0
    prev_bull = history[0] > 0.5
    for val in list(history)[1:]:
        curr_bull = val > 0.5
        if curr_bull != prev_bull:
            flips += 1
            prev_bull = curr_bull
    return flips


class SuperTrendDetectorV6:
    """Confidence-based SuperTrend regime detector.

    Parameters
    ----------
    st_period : int
        SuperTrend ATR period. Default 10.
    st_factor : float
        SuperTrend ATR multiplier. Default 3.0.
    adx_period : int
        ADX calculation period. Default 14.
    chop_period : int
        Choppiness Index period. Default 14.
    trend_sma_period : int
        Slow SMA period for structural bias. Default 100.
    timeframe : str
        Candle timeframe. Default '1D'.
    alpha : float
        Smoothing factor (0-1, higher = more responsive). Default 0.3.
    alpha_boost : float
        Smoothing factor for ranging-to-trending breakouts. Default 0.6.
    strong_entry : float
        Directional strength to enter strong trending. Default 0.70.
    strong_exit : float
        Directional strength to exit strong trending. Default 0.55.
    weak_entry : float
        Directional strength to enter weak trending. Default 0.40.
    weak_exit : float
        Directional strength to exit weak trending. Default 0.25.
    chaos_flips : int
        Direction flips in 10 bars to trigger chaotic. Default 4.
    chaos_atr_pct : float
        ATR percentile threshold for chaotic. Default 0.60.
    w_st : float
        SuperTrend weight. Default 0.40.
    w_adx : float
        ADX weight. Default 0.20.
    w_chop : float
        CHOP weight. Default 0.15.
    w_sma : float
        SMA weight. Default 0.25.
    """

    def __init__(
        self,
        st_period: int = 10,
        st_factor: float = 3.0,
        adx_period: int = 14,
        chop_period: int = 14,
        trend_sma_period: int = 100,
        timeframe: str = '1D',
        alpha: float = 0.3,
        alpha_boost: float = 0.6,
        strong_entry: float = 0.70,
        strong_exit: float = 0.55,
        weak_entry: float = 0.40,
        weak_exit: float = 0.25,
        chaos_flips: int = 4,
        chaos_atr_pct: float = 0.60,
        w_st: float = 0.40,
        w_adx: float = 0.20,
        w_chop: float = 0.15,
        w_sma: float = 0.25,
    ) -> None:
        self.st_period = st_period
        self.st_factor = st_factor
        self.adx_period = adx_period
        self.chop_period = chop_period
        self.trend_sma_period = trend_sma_period
        self.timeframe = timeframe
        self.alpha = alpha
        self.alpha_boost = alpha_boost
        self.strong_entry = strong_entry
        self.strong_exit = strong_exit
        self.weak_entry = weak_entry
        self.weak_exit = weak_exit
        self.chaos_flips = chaos_flips
        self.chaos_atr_pct = chaos_atr_pct
        self.w_st = w_st
        self.w_adx = w_adx
        self.w_chop = w_chop
        self.w_sma = w_sma

        self._smoothed_confidence: float = 0.5
        self._current_tier: str = 'ranging'
        self._current_direction: str = 'bull'
        self._raw_confidence_history: deque = deque(maxlen=10)
        self._confirmed_regime: str | None = None
        self._last_candle_timestamp = None
        self._atr_history: deque = deque(maxlen=50)

    @property
    def regime(self) -> str | None:
        return self._confirmed_regime

    def reset(self) -> None:
        """Clear all internal state."""
        self._smoothed_confidence = 0.5
        self._current_tier = 'ranging'
        self._current_direction = 'bull'
        self._raw_confidence_history = deque(maxlen=10)
        self._confirmed_regime = None
        self._last_candle_timestamp = None
        self._atr_history = deque(maxlen=50)

    def detect(self, candles: np.ndarray) -> str:
        """Classify the current market regime from candle data."""
        min_bars = max(self.st_period, self.adx_period, self.chop_period) * 3
        if candles is None or len(candles) < min_bars:
            raise ValueError(
                f'SuperTrendDetectorV6 needs at least {min_bars} candles '
                f'(got {len(candles) if candles is not None else 0}).'
            )

        last_completed_ts = candles[-2, 0] if len(candles) >= 2 else None
        if last_completed_ts == self._last_candle_timestamp and self._confirmed_regime is not None:
            return self._confirmed_regime
        self._last_candle_timestamp = last_completed_ts

        completed = candles[:-1]
        raw_conf = self._compute_bar_confidence(completed)
        regime = self._update_state(raw_conf)
        return regime

    def detect_all(self, candles: np.ndarray, debug: bool = False) -> list | tuple:
        """Bulk detection: precompute indicators once, classify every bar.

        When debug=True, returns (labels, debug_rows) where debug_rows
        contains per-bar confidence data for diagnosis.
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
        sma_arr = ta.sma(candles, period=self.trend_sma_period, sequential=True)
        atr_arr = ta.atr(candles, period=self.st_period, sequential=True)

        min_bars = max(self.st_period, self.adx_period, self.chop_period) * 3
        for i in range(1, n):
            if i < min_bars:
                continue
            idx = i - 1  # Use completed bar (not the forming bar)
            close = candles[idx, 2]
            st_trend = st_trend_arr[idx]
            adx_val = adx_arr[idx]
            chop_val = chop_arr[idx]
            sma_val = sma_arr[idx]
            atr_val = atr_arr[idx]

            if np.isnan(adx_val) or np.isnan(chop_val) or np.isnan(st_trend):
                labels[i] = self._confirmed_regime or 'ranging-up'
                continue

            raw_conf = self._compute_signals_to_confidence(
                close, st_trend, adx_val, chop_val, sma_val, atr_val
            )
            labels[i] = self._update_state(raw_conf, atr_val)

            if debug:
                debug_rows.append({
                    'ts': candles[idx, 0],
                    'close': close,
                    'st_trend': st_trend,
                    'st_bullish': close > st_trend,
                    'adx': adx_val,
                    'chop': chop_val,
                    'sma': sma_val,
                    'atr': atr_val,
                    'raw_confidence': raw_conf,
                    'smoothed_confidence': self._smoothed_confidence,
                    'directional_strength': abs(self._smoothed_confidence - 0.5) * 2,
                    'current_tier': self._current_tier,
                    'raw': self._format_regime(
                        'bull' if raw_conf > 0.5 else 'bear',
                        self._current_tier,
                    ),
                    'confirmed': labels[i],
                })

        if debug:
            return labels, debug_rows
        return labels

    def _compute_bar_confidence(self, candles: np.ndarray) -> float:
        """Compute raw confidence from indicators for the last completed bar."""
        close = candles[-1, 2]
        st = ta.supertrend(candles, period=self.st_period, factor=self.st_factor)
        adx_val = ta.adx(candles, period=self.adx_period)
        chop_val = ta.chop(candles, period=self.chop_period)
        sma_val = ta.sma(candles, period=self.trend_sma_period)
        atr_val = ta.atr(candles, period=self.st_period)

        if np.isnan(adx_val) or np.isnan(chop_val) or np.isnan(st.trend):
            return 0.5

        return self._compute_signals_to_confidence(
            close, st.trend, adx_val, chop_val, sma_val, atr_val
        )

    def _compute_signals_to_confidence(
        self, close: float, st_trend: float, adx_val: float,
        chop_val: float, sma_val: float, atr_val: float,
    ) -> float:
        """Normalize indicators and compute weighted confidence."""
        st_signal = _normalize_st(close, st_trend)
        adx_signal = _normalize_adx(adx_val)
        chop_signal = _normalize_chop(chop_val)
        sma_signal = _normalize_sma(close, sma_val, atr_val)

        return _compute_raw_confidence(
            st_signal, adx_signal, chop_signal, sma_signal,
            self.w_st, self.w_adx, self.w_chop, self.w_sma,
        )

    def _update_state(self, raw_confidence: float, atr_val: float = None) -> str:
        """Apply smoothing, classify tier, and return regime label."""
        self._raw_confidence_history.append(raw_confidence)

        # Track ATR for chaotic percentile calculation
        if atr_val is not None:
            self._atr_history.append(atr_val)

        # Choose alpha: boosted when breaking out of ranging
        alpha = self._choose_alpha(raw_confidence)

        # Exponential smoothing
        self._smoothed_confidence = (
            alpha * raw_confidence + (1.0 - alpha) * self._smoothed_confidence
        )

        # Direction
        self._current_direction = 'bull' if self._smoothed_confidence > 0.5 else 'bear'
        directional_strength = abs(self._smoothed_confidence - 0.5) * 2.0

        # Check chaotic first (circuit breaker)
        if self._is_chaotic(atr_val):
            self._current_tier = 'chaotic'
            self._confirmed_regime = 'chaotic'
            return 'chaotic'

        # Exit chaotic only when stable
        if self._current_tier == 'chaotic':
            if not self._can_exit_chaotic(directional_strength):
                self._confirmed_regime = 'chaotic'
                return 'chaotic'

        # Apply hysteresis thresholds
        self._current_tier = self._classify_tier(directional_strength)
        self._confirmed_regime = self._format_regime(
            self._current_direction, self._current_tier,
        )
        return self._confirmed_regime

    def _choose_alpha(self, raw_confidence: float) -> float:
        """Select smoothing factor. Use boosted alpha for ranging breakouts."""
        if self._current_tier != 'ranging':
            return self.alpha
        raw_directional = abs(raw_confidence - 0.5) * 2.0
        if raw_directional > 0.60:
            return self.alpha_boost
        return self.alpha

    def _classify_tier(self, directional_strength: float) -> str:
        """Map directional strength to tier with hysteresis."""
        tier = self._current_tier

        if tier == 'strong_trending':
            if directional_strength < self.strong_exit:
                tier = 'weak_trending' if directional_strength >= self.weak_exit else 'ranging'
        elif tier == 'weak_trending':
            if directional_strength >= self.strong_entry:
                tier = 'strong_trending'
            elif directional_strength < self.weak_exit:
                tier = 'ranging'
        elif tier == 'ranging' or tier == 'chaotic':
            if directional_strength >= self.strong_entry:
                tier = 'strong_trending'
            elif directional_strength >= self.weak_entry:
                tier = 'weak_trending'
            else:
                tier = 'ranging'

        return tier

    def _is_chaotic(self, atr_val: float | None) -> bool:
        """Check if market is chaotic: rapid flips + elevated ATR."""
        flips = _count_flips(self._raw_confidence_history)
        if flips < self.chaos_flips:
            return False

        # Check ATR percentile
        if atr_val is None or len(self._atr_history) < 10:
            return False
        sorted_atr = sorted(self._atr_history)
        percentile_idx = int(len(sorted_atr) * self.chaos_atr_pct)
        threshold = sorted_atr[min(percentile_idx, len(sorted_atr) - 1)]
        return atr_val >= threshold

    def _can_exit_chaotic(self, directional_strength: float) -> bool:
        """Conservative exit from chaotic: low flips + some directional strength."""
        flips = _count_flips(self._raw_confidence_history)
        return flips < 2 and directional_strength > 0.30

    @staticmethod
    def _format_regime(direction: str, tier: str) -> str:
        """Map internal direction + tier to output regime label."""
        if tier == 'chaotic':
            return 'chaotic'
        suffix = 'up' if direction == 'bull' else 'down'
        if tier in ('strong_trending', 'weak_trending'):
            return f'trending-{suffix}'
        return f'ranging-{suffix}'
