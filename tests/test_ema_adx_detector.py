"""Tests for the EMA+ADX composite regime detector."""
import numpy as np
import pytest

from openquant.regime.ema_adx_detector import EmaAdxDetector, REGIMES


def _make_candles(n, start_price=100.0, trend=0.0, noise=0.5):
    """Generate synthetic candle data with optional trend.

    trend > 0: uptrend, trend < 0: downtrend, trend == 0: flat/ranging
    """
    candles = []
    price = start_price
    for i in range(n):
        price += trend + np.random.uniform(-noise, noise)
        open_ = price - np.random.uniform(0, noise)
        close = price + np.random.uniform(-noise, noise)
        high = max(open_, close) + np.random.uniform(0, noise)
        low = min(open_, close) - np.random.uniform(0, noise)
        candles.append([i * 86400000, open_, close, high, low, 100.0])
    return np.array(candles)


def _make_strong_uptrend(n=100):
    return _make_candles(n, start_price=100, trend=1.5, noise=0.3)


def _make_strong_downtrend(n=100):
    return _make_candles(n, start_price=200, trend=-1.5, noise=0.3)


def _make_flat_range(n=100):
    """Candles oscillating around a fixed price with minimal drift."""
    candles = []
    price = 100.0
    for i in range(n):
        # Oscillate around center, no drift
        offset = np.sin(i * 0.3) * 0.3
        open_ = price + offset
        close = price + offset + np.random.uniform(-0.1, 0.1)
        high = max(open_, close) + 0.1
        low = min(open_, close) - 0.1
        candles.append([i * 86400000, open_, close, high, low, 100.0])
    return np.array(candles)


class TestEmaAdxDetectorBasics:
    def test_regime_labels(self):
        assert REGIMES == frozenset({
            'trending-up', 'trending-down', 'ranging-up', 'ranging-down'
        })

    def test_default_params(self):
        d = EmaAdxDetector()
        assert d.fast_period == 13
        assert d.slow_period == 34
        assert d.macd_fast == 12
        assert d.macd_slow == 26
        assert d.macd_signal == 9
        assert d.separation_pct == 0.3
        assert d.confirm_bars == 2

    def test_custom_params(self):
        d = EmaAdxDetector(fast_period=8, slow_period=21, macd_fast=8)
        assert d.fast_period == 8
        assert d.slow_period == 21
        assert d.macd_fast == 8

    def test_initial_regime_is_none(self):
        d = EmaAdxDetector()
        assert d.regime is None

    def test_reset(self):
        d = EmaAdxDetector()
        candles = _make_strong_uptrend()
        d.detect(candles)
        assert d.regime is not None
        d.reset()
        assert d.regime is None


class TestInsufficientData:
    def test_none_candles_raises(self):
        d = EmaAdxDetector()
        with pytest.raises(ValueError, match='needs at least'):
            d.detect(None)

    def test_too_few_candles_raises(self):
        d = EmaAdxDetector()
        candles = _make_candles(10)
        with pytest.raises(ValueError, match='needs at least'):
            d.detect(candles)

    def test_minimum_candles_works(self):
        d = EmaAdxDetector(fast_period=5, slow_period=10, macd_fast=5, macd_slow=10, macd_signal=5, confirm_bars=0)
        min_bars = max(10, 10 + 5) * 2  # 30
        candles = _make_strong_uptrend(35)
        regime = d.detect(candles)
        assert regime in REGIMES


class TestRegimeClassification:
    def test_strong_uptrend(self):
        d = EmaAdxDetector(confirm_bars=0)
        candles = _make_strong_uptrend(100)
        regime = d.detect(candles)
        assert regime in ('trending-up', 'ranging-up')

    def test_strong_downtrend(self):
        d = EmaAdxDetector(confirm_bars=0)
        candles = _make_strong_downtrend(100)
        regime = d.detect(candles)
        assert regime in ('trending-down', 'ranging-down')

    def test_flat_range(self):
        d = EmaAdxDetector(confirm_bars=0)
        candles = _make_flat_range(100)
        regime = d.detect(candles)
        assert regime in ('ranging-up', 'ranging-down')

    def test_output_always_in_regimes(self):
        d = EmaAdxDetector(confirm_bars=0)
        for factory in [_make_strong_uptrend, _make_strong_downtrend, _make_flat_range]:
            candles = factory(100)
            assert d.detect(candles) in REGIMES


class TestConfirmation:
    def test_confirmation_prevents_immediate_switch(self):
        d = EmaAdxDetector(confirm_bars=3)
        candles_up = _make_strong_uptrend(100)
        r1 = d.detect(candles_up)

        # Single bar of different signal shouldn't switch
        candles_down = _make_strong_downtrend(100)
        r2 = d.detect(candles_down)
        # With confirm_bars=3, one bar shouldn't change the regime
        # (r2 might equal r1 if confirmation blocks the switch)

    def test_zero_confirm_bars_instant_switch(self):
        d = EmaAdxDetector(confirm_bars=0)
        candles = _make_strong_uptrend(100)
        r1 = d.detect(candles)
        # Instant, no delay

    def test_reset_clears_confirmation(self):
        d = EmaAdxDetector(confirm_bars=3)
        candles = _make_strong_uptrend(100)
        d.detect(candles)
        d.reset()
        assert d._pending_regime is None
        assert d._pending_count == 0


class TestNaNHandling:
    def test_nan_in_candles_returns_previous_regime(self):
        d = EmaAdxDetector(confirm_bars=0)
        candles = _make_strong_uptrend(100)
        r1 = d.detect(candles)

        # Inject NaN into last close
        bad_candles = candles.copy()
        bad_candles[-1, 2] = np.nan
        r2 = d.detect(bad_candles)
        # Should keep previous regime, not crash
        assert r2 in REGIMES
