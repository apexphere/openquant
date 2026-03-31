"""V7 SuperTrend regime detector — SMA dominance gate.

Extends V6 with a macro trend gate: price vs SMA(100) determines
the dominant direction. Trending labels are only allowed when the
confidence system AND the macro direction agree.

Key change from V6:
    If price is below SMA → macro trend is bearish:
        - trending-up is BLOCKED (forced to ranging-up at most)
        - trending-down is the natural dominant state
    If price is above SMA → macro trend is bullish:
        - trending-down is BLOCKED (forced to ranging-down at most)
        - trending-up is the natural dominant state

This makes ranging the dominant label (where markets spend most time)
and reserves trending for periods where both micro signals AND macro
structure agree. Prevents false trending-up labels during bear market
rallies and false trending-down during bull pullbacks.

All V6 features preserved:
    - Confidence-based smoothing with exponential alpha
    - 2-bar minimum hold to prevent flickering
    - Forced ranging transition between opposite trending
    - Price circuit breaker for crash protection
    - Chaotic detection
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
    if value < lo:
        return lo
    if value > hi:
        return hi
    return value


def _normalize_st(close: float, st_trend: float) -> float:
    return 1.0 if close > st_trend else 0.0


def _normalize_adx(adx_val: float) -> float:
    return _clamp((adx_val - 15.0) / 30.0, 0.0, 1.0)


def _normalize_chop(chop_val: float) -> float:
    return _clamp((70.0 - chop_val) / 30.0, 0.0, 1.0)


def _normalize_sma(close: float, sma_val: float, atr_val: float) -> float:
    if np.isnan(sma_val) or atr_val < 1e-10:
        return 0.5
    raw = _clamp((close - sma_val) / (atr_val * 3.0), -1.0, 1.0)
    return raw * 0.5 + 0.5


def _compute_raw_confidence(
    st_signal: float, adx_signal: float, chop_signal: float, sma_signal: float,
    w_st: float, w_adx: float, w_chop: float, w_sma: float,
) -> float:
    direction_score = w_st * st_signal + w_sma * sma_signal
    strength = (w_adx * adx_signal + w_chop * chop_signal)
    strength_weight = w_adx + w_chop
    dir_weight = w_st + w_sma

    if dir_weight > 0:
        dir_normalized = direction_score / dir_weight
    else:
        dir_normalized = 0.5

    if strength_weight > 0:
        avg_strength = strength / strength_weight
    else:
        avg_strength = 0.5

    base = dir_normalized
    modulated = 0.5 + (base - 0.5) * (0.3 + 0.7 * avg_strength)
    return _clamp(modulated, 0.0, 1.0)


def _count_flips(history: deque) -> int:
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


class SuperTrendDetectorV7:
    """Confidence-based SuperTrend regime detector with SMA dominance gate.

    Extends V6: trending labels are only allowed when the macro trend
    (price vs SMA) agrees with the confidence direction. This makes
    ranging the dominant state and prevents false trending labels during
    counter-macro moves.

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
        Slow SMA period for macro trend gate. Default 100.
    timeframe : str
        Candle timeframe. Default '1D'.
    alpha : float
        Smoothing factor (0-1, higher = more responsive). Default 0.3.
    alpha_boost : float
        Smoothing factor for breakouts and contradictions. Default 0.6.
    strong_entry : float
        Directional strength to enter strong trending. Default 0.70.
    strong_exit : float
        Directional strength to exit strong trending. Default 0.55.
    weak_entry : float
        Directional strength to enter weak trending. Default 0.40.
    weak_exit : float
        Directional strength to exit weak trending. Default 0.35.
    chaos_flips : int
        Direction flips in 10 bars to trigger chaotic. Default 4.
    chaos_atr_pct : float
        ATR percentile threshold for chaotic. Default 0.60.
    circuit_breaker_atr : float
        ATR multiplier for price circuit breaker. Default 1.5.
    w_st : float
        SuperTrend weight. Default 0.40.
    w_adx : float
        ADX weight. Default 0.30.
    w_chop : float
        CHOP weight. Default 0.15.
    w_sma : float
        SMA weight. Default 0.15.
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
        weak_exit: float = 0.35,
        chaos_flips: int = 4,
        chaos_atr_pct: float = 0.60,
        circuit_breaker_atr: float = 1.5,
        w_st: float = 0.40,
        w_adx: float = 0.30,
        w_chop: float = 0.15,
        w_sma: float = 0.15,
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
        self.circuit_breaker_atr = circuit_breaker_atr
        self.w_st = w_st
        self.w_adx = w_adx
        self.w_chop = w_chop
        self.w_sma = w_sma

        self._smoothed_confidence: float = 0.5
        self._current_tier: str = 'ranging'
        self._current_direction: str = 'bull'
        self._raw_confidence_history: deque = deque(maxlen=10)
        self._confirmed_regime: str | None = None
        self._pending_regime: str | None = None
        self._pending_regime_bars: int = 0
        self._last_candle_timestamp = None
        self._atr_history: deque = deque(maxlen=50)
        self._trending_entry_price: float | None = None
        self._prev_st_bullish = None
        self._last_sma_val: float | None = None

    @property
    def regime(self) -> str | None:
        return self._confirmed_regime

    def reset(self) -> None:
        self._smoothed_confidence = 0.5
        self._current_tier = 'ranging'
        self._current_direction = 'bull'
        self._raw_confidence_history = deque(maxlen=10)
        self._confirmed_regime = None
        self._pending_regime = None
        self._pending_regime_bars = 0
        self._last_candle_timestamp = None
        self._atr_history = deque(maxlen=50)
        self._trending_entry_price = None
        self._prev_st_bullish = None
        self._last_sma_val = None

    def detect(self, candles: np.ndarray) -> str:
        min_bars = max(self.st_period, self.adx_period, self.chop_period) * 3
        if candles is None or len(candles) < min_bars:
            raise ValueError(
                f'SuperTrendDetectorV7 needs at least {min_bars} candles '
                f'(got {len(candles) if candles is not None else 0}).'
            )

        last_completed_ts = candles[-2, 0] if len(candles) >= 2 else None
        if last_completed_ts == self._last_candle_timestamp and self._confirmed_regime is not None:
            return self._confirmed_regime
        self._last_candle_timestamp = last_completed_ts

        completed = candles[:-1]
        close = completed[-1, 2]
        raw_conf = self._compute_bar_confidence(completed)
        return self._update_state(raw_conf, close=close)

    def detect_all(self, candles: np.ndarray, debug: bool = False) -> list | tuple:
        self.reset()
        n = len(candles)
        labels = [None] * n
        debug_rows = [] if debug else None

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
            idx = i - 1
            close = candles[idx, 2]
            st_trend = st_trend_arr[idx]
            adx_val = adx_arr[idx]
            chop_val = chop_arr[idx]
            sma_val = sma_arr[idx]
            atr_val = atr_arr[idx]

            if np.isnan(adx_val) or np.isnan(chop_val) or np.isnan(st_trend):
                labels[i] = self._confirmed_regime or 'ranging-up'
                continue

            self._last_sma_val = sma_val

            raw_conf = self._compute_signals_to_confidence(
                close, st_trend, adx_val, chop_val, sma_val, atr_val
            )
            labels[i] = self._update_state(raw_conf, atr_val, close=close)

            if debug:
                macro = 'bullish' if close > sma_val else 'bearish'
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
                    'macro_trend': macro,
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
        close = candles[-1, 2]
        st = ta.supertrend(candles, period=self.st_period, factor=self.st_factor)
        adx_val = ta.adx(candles, period=self.adx_period)
        chop_val = ta.chop(candles, period=self.chop_period)
        sma_val = ta.sma(candles, period=self.trend_sma_period)
        atr_val = ta.atr(candles, period=self.st_period)

        if np.isnan(adx_val) or np.isnan(chop_val) or np.isnan(st.trend):
            return 0.5

        self._last_sma_val = sma_val

        return self._compute_signals_to_confidence(
            close, st.trend, adx_val, chop_val, sma_val, atr_val
        )

    def _compute_signals_to_confidence(
        self, close: float, st_trend: float, adx_val: float,
        chop_val: float, sma_val: float, atr_val: float,
    ) -> float:
        st_signal = _normalize_st(close, st_trend)
        adx_signal = _normalize_adx(adx_val)
        chop_signal = _normalize_chop(chop_val)
        sma_signal = _normalize_sma(close, sma_val, atr_val)

        return _compute_raw_confidence(
            st_signal, adx_signal, chop_signal, sma_signal,
            self.w_st, self.w_adx, self.w_chop, self.w_sma,
        )

    def _macro_trend(self, close: float) -> str:
        """Determine macro trend from price vs SMA."""
        if self._last_sma_val is None or np.isnan(self._last_sma_val):
            return 'neutral'
        if close > self._last_sma_val:
            return 'bullish'
        return 'bearish'

    def _apply_dominance_gate(self, candidate: str, close: float) -> str:
        """Block trending labels that contradict the macro trend.

        If macro is bearish (price < SMA): trending-up → ranging-up
        If macro is bullish (price > SMA): trending-down → ranging-down
        """
        macro = self._macro_trend(close)
        if macro == 'bearish' and candidate == 'trending-up':
            return 'ranging-up'
        if macro == 'bullish' and candidate == 'trending-down':
            return 'ranging-down'
        return candidate

    def _update_state(self, raw_confidence: float, atr_val: float = None, close: float = None) -> str:
        self._raw_confidence_history.append(raw_confidence)

        if atr_val is not None:
            self._atr_history.append(atr_val)

        alpha = self._choose_alpha(raw_confidence)
        self._smoothed_confidence = (
            alpha * raw_confidence + (1.0 - alpha) * self._smoothed_confidence
        )

        self._current_direction = 'bull' if self._smoothed_confidence > 0.5 else 'bear'
        directional_strength = abs(self._smoothed_confidence - 0.5) * 2.0

        # Chaotic check
        if self._is_chaotic(atr_val):
            self._current_tier = 'chaotic'
            self._confirmed_regime = 'chaotic'
            return 'chaotic'

        if self._current_tier == 'chaotic':
            if not self._can_exit_chaotic(directional_strength):
                self._confirmed_regime = 'chaotic'
                return 'chaotic'

        # Hysteresis tier classification
        self._current_tier = self._classify_tier(directional_strength)
        candidate = self._format_regime(
            self._current_direction, self._current_tier,
        )

        # Dominance gate: block trending against macro trend
        if close is not None:
            candidate = self._apply_dominance_gate(candidate, close)

        # Transition guard: no direct trending↔trending
        candidate = self._apply_transition_guard(candidate)

        # 2-bar minimum hold
        prev_confirmed = self._confirmed_regime
        if self._confirmed_regime is None:
            self._confirmed_regime = candidate
        elif candidate == self._confirmed_regime:
            self._pending_regime = None
            self._pending_regime_bars = 0
        elif candidate == self._pending_regime:
            self._pending_regime_bars += 1
            if self._pending_regime_bars >= 2:
                self._confirmed_regime = candidate
                self._pending_regime = None
                self._pending_regime_bars = 0
        else:
            self._pending_regime = candidate
            self._pending_regime_bars = 1

        # Track entry price for circuit breaker
        if self._confirmed_regime != prev_confirmed:
            if self._confirmed_regime in ('trending-up', 'trending-down'):
                self._trending_entry_price = close
            else:
                self._trending_entry_price = None

        # Price circuit breaker
        breaker_result = self._check_circuit_breaker(close)
        if breaker_result is not None:
            self._confirmed_regime = breaker_result
            self._pending_regime = None
            self._pending_regime_bars = 0
            self._trending_entry_price = None

        return self._confirmed_regime

    def _choose_alpha(self, raw_confidence: float) -> float:
        if self._current_tier == 'ranging':
            raw_directional = abs(raw_confidence - 0.5) * 2.0
            if raw_directional > 0.40:
                return self.alpha_boost
            return self.alpha

        if self._current_tier in ('weak_trending', 'strong_trending'):
            if self._current_direction == 'bull':
                contradiction = 0.5 - raw_confidence
            else:
                contradiction = raw_confidence - 0.5
            if contradiction > 0.25:
                return self.alpha_boost

        return self.alpha

    def _classify_tier(self, directional_strength: float) -> str:
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
        flips = _count_flips(self._raw_confidence_history)
        if flips < self.chaos_flips:
            return False
        if atr_val is None or len(self._atr_history) < 10:
            return False
        sorted_atr = sorted(self._atr_history)
        percentile_idx = int(len(sorted_atr) * self.chaos_atr_pct)
        threshold = sorted_atr[min(percentile_idx, len(sorted_atr) - 1)]
        return atr_val >= threshold

    def _can_exit_chaotic(self, directional_strength: float) -> bool:
        flips = _count_flips(self._raw_confidence_history)
        return flips < 2 and directional_strength > 0.30

    def _check_circuit_breaker(self, close: float | None) -> str | None:
        if (
            close is None
            or self._trending_entry_price is None
            or not self._atr_history
            or self._confirmed_regime not in ('trending-up', 'trending-down')
        ):
            return None

        atr = self._atr_history[-1]
        threshold = self.circuit_breaker_atr * atr

        if self._confirmed_regime == 'trending-up':
            if self._trending_entry_price - close > threshold:
                return 'ranging-down'
        elif self._confirmed_regime == 'trending-down':
            if close - self._trending_entry_price > threshold:
                return 'ranging-up'

        return None

    _OPPOSITE_TRENDING = {
        ('trending-up', 'trending-down'),
        ('trending-down', 'trending-up'),
    }

    def _apply_transition_guard(self, candidate: str) -> str:
        if self._confirmed_regime is None:
            return candidate
        pair = (self._confirmed_regime, candidate)
        if pair in self._OPPOSITE_TRENDING:
            suffix = candidate.split('-')[1]
            return f'ranging-{suffix}'
        return candidate

    @staticmethod
    def _format_regime(direction: str, tier: str) -> str:
        if tier == 'chaotic':
            return 'chaotic'
        suffix = 'up' if direction == 'bull' else 'down'
        if tier in ('strong_trending', 'weak_trending'):
            return f'trending-{suffix}'
        return f'ranging-{suffix}'
