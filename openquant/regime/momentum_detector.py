"""V4 Momentum regime detector.

More aggressive than V3. The core idea: EMA direction IS the trend.
Ranging is only when price is chopping around with no clear direction.

Detection logic:
    ENTRY (hard — requires conviction):
        TRENDING-UP:
            fast EMA > slow EMA + separation > threshold
            + price > fast EMA (riding the trend)
        TRENDING-DOWN:
            fast EMA < slow EMA + separation > threshold
            + price < fast EMA

    STAY (easy — trailing):
        Once trending, stay trending as long as price holds above/below
        the SLOW EMA. Pullbacks to fast EMA are normal and tolerated.

    EXIT (trailing — slow EMA break):
        Trending-up ends: price < slow EMA (structural support lost)
        Trending-down ends: price > slow EMA (resistance reclaimed)

    RANGING:
        Not trending. ranging-up if price >= slow EMA, else ranging-down.

Why more aggressive than V3:
    - V3 required Donchian breakout (new high) for uptrends. V4 just needs
      EMA alignment + price above. Catches trends much earlier.
    - V3 required MACD < 0 AND histogram < 0 for downtrends. V4 just needs
      EMA bearish + price below fast EMA. Catches grinds immediately.
    - Exits on fast EMA cross (faster than V3's slow EMA exit).

Regimes:
    trending-up    — EMAs bullish + price above fast EMA
    trending-down  — EMAs bearish + price below fast EMA
    ranging-up     — indecisive + price above slow EMA
    ranging-down   — indecisive + price below slow EMA

Usage:
    detector = MomentumDetector(fast_ema=13, slow_ema=34)
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


class MomentumDetector:
    """Stateful EMA-momentum detector. More aggressive trend classification.

    Parameters
    ----------
    fast_ema : int
        Fast EMA period. Default 13.
    slow_ema : int
        Slow EMA period. Default 34.
    separation_pct : float
        Min EMA separation as % of price to classify as trending. Default 0.15.
    confirm_bars : int
        Bars a new trend must hold before confirming. Default 1.
    timeframe : str
        Candle timeframe. Default '1D'.
    """

    def __init__(
        self,
        fast_ema: int = 13,
        slow_ema: int = 34,
        separation_pct: float = 0.15,
        confirm_bars: int = 1,
        timeframe: str = '1D',
    ) -> None:
        self.fast_ema = fast_ema
        self.slow_ema = slow_ema
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
        """Classify the current market regime."""
        min_bars = self.slow_ema * 2
        if candles is None or len(candles) < min_bars:
            raise ValueError(
                f'MomentumDetector needs at least {min_bars} candles '
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

        fast_ema_val = ta.ema(candles, period=self.fast_ema, sequential=True)[-1]
        slow_ema_val = ta.ema(candles, period=self.slow_ema, sequential=True)[-1]

        if np.isnan(slow_ema_val) or np.isnan(fast_ema_val) or np.isnan(current_close):
            return self._confirmed_regime or 'ranging-up'

        # EMA separation as % of price
        separation = (fast_ema_val - slow_ema_val) / current_close * 100

        emas_bullish = separation > self.separation_pct
        emas_bearish = separation < -self.separation_pct

        price_above_fast = current_close > fast_ema_val
        price_below_fast = current_close < fast_ema_val

        # ── ENTRY: requires conviction (EMA alignment + price confirms) ──
        trending_up_entry = emas_bullish and price_above_fast
        trending_down_entry = emas_bearish and price_below_fast

        # ── EXIT: trailing (only exit on slow EMA break, not fast) ──
        #    Trend gets room to breathe. Pullbacks to fast EMA are normal.
        #    Only lose the trend when price breaks the slow EMA.
        lost_uptrend = current_close < slow_ema_val
        lost_downtrend = current_close > slow_ema_val

        # ── STATE MACHINE ──
        #
        #   Entry: hard (EMA separated + price above/below fast)
        #   Stay:  easy (just hold above/below slow EMA)
        #   Exit:  trailing (break slow EMA = trend over)

        if self._confirmed_regime == 'trending-up':
            if lost_uptrend:
                return 'ranging-down'
            return 'trending-up'

        elif self._confirmed_regime == 'trending-down':
            if lost_downtrend:
                return 'ranging-up'
            return 'trending-down'

        else:
            # Ranging: look for trend entry
            if trending_up_entry:
                return 'trending-up'
            elif trending_down_entry:
                return 'trending-down'
            else:
                return 'ranging-up' if current_close >= slow_ema_val else 'ranging-down'

    def _apply_confirmation(self, raw_regime: str) -> str:
        """All regime changes require confirmation.

        Entry (ranging → trending): confirm_bars of consistent signal.
        Exit (trending → ranging): also confirm_bars — one bar dipping
        below the slow EMA shouldn't kill the trend.
        """
        if self._confirmed_regime is None:
            self._confirmed_regime = raw_regime
            return raw_regime

        if self.confirm_bars <= 0:
            self._confirmed_regime = raw_regime
            return raw_regime

        # No direct trend reversal: trending-up cannot go straight to
        # trending-down (or vice versa). Must pass through ranging first.
        if (
            self._confirmed_regime == 'trending-up' and raw_regime == 'trending-down'
            or self._confirmed_regime == 'trending-down' and raw_regime == 'trending-up'
        ):
            raw_regime = 'ranging-down' if raw_regime == 'trending-up' else 'ranging-up'

        # Any regime change requires confirmation
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
            # Signal matches current regime — reset any pending change
            self._pending_regime = None
            self._pending_count = 0

        return self._confirmed_regime
