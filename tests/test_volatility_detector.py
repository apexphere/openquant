"""Tests for VolatilityRegimeDetector."""
import numpy as np
import pytest
from openquant.regime.volatility_detector import VolatilityRegimeDetector


def _make_candles(closes, length=None):
    if length is None:
        length = len(closes)
    candles = []
    for i in range(length):
        c = closes[i] if i < len(closes) else closes[-1]
        o = closes[i - 1] if i > 0 and i - 1 < len(closes) else c
        h = max(o, c) + 1
        l = min(o, c) - 1
        candles.append([1700000000000 + i * 86400000, o, c, h, l, 1000.0])
    return np.array(candles)


def _make_volatile_candles(length=200):
    """Large swings — high ATR relative to price."""
    closes = [50000 + 3000 * np.sin(i * 0.5) + np.random.normal(0, 1000) for i in range(length)]
    return _make_candles(closes)


def _make_calm_candles(length=200):
    """Steady, small moves — low ATR relative to price."""
    closes = [50000 + i * 5 for i in range(length)]
    return _make_candles(closes)


class TestColdStart:
    def test_insufficient_data(self):
        d = VolatilityRegimeDetector(atr_period=14, lookback=50)
        assert d.detect(np.array([])) == 'cold-start'
        assert d.detect(None) == 'cold-start'
        assert d.detect(_make_candles([50000] * 30)) == 'cold-start'

    def test_enough_data_exits_cold_start(self):
        d = VolatilityRegimeDetector(atr_period=14, lookback=50, confirm_bars=0)
        candles = _make_volatile_candles(200)
        assert d.detect(candles) != 'cold-start'


class TestClassification:
    def test_calm_market_is_low_volatility(self):
        d = VolatilityRegimeDetector(atr_period=14, lookback=50, confirm_bars=0)
        # Calm candles at the end after volatile start
        volatile = _make_volatile_candles(100)
        calm = _make_calm_candles(100)
        # Concatenate: volatile period then calm period
        combined = np.vstack([volatile, calm])
        regime = d.detect(combined)
        assert regime == 'low-volatility'

    def test_returns_valid_regime(self):
        d = VolatilityRegimeDetector(confirm_bars=0)
        candles = _make_volatile_candles(200)
        regime = d.detect(candles)
        assert regime in ('high-volatility', 'low-volatility', 'normal', 'cold-start')


class TestReset:
    def test_reset_clears_state(self):
        d = VolatilityRegimeDetector(confirm_bars=0)
        d.detect(_make_volatile_candles(200))
        assert d.regime != 'cold-start'
        d.reset()
        assert d.regime == 'cold-start'


class TestParameters:
    def test_regime_property(self):
        d = VolatilityRegimeDetector(confirm_bars=0)
        candles = _make_volatile_candles(200)
        result = d.detect(candles)
        assert result == d.regime
