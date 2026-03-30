"""V6 Price Structure regime detector.

Detects trends from actual price structure — higher highs/lows for
uptrends, lower highs/lows for downtrends. No indicator lag because
it reads the market's own structure, not a smoothed derivative.

Detection logic:
    1. Identify swing highs and swing lows using N-bar lookback
       (a swing high is a bar whose high is higher than N bars on each side)

    2. Track the sequence of swing points:
       - Higher high + higher low = UPTREND
       - Lower high + lower low = DOWNTREND
       - Mixed (higher high + lower low, or lower high + higher low) = RANGING

    3. Direction from the latest swing sequence:
       - ranging-up if last swing low is above the one before it
       - ranging-down if last swing low is below the one before it

Why better than indicator-based:
    - A distribution zone (Oct 2025) makes a high, then fails to hold it
      and breaks the previous low. This is unambiguous: lower high + lower
      low = downtrend. SuperTrend can't see this because it only tracks
      price vs a trailing band.
    - No lag: swing points are identified as soon as they're confirmed
      (N bars after the swing). No EMA smoothing delay.
    - No false breakouts: a new high that immediately reverses creates
      a swing high, which then gets compared to the structure. If the
      next low is lower than the previous low, it's a trend change.

Regimes:
    trending-up    — last two swing highs rising AND last two swing lows rising
    trending-down  — last two swing highs falling AND last two swing lows falling
    ranging-up     — mixed structure + price above mid-point of last swing range
    ranging-down   — mixed structure + price below mid-point of last swing range

Parameters:
    swing_period : int — bars on each side to confirm a swing point (default 5)
    confirm_bars : int — bars to hold new regime before confirming (default 2)

Usage:
    detector = StructureDetector(swing_period=5)
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


class StructureDetector:
    """Stateful price structure detector.

    Tracks swing highs/lows and classifies based on their sequence.
    """

    def __init__(
        self,
        swing_period: int = 5,
        confirm_bars: int = 2,
        timeframe: str = '1D',
    ) -> None:
        self.swing_period = swing_period
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
        """Classify the current market regime from price structure."""
        min_bars = self.swing_period * 6
        if candles is None or len(candles) < min_bars:
            raise ValueError(
                f'StructureDetector needs at least {min_bars} candles '
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

    def _find_swing_points(self, candles: np.ndarray):
        """Find swing highs and swing lows using ta.minmax (scipy argrelextrema)."""
        extrema = ta.minmax(candles, order=self.swing_period, sequential=True)

        swing_highs = []
        swing_lows = []

        for i in range(len(candles)):
            if not np.isnan(extrema.is_max[i]):
                swing_highs.append((i, extrema.is_max[i]))
            if not np.isnan(extrema.is_min[i]):
                swing_lows.append((i, extrema.is_min[i]))

        return swing_highs, swing_lows

    def _classify(self, candles: np.ndarray) -> str:
        current_close = candles[-1, 2]

        swing_highs, swing_lows = self._find_swing_points(candles)

        if len(swing_highs) < 2 or len(swing_lows) < 2:
            return self._confirmed_regime or 'ranging-up'

        # Use last 3 swing points for more robust structure read
        # Check if the overall structure is trending or mixed
        n_check = min(3, len(swing_highs), len(swing_lows))

        recent_highs = [sh[1] for sh in swing_highs[-n_check:]]
        recent_lows = [sl[1] for sl in swing_lows[-n_check:]]

        # Count rising vs falling moves in the sequence
        rising_highs = sum(1 for i in range(1, len(recent_highs)) if recent_highs[i] > recent_highs[i-1])
        falling_highs = sum(1 for i in range(1, len(recent_highs)) if recent_highs[i] < recent_highs[i-1])
        rising_lows = sum(1 for i in range(1, len(recent_lows)) if recent_lows[i] > recent_lows[i-1])
        falling_lows = sum(1 for i in range(1, len(recent_lows)) if recent_lows[i] < recent_lows[i-1])

        # Also check where current price is relative to structure
        last_swing_high = swing_highs[-1][1]
        last_swing_low = swing_lows[-1][1]
        price_near_highs = current_close > (last_swing_high + last_swing_low) / 2

        # Uptrend: majority of swings rising AND price near highs
        bullish_structure = rising_highs > falling_highs and rising_lows > falling_lows
        bearish_structure = falling_highs > rising_highs and falling_lows > rising_lows

        if bullish_structure and price_near_highs:
            return 'trending-up'

        if bearish_structure and not price_near_highs:
            return 'trending-down'

        # Ranging: mixed structure or price contradicts structure
        if current_close >= (last_swing_high + last_swing_low) / 2:
            return 'ranging-up'
        else:
            return 'ranging-down'

    def _apply_confirmation(self, raw_regime: str) -> str:
        """All regime changes require confirmation."""
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
