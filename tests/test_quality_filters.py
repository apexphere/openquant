"""Tests for the quality filter framework and CandleEnergyFilter."""
import math
import numpy as np
import pytest

from openquant.regime.quality import QualityFilter, aggregate_scores
from openquant.regime.filters.candle_energy import CandleEnergyFilter


# ── aggregate_scores tests ────────────────────────────────────────

class TestAggregateScores:
    def test_min_with_mixed_scores(self):
        assert aggregate_scores([7.2, 5.4, 8.0], 'min') == 5.4

    def test_min_excludes_none(self):
        assert aggregate_scores([7.2, None, 5.4], 'min') == 5.4

    def test_mean_with_mixed_scores(self):
        result = aggregate_scores([7.2, None, 5.4], 'mean')
        assert abs(result - 6.3) < 0.01

    def test_all_none_returns_none(self):
        assert aggregate_scores([None, None], 'min') is None

    def test_empty_list_returns_none(self):
        assert aggregate_scores([], 'min') is None

    def test_nan_treated_as_none(self):
        assert aggregate_scores([float('nan'), 5.0], 'min') == 5.0

    def test_all_nan_returns_none(self):
        assert aggregate_scores([float('nan'), float('nan')], 'min') is None

    def test_single_score(self):
        assert aggregate_scores([7.5], 'min') == 7.5

    def test_single_none(self):
        assert aggregate_scores([None], 'min') is None


# ── CandleEnergyFilter tests ─────────────────────────────────────

def _make_candles(n, body_frac=0.5, overlap_frac=0.3, base_price=100.0, range_size=2.0):
    """Generate synthetic candle data.

    Parameters
    ----------
    n : int
        Number of candles.
    body_frac : float
        Fraction of the candle range that is body (0-1).
    overlap_frac : float
        How much consecutive candles overlap (0-1).
    base_price : float
        Starting price.
    range_size : float
        High-low range per candle.
    """
    candles = []
    price = base_price
    for i in range(n):
        low = price
        high = price + range_size
        body = range_size * body_frac
        # Alternate direction
        if i % 2 == 0:
            open_ = low + (range_size - body) / 2
            close = open_ + body
        else:
            close = low + (range_size - body) / 2
            open_ = close + body

        candles.append([i * 60000, open_, close, high, low, 100.0])

        # Move price: less overlap = more movement between candles
        step = range_size * (1 - overlap_frac)
        price += step

    return np.array(candles)


def _make_strong_trend(n=20):
    """Large bodies, low overlap — strong directional conviction."""
    return _make_candles(n, body_frac=0.8, overlap_frac=0.1, range_size=3.0)


def _make_choppy_range(n=20):
    """Small bodies, high overlap — choppy, directionless."""
    return _make_candles(n, body_frac=0.15, overlap_frac=0.8, range_size=1.0)


def _make_medium_quality(n=20):
    """Moderate bodies, moderate overlap."""
    return _make_candles(n, body_frac=0.45, overlap_frac=0.45, range_size=2.0)


class TestCandleEnergyFilter:
    def setup_method(self):
        self.filter = CandleEnergyFilter(lookback=20, timeframe=None)

    def test_protocol_compliance(self):
        """CandleEnergyFilter implements QualityFilter protocol."""
        assert isinstance(self.filter, QualityFilter)

    def test_strong_trend_high_score(self):
        candles = _make_strong_trend()
        score = self.filter.score(candles, 'trending-up')
        assert score is not None
        assert score >= 7.0, f'Strong trend should score >= 7.0, got {score:.2f}'

    def test_choppy_range_low_score(self):
        candles = _make_choppy_range()
        score = self.filter.score(candles, 'ranging-up')
        assert score is not None
        assert score <= 4.0, f'Choppy range should score <= 4.0, got {score:.2f}'

    def test_medium_quality_medium_score(self):
        candles = _make_medium_quality()
        score = self.filter.score(candles, 'trending-up')
        assert score is not None
        assert 3.5 <= score <= 7.0, f'Medium quality should score 3.5-7.0, got {score:.2f}'

    def test_insufficient_data_returns_none(self):
        candles = _make_strong_trend(5)  # less than lookback of 20
        score = self.filter.score(candles, 'trending-up')
        assert score is None

    def test_none_candles_returns_none(self):
        assert self.filter.score(None, 'trending-up') is None

    def test_flat_candles_low_body_score(self):
        """All doji candles (open == close) should get very low body score."""
        n = 20
        candles = []
        for i in range(n):
            price = 100.0 + i * 0.5
            candles.append([i * 60000, price, price, price + 1.0, price - 1.0, 100.0])
        candles = np.array(candles)
        score = self.filter.score(candles, 'trending-up')
        assert score is not None
        assert score <= 5.0, f'Doji candles should score low, got {score:.2f}'

    def test_zero_range_candles_returns_none(self):
        """Candles where high == low == open == close."""
        n = 20
        candles = np.array([[i * 60000, 100.0, 100.0, 100.0, 100.0, 0.0] for i in range(n)])
        score = self.filter.score(candles, 'trending-up')
        assert score is None

    def test_score_bounded_0_10(self):
        for factory in [_make_strong_trend, _make_choppy_range, _make_medium_quality]:
            candles = factory(30)
            score = self.filter.score(candles, 'trending-up')
            if score is not None:
                assert 0 <= score <= 10, f'Score out of bounds: {score}'

    def test_regime_agnostic(self):
        """Score should be the same regardless of regime label."""
        candles = _make_strong_trend()
        s1 = self.filter.score(candles, 'trending-up')
        s2 = self.filter.score(candles, 'ranging-down')
        assert s1 == s2

    def test_warmup_bars(self):
        f = CandleEnergyFilter(lookback=15)
        assert f.warmup_bars == 15

    def test_required_timeframe_default(self):
        f = CandleEnergyFilter()
        assert f.required_timeframe == '1D'

    def test_required_timeframe_custom(self):
        f = CandleEnergyFilter(timeframe='4h')
        assert f.required_timeframe == '4h'

    def test_name(self):
        assert self.filter.name == 'candle_energy'

    def test_custom_weights(self):
        """Custom weights should change the score."""
        candles = _make_strong_trend()
        f_body = CandleEnergyFilter(lookback=20, body_weight=1.0, overlap_weight=0.0, timeframe=None)
        f_overlap = CandleEnergyFilter(lookback=20, body_weight=0.0, overlap_weight=1.0, timeframe=None)
        s_body = f_body.score(candles, 'trending-up')
        s_overlap = f_overlap.score(candles, 'trending-up')
        assert s_body != s_overlap
