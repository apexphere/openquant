"""V3 Breakout regime detector.

Asymmetric detection: markets go up differently than they go down.
Uptrends break out sharply (Donchian). Downtrends grind gradually (EMA+MACD).

Detection logic:
    UPTREND ENTRY (fast, zero lag):
        close > highest high of last N bars (Donchian breakout)
        Confirmed after `confirm_bars` bars holding above

    DOWNTREND ENTRY (momentum-based, handles gradual declines):
        Price < slow EMA (structural bear)
        + EMA separation > threshold (fast EMA well below slow)
        + MACD line < 0 (momentum confirms)
        Confirmed after `confirm_bars` bars

    EXIT (fast, no confirmation delay):
        Trending-up ends:   close < slow EMA (lost support)
        Trending-down ends: close > slow EMA OR MACD histogram > 0
                            (reclaimed support or selling exhausted)

    Ranging classification:
        ranging-up:   not trending + price >= slow EMA
        ranging-down: not trending + price < slow EMA

Why asymmetric:
    - Upside breakouts are sharp, clean events. Donchian catches them instantly.
    - Downtrends grind lower gradually. Donchian low keeps resetting, so
      "breakout below" barely triggers. EMA+MACD detects the grind.
    - Exits are fast for both: lose support = exit immediately.

Regimes:
    trending-up    — Donchian breakout confirmed + holding
    trending-down  — Donchian breakdown confirmed + holding
    ranging-up     — no active trend + price above slow EMA
    ranging-down   — no active trend + price below slow EMA

Usage:
    detector = BreakoutDetector(breakout_period=20, slow_ema=34)
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


class BreakoutDetector:
    """Stateful asymmetric detector: Donchian up + EMA/MACD down.

    Parameters
    ----------
    breakout_period : int
        Lookback period for Donchian high (uptrend entry). Default 20.
    fast_ema : int
        Fast EMA for downtrend direction detection. Default 13.
    slow_ema : int
        Slow EMA for trend support/exit. Default 34.
    separation_pct : float
        Min EMA separation as % of price for downtrend entry. Default 0.3.
    macd_fast : int
        MACD fast period. Default 12.
    macd_slow : int
        MACD slow period. Default 26.
    macd_signal : int
        MACD signal smoothing. Default 9.
    confirm_bars : int
        Bars a new trend must hold before confirming. Default 2.
    timeframe : str
        Candle timeframe. Default '1D'.
    """

    def __init__(
        self,
        breakout_period: int = 20,
        fast_ema: int = 13,
        slow_ema: int = 34,
        separation_pct: float = 0.3,
        macd_fast: int = 12,
        macd_slow: int = 26,
        macd_signal: int = 9,
        confirm_bars: int = 2,
        timeframe: str = '1D',
    ) -> None:
        self.breakout_period = breakout_period
        self.fast_ema = fast_ema
        self.slow_ema = slow_ema
        self.separation_pct = separation_pct
        self.macd_fast = macd_fast
        self.macd_slow = macd_slow
        self.macd_signal = macd_signal
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

        Only reclassifies on completed bar boundaries.
        """
        min_bars = max(self.breakout_period, self.macd_slow + self.macd_signal) * 2
        if candles is None or len(candles) < min_bars:
            raise ValueError(
                f'BreakoutDetector needs at least {min_bars} candles '
                f'(got {len(candles) if candles is not None else 0}).'
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
        """Bulk detection: precompute indicators once, classify every bar."""
        self.reset()
        n = len(candles)
        labels = [None] * n

        # Precompute all indicators once
        fast_ema_arr = ta.ema(candles, period=self.fast_ema, sequential=True)
        slow_ema_arr = ta.ema(candles, period=self.slow_ema, sequential=True)
        macd_result = ta.macd(candles, fast_period=self.macd_fast,
                              slow_period=self.macd_slow,
                              signal_period=self.macd_signal, sequential=True)
        macd_line_arr = macd_result[0]
        macd_hist_arr = macd_result[2]

        min_bars = max(self.breakout_period, self.macd_slow + self.macd_signal) * 2
        for i in range(1, n):
            if i < min_bars:
                continue
            # Classify on completed bar (index i-1)
            idx = i - 1
            current_close = candles[idx, 2]

            # Donchian high: highest high of breakout_period bars before idx
            lookback_start = max(0, idx - self.breakout_period)
            donchian_high = np.max(candles[lookback_start:idx, 3])

            fast_ema_val = fast_ema_arr[idx]
            slow_ema_val = slow_ema_arr[idx]
            macd_line = macd_line_arr[idx]
            macd_hist = macd_hist_arr[idx]

            if np.isnan(slow_ema_val) or np.isnan(fast_ema_val) or np.isnan(macd_line) or np.isnan(current_close):
                raw = self._confirmed_regime or 'ranging-up'
            else:
                breakout_up = current_close > donchian_high
                separation = (fast_ema_val - slow_ema_val) / current_close * 100
                ema_bearish = separation < -self.separation_pct
                downtrend_entry = ema_bearish and macd_line < 0 and macd_hist < 0
                lost_uptrend = current_close < slow_ema_val
                lost_downtrend = current_close > slow_ema_val or macd_hist > 0

                if self._confirmed_regime == 'trending-up':
                    if lost_uptrend:
                        raw = 'ranging-up' if current_close >= slow_ema_val else 'ranging-down'
                    else:
                        raw = 'trending-up'
                elif self._confirmed_regime == 'trending-down':
                    if lost_downtrend:
                        raw = 'ranging-up' if current_close >= slow_ema_val else 'ranging-down'
                    else:
                        raw = 'trending-down'
                else:
                    if breakout_up:
                        raw = 'trending-up'
                    elif downtrend_entry:
                        raw = 'trending-down'
                    else:
                        raw = 'ranging-up' if current_close >= slow_ema_val else 'ranging-down'

            labels[i] = self._apply_confirmation(raw)

        return labels

    def _classify(self, candles: np.ndarray) -> str:
        current_close = candles[-1, 2]

        # ── Indicators ──
        # Donchian high (for uptrend entry)
        lookback = candles[-self.breakout_period - 1:-1]
        donchian_high = np.max(lookback[:, 3])

        # EMAs (for downtrend entry + exits)
        fast_ema_val = ta.ema(candles, period=self.fast_ema, sequential=True)[-1]
        slow_ema_val = ta.ema(candles, period=self.slow_ema, sequential=True)[-1]

        # MACD (for downtrend entry + exits)
        macd_result = ta.macd(
            candles,
            fast_period=self.macd_fast,
            slow_period=self.macd_slow,
            signal_period=self.macd_signal
        )
        macd_line = macd_result[0]
        macd_hist = macd_result[2]

        if np.isnan(slow_ema_val) or np.isnan(fast_ema_val) or np.isnan(macd_line) or np.isnan(current_close):
            return self._confirmed_regime or 'ranging-up'

        # ── UPTREND ENTRY: Donchian breakout (fast, zero lag) ──
        breakout_up = current_close > donchian_high

        # ── DOWNTREND ENTRY: EMA bearish + MACD confirms (handles gradual grind) ──
        separation = (fast_ema_val - slow_ema_val) / current_close * 100
        ema_bearish = separation < -self.separation_pct
        downtrend_entry = ema_bearish and macd_line < 0 and macd_hist < 0

        # ── UPTREND EXIT: lost structural support ──
        lost_uptrend = current_close < slow_ema_val

        # ── DOWNTREND EXIT: reclaimed support OR selling exhausted ──
        #    Histogram flipping positive = selling momentum fading
        #    (asymmetric MACD from v2, proven to catch exhaustion early)
        lost_downtrend = current_close > slow_ema_val or macd_hist > 0

        # ── STATE MACHINE ──
        #
        #   RANGING ──donchian_break──▶ TRENDING-UP ──close<ema──▶ RANGING
        #   RANGING ──ema+macd_bear──▶ TRENDING-DN ──close>ema──▶ RANGING

        if self._confirmed_regime == 'trending-up':
            if lost_uptrend:
                return 'ranging-up' if current_close >= slow_ema_val else 'ranging-down'
            return 'trending-up'

        elif self._confirmed_regime == 'trending-down':
            if lost_downtrend:
                return 'ranging-up' if current_close >= slow_ema_val else 'ranging-down'
            return 'trending-down'

        else:
            # Ranging: look for entries
            if breakout_up:
                return 'trending-up'
            elif downtrend_entry:
                return 'trending-down'
            else:
                return 'ranging-up' if current_close >= slow_ema_val else 'ranging-down'

    def _apply_confirmation(self, raw_regime: str) -> str:
        """Confirmation state machine.

        New breakout entries require `confirm_bars` consecutive bars.
        Exits from trending to ranging are IMMEDIATE (no confirmation delay).
        This is asymmetric by design: be careful entering, be fast exiting.
        """
        if self._confirmed_regime is None:
            self._confirmed_regime = raw_regime
            return raw_regime

        if self.confirm_bars <= 0:
            self._confirmed_regime = raw_regime
            return raw_regime

        # Fast exit: trending → ranging is immediate (no confirmation)
        is_exit = (
            self._confirmed_regime in ('trending-up', 'trending-down')
            and raw_regime in ('ranging-up', 'ranging-down')
        )
        if is_exit:
            self._confirmed_regime = raw_regime
            self._pending_regime = None
            self._pending_count = 0
            return raw_regime

        # Confirmed entry: ranging → trending needs confirm_bars
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
