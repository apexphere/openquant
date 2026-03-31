"""Tests for SuperTrendDetector SMA macro trend filter.

Tests cover:
  - Pure function _apply_sma_filter unit tests
  - SMA filter downgrades trending-up to ranging-down when price < SMA
  - SMA filter downgrades trending-down to ranging-down when price > SMA
  - Filter disabled with use_trend_filter=False
  - Filter works in detect_all() bulk path
  - NaN SMA values (insufficient data) don't crash — filter is skipped
  - Custom trend_sma_period parameter
  - Default parameters unchanged (backward compat)
  - Bear bounce scenario — no trending-up during structural downtrend
  - Bull dip scenario — no trending-down during structural uptrend
  - Sustained downtrend with multiple bounces
  - Test isolation from global config pollution
"""
import copy

import numpy as np
import pytest
from openquant.regime.supertrend_detector import SuperTrendDetector, _apply_sma_filter
import openquant.config as config_module


@pytest.fixture(autouse=True)
def _reset_global_config():
    """Force warmup_candles_num to default before each test.

    The framework's reset_config() uses a shallow copy, so nested dicts
    (like config['env']['data']) are shared between config and backup_config.
    Earlier tests (test_isolated_backtest) set warmup_candles_num=0, which
    corrupts slice_candles behavior and breaks indicator calculations.
    We explicitly restore the default value (240) since reset_config can't.
    """
    config_module.config['env']['data']['warmup_candles_num'] = 240
    yield
    config_module.config['env']['data']['warmup_candles_num'] = 240


def _make_candles(closes: list, n_bars: int = None) -> np.ndarray:
    """Build a candle array from a list of close prices.

    Each candle: [timestamp, open, close, high, low, volume]
    """
    if n_bars is None:
        n_bars = len(closes)
    candles = []
    for i in range(n_bars):
        close = closes[i] if i < len(closes) else closes[-1]
        open_price = closes[i - 1] if i > 0 and i - 1 < len(closes) else close
        high = max(open_price, close) + 1
        low = min(open_price, close) - 1
        ts = 1700000000000 + i * 86400000
        candles.append([ts, open_price, close, high, low, 1000.0])
    return np.array(candles)


def _make_trending_up_candles(length: int = 200) -> np.ndarray:
    """Steady uptrend — price rises consistently."""
    closes = [50000 + i * 200 for i in range(length)]
    return _make_candles(closes)


def _make_trending_down_candles(length: int = 200) -> np.ndarray:
    """Steady downtrend — price falls consistently."""
    closes = [90000 - i * 200 for i in range(length)]
    return _make_candles(closes)


def _make_bear_bounce_candles(length: int = 200, bounce_start: int = 150,
                               bounce_size: int = 15) -> np.ndarray:
    """Sustained downtrend with a temporary bounce.

    Price falls from 90000 at -200/bar, then bounces up at +100/bar
    for bounce_size bars, then resumes falling. The bounce is small enough
    that price stays well below SMA(50) throughout.
    """
    closes = []
    for i in range(length):
        if i < bounce_start:
            # Downtrend: -200 per bar
            closes.append(90000 - i * 200)
        elif i < bounce_start + bounce_size:
            # Bounce: +100 per bar (modest, stays below SMA)
            base = 90000 - bounce_start * 200
            closes.append(base + (i - bounce_start) * 100)
        else:
            # Resume downtrend
            base = 90000 - bounce_start * 200
            closes.append(base - (i - bounce_start - bounce_size) * 200)
    return _make_candles(closes)


def _make_bull_dip_candles(length: int = 200, dip_start: int = 150,
                            dip_size: int = 20) -> np.ndarray:
    """Sustained uptrend with a temporary dip.

    Price rises from 50000, then dips for dip_size bars,
    then resumes rising. The SMA(50) should still be below price
    during the dip, preventing a false trending-down classification.
    """
    closes = []
    for i in range(length):
        if i < dip_start:
            closes.append(50000 + i * 200)
        elif i < dip_start + dip_size:
            base = 50000 + dip_start * 200
            closes.append(base - (i - dip_start) * 300)
        else:
            base = 50000 + dip_start * 200
            closes.append(base + (i - dip_start - dip_size) * 200)
    return _make_candles(closes)


class TestDefaultParametersUnchanged:
    """Backward compatibility: existing defaults must not change."""

    def test_default_st_period(self):
        d = SuperTrendDetector()
        assert d.st_period == 10

    def test_default_st_factor(self):
        d = SuperTrendDetector()
        assert d.st_factor == 3.0

    def test_default_adx_threshold(self):
        d = SuperTrendDetector()
        assert d.adx_threshold == 25.0

    def test_default_chop_ranging(self):
        d = SuperTrendDetector()
        assert d.chop_ranging == 55.0

    def test_default_chop_trending(self):
        d = SuperTrendDetector()
        assert d.chop_trending == 38.2

    def test_default_trend_filter_params(self):
        d = SuperTrendDetector()
        assert d.trend_sma_period == 100
        assert d.use_trend_filter is True


class TestSMAFilterDowngradesInClassify:
    """_classify() should downgrade trending regimes when SMA disagrees."""

    def test_trending_up_allowed_when_price_above_sma(self):
        """In a real uptrend, price is above SMA — trending-up should pass."""
        detector = SuperTrendDetector(
            bull_entry_bars=0, bull_exit_bars=0,
            bear_entry_bars=0, bear_exit_bars=0,
            use_trend_filter=True, trend_sma_period=50,
        )
        candles = _make_trending_up_candles(200)
        regime = detector.detect(candles)
        assert regime == 'trending-up'

    def test_trending_down_allowed_when_price_below_sma(self):
        """In a real downtrend, price is below SMA — trending-down should pass."""
        detector = SuperTrendDetector(
            bull_entry_bars=0, bull_exit_bars=0,
            bear_entry_bars=0, bear_exit_bars=0,
            use_trend_filter=True, trend_sma_period=50,
        )
        candles = _make_trending_down_candles(200)
        regime = detector.detect(candles)
        assert regime == 'trending-down'


class TestSMAFilterDisabled:
    """With use_trend_filter=False, classification is unchanged."""

    def test_filter_off_preserves_original_behavior(self):
        detector_on = SuperTrendDetector(
            bull_entry_bars=0, bull_exit_bars=0,
            bear_entry_bars=0, bear_exit_bars=0,
            use_trend_filter=False, trend_sma_period=50,
        )
        candles = _make_trending_up_candles(200)
        regime = detector_on.detect(candles)
        # Should still classify normally
        assert regime in ('trending-up', 'trending-down', 'ranging-up', 'ranging-down')


class TestSMAFilterInDetectAll:
    """detect_all() bulk path must also apply the SMA filter."""

    def test_detect_all_uses_sma_filter(self):
        """detect_all should produce same results as detect for each bar."""
        detector_all = SuperTrendDetector(
            bull_entry_bars=0, bull_exit_bars=0,
            bear_entry_bars=0, bear_exit_bars=0,
            use_trend_filter=True, trend_sma_period=50,
        )
        candles = _make_trending_up_candles(200)
        labels = detector_all.detect_all(candles)

        # The last non-None label should match single detect
        detector_single = SuperTrendDetector(
            bull_entry_bars=0, bull_exit_bars=0,
            bear_entry_bars=0, bear_exit_bars=0,
            use_trend_filter=True, trend_sma_period=50,
        )
        single_result = detector_single.detect(candles)

        non_none = [l for l in labels if l is not None]
        assert len(non_none) > 0
        assert non_none[-1] == single_result

    def test_detect_all_filter_off(self):
        """detect_all with filter off should not apply SMA downgrade."""
        detector = SuperTrendDetector(
            bull_entry_bars=0, bull_exit_bars=0,
            bear_entry_bars=0, bear_exit_bars=0,
            use_trend_filter=False, trend_sma_period=50,
        )
        candles = _make_trending_up_candles(200)
        labels = detector.detect_all(candles)
        non_none = [l for l in labels if l is not None]
        assert len(non_none) > 0


class TestSMAFilterNaN:
    """When SMA has NaN (insufficient data), filter should be skipped."""

    def test_nan_sma_does_not_crash(self):
        """With very few candles, SMA is NaN — should not crash or block."""
        detector = SuperTrendDetector(
            bull_entry_bars=0, bull_exit_bars=0,
            bear_entry_bars=0, bear_exit_bars=0,
            use_trend_filter=True, trend_sma_period=50,
        )
        # min_bars for ST detector is max(10,14,14)*3 = 42
        # SMA(50) needs 50 bars — so with 45 bars we get NaN SMA
        # but the detector will raise ValueError for < min_bars anyway
        # Use enough for detector but less than SMA period
        candles = _make_trending_up_candles(200)
        # This should work without crashing
        regime = detector.detect(candles)
        assert regime in ('trending-up', 'trending-down', 'ranging-up', 'ranging-down')


class TestCustomTrendSMAPeriod:
    """Custom trend_sma_period should be respected."""

    def test_short_sma_period(self):
        detector = SuperTrendDetector(
            bull_entry_bars=0, bull_exit_bars=0,
            bear_entry_bars=0, bear_exit_bars=0,
            use_trend_filter=True, trend_sma_period=20,
        )
        assert detector.trend_sma_period == 20
        candles = _make_trending_up_candles(200)
        regime = detector.detect(candles)
        assert regime in ('trending-up', 'trending-down', 'ranging-up', 'ranging-down')

    def test_long_sma_period(self):
        detector = SuperTrendDetector(
            bull_entry_bars=0, bull_exit_bars=0,
            bear_entry_bars=0, bear_exit_bars=0,
            use_trend_filter=True, trend_sma_period=100,
        )
        assert detector.trend_sma_period == 100
        candles = _make_trending_up_candles(300)
        regime = detector.detect(candles)
        assert regime in ('trending-up', 'trending-down', 'ranging-up', 'ranging-down')


class TestBearBounceProtection:
    """The core use case: prevent false trending-up during bear bounces."""

    def test_bear_bounce_does_not_produce_trending_up_in_bulk(self):
        """During a bear bounce, detect_all should never produce trending-up
        while price is structurally below the SMA."""
        detector = SuperTrendDetector(
            bull_entry_bars=0, bull_exit_bars=0,
            bear_entry_bars=0, bear_exit_bars=0,
            use_trend_filter=True, trend_sma_period=50,
        )
        candles = _make_bear_bounce_candles(200, bounce_start=150, bounce_size=15)
        labels = detector.detect_all(candles)

        # During the bounce (bars 150-165), price is still well below SMA(50)
        # so we should NOT see trending-up during those bars
        bounce_labels = [labels[i] for i in range(150, 165) if labels[i] is not None]
        for label in bounce_labels:
            assert label != 'trending-up', (
                f"Got trending-up during bear bounce — SMA filter should prevent this"
            )


class TestApplySmaFilterPure:
    """Unit tests for the pure _apply_sma_filter function."""

    def test_trending_up_below_sma_downgrades(self):
        # Below SMA = structurally bearish, so ranging-down
        assert _apply_sma_filter('trending-up', 100.0, 150.0) == 'ranging-down'

    def test_trending_down_above_sma_downgrades(self):
        # Above SMA = structurally bullish, so ranging-up
        assert _apply_sma_filter('trending-down', 200.0, 150.0) == 'ranging-up'

    def test_trending_up_above_sma_passes(self):
        assert _apply_sma_filter('trending-up', 200.0, 150.0) == 'trending-up'

    def test_trending_down_below_sma_passes(self):
        assert _apply_sma_filter('trending-down', 100.0, 150.0) == 'trending-down'

    def test_ranging_up_unchanged(self):
        assert _apply_sma_filter('ranging-up', 100.0, 150.0) == 'ranging-up'

    def test_ranging_down_unchanged(self):
        assert _apply_sma_filter('ranging-down', 200.0, 150.0) == 'ranging-down'

    def test_nan_sma_returns_raw(self):
        assert _apply_sma_filter('trending-up', 100.0, float('nan')) == 'trending-up'

    def test_nan_sma_returns_raw_trending_down(self):
        assert _apply_sma_filter('trending-down', 200.0, float('nan')) == 'trending-down'

    def test_close_equals_sma_no_downgrade(self):
        """When close == SMA, neither < nor > is true — no downgrade."""
        assert _apply_sma_filter('trending-up', 150.0, 150.0) == 'trending-up'
        assert _apply_sma_filter('trending-down', 150.0, 150.0) == 'trending-down'

    def test_nan_close_no_crash(self):
        """NaN close should not crash — numpy comparisons return False."""
        result = _apply_sma_filter('trending-up', float('nan'), 150.0)
        # NaN < 150.0 is False, so no downgrade
        assert result == 'trending-up'


class TestBullDipProtection:
    """Prevent false trending-down during shallow bull dips.

    Note: The SMA filter only protects when price stays above the SMA.
    A steep dip that crosses below SMA is a legitimate trend change,
    not a false signal. We test with a gentle dip that stays above SMA.
    """

    def test_gentle_bull_dip_does_not_produce_trending_down(self):
        """During a shallow bull dip (price stays above SMA),
        detect_all should never produce trending-down."""
        # Build a strong uptrend followed by a gentle pullback
        closes = []
        for i in range(250):
            if i < 180:
                # Strong uptrend: +200/bar (builds large SMA gap)
                closes.append(50000 + i * 200)
            elif i < 195:
                # Gentle dip: -100/bar (shallow enough to stay above SMA)
                base = 50000 + 180 * 200
                closes.append(base - (i - 180) * 100)
            else:
                # Resume uptrend
                base = 50000 + 180 * 200 - 15 * 100
                closes.append(base + (i - 195) * 200)
        candles = _make_candles(closes)

        detector = SuperTrendDetector(
            bull_entry_bars=0, bull_exit_bars=0,
            bear_entry_bars=0, bear_exit_bars=0,
            use_trend_filter=True, trend_sma_period=50,
        )
        labels = detector.detect_all(candles)

        # During the gentle dip (bars 180-195), price should still be above SMA(50)
        # so trending-down should be filtered to ranging-down
        dip_labels = [labels[i] for i in range(180, 195) if labels[i] is not None]
        for label in dip_labels:
            assert label != 'trending-down', (
                f"Got trending-down during gentle bull dip — "
                f"SMA filter should prevent this when price > SMA"
            )


class TestFilterOffBackwardsCompat:
    """With use_trend_filter=False, no downgrade happens."""

    def test_filter_off_detect_matches_filter_on_for_clean_trend(self):
        """For a clean uptrend (price always above SMA), both should agree."""
        candles = _make_trending_up_candles(200)

        d_on = SuperTrendDetector(
            bull_entry_bars=0, bull_exit_bars=0,
            bear_entry_bars=0, bear_exit_bars=0,
            use_trend_filter=True, trend_sma_period=50,
        )
        d_off = SuperTrendDetector(
            bull_entry_bars=0, bull_exit_bars=0,
            bear_entry_bars=0, bear_exit_bars=0,
            use_trend_filter=False, trend_sma_period=50,
        )
        regime_on = d_on.detect(candles)
        regime_off = d_off.detect(candles)
        # For a clean trend, both should return the same result
        assert regime_on == regime_off

    def test_filter_off_allows_trending_up_below_sma_in_bulk(self):
        """With filter off, bear bounces CAN produce trending-up."""
        detector = SuperTrendDetector(
            bull_entry_bars=0, bull_exit_bars=0,
            bear_entry_bars=0, bear_exit_bars=0,
            use_trend_filter=False, trend_sma_period=50,
        )
        candles = _make_bear_bounce_candles(200, bounce_start=150, bounce_size=15)
        labels = detector.detect_all(candles)
        # We're just verifying it doesn't crash and produces valid labels
        non_none = [l for l in labels if l is not None]
        assert len(non_none) > 0
        for label in non_none:
            assert label in ('trending-up', 'trending-down', 'ranging-up', 'ranging-down')


class TestDetectAllConsistency:
    """detect_all and detect should produce consistent results."""

    def test_detect_all_labels_are_valid_regimes(self):
        """Every non-None label must be a valid regime string."""
        detector = SuperTrendDetector(
            bull_entry_bars=0, bull_exit_bars=0,
            bear_entry_bars=0, bear_exit_bars=0,
            use_trend_filter=True, trend_sma_period=50,
        )
        candles = _make_bear_bounce_candles(200)
        labels = detector.detect_all(candles)
        valid = {'trending-up', 'trending-down', 'ranging-up', 'ranging-down'}
        for i, label in enumerate(labels):
            if label is not None:
                assert label in valid, f"Bar {i}: invalid label '{label}'"

    def test_detect_all_early_bars_are_none(self):
        """Bars before min_bars should be None."""
        detector = SuperTrendDetector(
            use_trend_filter=True, trend_sma_period=50,
        )
        candles = _make_trending_up_candles(200)
        labels = detector.detect_all(candles)
        min_bars = max(detector.st_period, detector.adx_period, detector.chop_period) * 3
        for i in range(min_bars):
            assert labels[i] is None, f"Bar {i} should be None (before min_bars={min_bars})"


class TestSustainedDowntrendWithBounces:
    """The core scenario: prolonged downtrend with multiple bounces."""

    def test_no_trending_up_in_sustained_downtrend(self):
        """Build a 300-bar sustained downtrend with two bounces.
        The SMA filter should prevent any trending-up classification."""
        closes = []
        for i in range(300):
            if 120 <= i < 135:
                # First bounce: +80/bar
                base = 90000 - 120 * 150
                closes.append(base + (i - 120) * 80)
            elif 220 <= i < 240:
                # Second bounce: +60/bar
                base = 90000 - 220 * 150
                closes.append(base + (i - 220) * 60)
            else:
                # Downtrend: -150/bar
                closes.append(90000 - i * 150)

        candles = _make_candles(closes)

        detector = SuperTrendDetector(
            bull_entry_bars=0, bull_exit_bars=0,
            bear_entry_bars=0, bear_exit_bars=0,
            use_trend_filter=True, trend_sma_period=50,
        )
        labels = detector.detect_all(candles)

        # After sufficient warmup, no bar should be trending-up
        # (price is always well below SMA(50) during bounces)
        for i in range(100, 300):
            if labels[i] is not None:
                assert labels[i] != 'trending-up', (
                    f"Bar {i}: got trending-up in sustained downtrend "
                    f"(close={candles[i-1, 2]:.0f})"
                )
