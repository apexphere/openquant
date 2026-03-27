"""Candle energy quality filter.

Measures candle body-to-range ratio and inter-candle overlap over a
lookback window. High body ratio + low overlap = strong directional
conviction (score near 10). Small bodies + high overlap = choppy,
unconvincing price action (score near 0).

Operates on daily candles by default. The 15m signal is noise; daily
candle structure captures meaningful trend quality differences.

Score formula:
    body_score = mean(abs(close - open) / (high - low)) * 10
    overlap_score = (1 - mean(overlap_ratio)) * 10
    score = w_body * body_score + w_overlap * overlap_score
"""
import numpy as np


class CandleEnergyFilter:
    """Scores regime quality based on candle body fullness and overlap.

    Parameters
    ----------
    lookback : int
        Number of candles to analyze. Default 20.
    body_weight : float
        Weight for body ratio sub-score. Default 0.5.
    overlap_weight : float
        Weight for overlap sub-score. Default 0.5.
    timeframe : str | None
        Candle timeframe to operate on. Default '1D'.
    """

    def __init__(
        self,
        lookback: int = 20,
        body_weight: float = 0.5,
        overlap_weight: float = 0.5,
        timeframe: str | None = '1D',
    ) -> None:
        self._lookback = lookback
        self._body_weight = body_weight
        self._overlap_weight = overlap_weight
        self._timeframe = timeframe

    @property
    def warmup_bars(self) -> int:
        return self._lookback

    @property
    def required_timeframe(self) -> str | None:
        return self._timeframe

    @property
    def name(self) -> str:
        return 'candle_energy'

    def score(self, candles: np.ndarray, regime: str) -> float | None:
        """Score candle energy from 0 (choppy junk) to 10 (strong conviction).

        Parameters
        ----------
        candles : np.ndarray
            Candle array with shape (n, 6+):
            [timestamp, open, close, high, low, volume, ...]
        regime : str
            Current regime label (unused by this filter, applies to all regimes).

        Returns
        -------
        float | None
            Quality score 0-10, or None if insufficient data.
        """
        if candles is None or len(candles) < self._lookback:
            return None

        window = candles[-self._lookback:]
        body_score = self._body_ratio_score(window)
        overlap_score = self._overlap_score(window)

        if body_score is None or overlap_score is None:
            return None

        return self._body_weight * body_score + self._overlap_weight * overlap_score

    def _body_ratio_score(self, candles: np.ndarray) -> float | None:
        """Mean body-to-range ratio scaled to 0-10.

        Large candle bodies relative to their range indicate strong
        directional conviction. Doji-like candles (body near zero)
        indicate indecision.
        """
        highs = candles[:, 3]
        lows = candles[:, 4]
        ranges = highs - lows

        # Guard: skip candles where high == low (zero range)
        valid_mask = ranges > 0
        if not np.any(valid_mask):
            return None

        opens = candles[:, 1][valid_mask]
        closes = candles[:, 2][valid_mask]
        valid_ranges = ranges[valid_mask]

        bodies = np.abs(closes - opens)
        ratios = bodies / valid_ranges

        return float(min(np.mean(ratios) * 10, 10.0))

    def _overlap_score(self, candles: np.ndarray) -> float | None:
        """Mean inter-candle overlap inverted and scaled to 0-10.

        Low overlap between consecutive candles means each bar makes
        new ground (trending). High overlap means bars retrace into
        each other (choppy/ranging).
        """
        if len(candles) < 2:
            return None

        overlaps = []
        for i in range(1, len(candles)):
            prev_high = candles[i - 1, 3]
            prev_low = candles[i - 1, 4]
            curr_high = candles[i, 3]
            curr_low = candles[i, 4]

            overlap_top = min(prev_high, curr_high)
            overlap_bot = max(prev_low, curr_low)
            overlap = max(0.0, overlap_top - overlap_bot)

            total_range = max(prev_high, curr_high) - min(prev_low, curr_low)
            if total_range > 0:
                overlaps.append(overlap / total_range)

        if not overlaps:
            return None

        avg_overlap = np.mean(overlaps)
        return float(min((1.0 - avg_overlap) * 10, 10.0))
