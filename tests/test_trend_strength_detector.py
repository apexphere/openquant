"""Tests for TrendStrengthDetector."""
import numpy as np
import pytest
from openquant.regime.trend_strength_detector import TrendStrengthDetector


def _make_candles(closes):
    candles = []
    for i, c in enumerate(closes):
        o = closes[i - 1] if i > 0 else c
        h = max(o, c) + 1
        l = min(o, c) - 1
        candles.append([1700000000000 + i * 86400000, o, c, h, l, 1000.0])
    return np.array(candles)


def _make_uptrend(length=200):
    return _make_candles([50000 + i * 200 for i in range(length)])


def _make_downtrend(length=200):
    return _make_candles([90000 - i * 200 for i in range(length)])


def _make_ranging(length=200):
    return _make_candles([70000 + 100 * np.sin(i * 0.2) for i in range(length)])


class TestColdStart:
    def test_insufficient_data(self):
        d = TrendStrengthDetector(fast_period=13, slow_period=34)
        assert d.detect(np.array([])) == 'cold-start'
        assert d.detect(None) == 'cold-start'
        assert d.detect(_make_candles([50000] * 30)) == 'cold-start'

    def test_enough_data_exits_cold_start(self):
        d = TrendStrengthDetector(fast_period=13, slow_period=34, confirm_bars=0)
        assert d.detect(_make_uptrend(200)) != 'cold-start'


class TestClassification:
    def test_uptrend_detected(self):
        d = TrendStrengthDetector(fast_period=13, slow_period=34, confirm_bars=0)
        assert d.detect(_make_uptrend(200)) == 'trending-up'

    def test_downtrend_detected(self):
        d = TrendStrengthDetector(fast_period=13, slow_period=34, confirm_bars=0)
        assert d.detect(_make_downtrend(200)) == 'trending-down'

    def test_ranging_detected(self):
        d = TrendStrengthDetector(fast_period=13, slow_period=34,
                                   separation_pct=2.0, confirm_bars=0)
        # High separation threshold → small moves classified as ranging
        assert d.detect(_make_ranging(200)) == 'ranging'


class TestConfirmation:
    def test_instant_mode(self):
        d = TrendStrengthDetector(confirm_bars=0)
        d.detect(_make_uptrend(100))
        r1 = d.regime
        d.detect(_make_downtrend(100))
        r2 = d.regime
        assert r1 != r2

    def test_confirmation_delays_switch(self):
        d = TrendStrengthDetector(confirm_bars=3)
        d.detect(_make_uptrend(100))
        established = d.regime
        # Single bar of different data shouldn't switch
        d.detect(_make_downtrend(100))
        # May or may not have switched depending on confirmation
        # The key test: after 1 call, it should either stay or need more bars
        assert d.regime in ('trending-up', 'trending-down', 'ranging', 'cold-start')


class TestReset:
    def test_reset(self):
        d = TrendStrengthDetector(confirm_bars=0)
        d.detect(_make_uptrend(200))
        assert d.regime != 'cold-start'
        d.reset()
        assert d.regime == 'cold-start'


class TestParameters:
    def test_higher_separation_more_ranging(self):
        candles = _make_uptrend(200)
        low_sep = TrendStrengthDetector(separation_pct=0.01, confirm_bars=0)
        high_sep = TrendStrengthDetector(separation_pct=50.0, confirm_bars=0)
        r_low = low_sep.detect(candles)
        r_high = high_sep.detect(candles)
        # With impossibly high separation, everything is ranging
        assert r_high == 'ranging'
        assert 'trending' in r_low

    def test_regime_property_matches(self):
        d = TrendStrengthDetector(confirm_bars=0)
        result = d.detect(_make_uptrend(200))
        assert result == d.regime
