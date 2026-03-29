"""V4 Momentum regime detector.

More aggressive than V3. The core idea: EMA direction IS the trend.
Ranging is only when price is chopping around with no clear direction.

Detection logic:
    TRENDING-UP:
        fast EMA > slow EMA (bullish structure)
        + EMA separation > threshold (not just barely crossing)
        + price > fast EMA (riding the trend, not pulling back through it)

    TRENDING-DOWN:
        fast EMA < slow EMA (bearish structure)
        + EMA separation > threshold
        + price < fast EMA

    RANGING:
        EMA separation < threshold (no clear direction)
        OR price between EMAs (indecisive)
        ranging-up if price >= slow EMA, ranging-down otherwise

    EXIT:
        Trending-up ends: price crosses below fast EMA (momentum lost)
        Trending-down ends: price crosses above fast EMA

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

        # ── TRENDING CONDITIONS ──
        # Aggressive: just need EMA alignment + price confirmation
        trending_up = emas_bullish and price_above_fast
        trending_down = emas_bearish and price_below_fast

        # ── STATE MACHINE ──
        if self._confirmed_regime == 'trending-up':
            # Stay trending-up unless price drops below fast EMA
            if price_below_fast:
                return 'ranging-up' if current_close >= slow_ema_val else 'ranging-down'
            return 'trending-up'

        elif self._confirmed_regime == 'trending-down':
            # Stay trending-down unless price rises above fast EMA
            if price_above_fast:
                return 'ranging-up' if current_close >= slow_ema_val else 'ranging-down'
            return 'trending-down'

        else:
            # Ranging: look for trend entry
            if trending_up:
                return 'trending-up'
            elif trending_down:
                return 'trending-down'
            else:
                return 'ranging-up' if current_close >= slow_ema_val else 'ranging-down'

    def _apply_confirmation(self, raw_regime: str) -> str:
        """Confirmation with fast exits."""
        if self._confirmed_regime is None:
            self._confirmed_regime = raw_regime
            return raw_regime

        if self.confirm_bars <= 0:
            self._confirmed_regime = raw_regime
            return raw_regime

        # Fast exit: trending → ranging is immediate
        is_exit = (
            self._confirmed_regime in ('trending-up', 'trending-down')
            and raw_regime in ('ranging-up', 'ranging-down')
        )
        if is_exit:
            self._confirmed_regime = raw_regime
            self._pending_regime = None
            self._pending_count = 0
            return raw_regime

        # Entry: ranging → trending needs confirm_bars
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
