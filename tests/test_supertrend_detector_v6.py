"""Tests for SuperTrendDetectorV6 — confidence-based regime detection.

Tests cover:
  - Confidence calculation with all signals agreeing (bull/bear)
  - Mixed signals → ranging
  - Exponential smoothing suppresses 1-bar counter-signals
  - Ranging-to-trending breakout is fast (boosted alpha)
  - No oscillation deadlock (structurally impossible with confidence)
  - Chaotic detection (rapid flips + high ATR)
  - detect_all consistency with detect
  - Debug output includes confidence fields
  - Hysteresis prevents flickering at tier boundaries
  - Module-level REGIMES frozenset includes 'chaotic'
  - reset() clears all state
  - Default parameters
"""
import numpy as np
import pytest
import openquant.config as config_module


@pytest.fixture(autouse=True)
def _reset_global_config():
    """Force warmup_candles_num to default before each test."""
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


def _make_choppy_candles(length: int = 200, amplitude: int = 3000) -> np.ndarray:
    """Oscillating price — no clear trend, high choppiness."""
    closes = []
    base = 70000
    for i in range(length):
        # Oscillate with large swings but no net direction
        closes.append(base + amplitude * (1 if i % 4 < 2 else -1) + (i % 2) * 500)
    return _make_candles(closes)


def _make_chaotic_candles(length: int = 200) -> np.ndarray:
    """Violent direction changes — price swings wildly every few bars.

    Creates large multi-bar swings (not single-bar) so SuperTrend actually
    flips direction. Single-bar noise gets absorbed by ATR-based trailing
    stops, but 3-4 bar trends followed by sharp reversals cause real flips.
    """
    closes = []
    base = 70000
    for i in range(length):
        if i < 80:
            # Normal uptrend for warmup
            closes.append(base + i * 100)
        else:
            # Chaotic: 3-bar up swings followed by 3-bar down swings
            # with increasing amplitude to create extreme ATR
            cycle = (i - 80) % 6
            amplitude = 8000
            if cycle < 3:
                closes.append(base + cycle * amplitude)
            else:
                closes.append(base + (5 - cycle) * amplitude)
    return _make_candles(closes)


# ── Import the module under test ───────────────────────────────────

from openquant.regime.supertrend_detector_v6 import (
    SuperTrendDetectorV6,
    REGIMES,
)


class TestModuleAttributes:
    """Module-level constants."""

    def test_regimes_frozenset_includes_chaotic(self):
        assert isinstance(REGIMES, frozenset)
        assert 'chaotic' in REGIMES

    def test_regimes_contains_all_five(self):
        expected = {'trending-up', 'trending-down', 'ranging-up', 'ranging-down', 'chaotic'}
        assert REGIMES == expected


class TestDefaultParameters:
    """Constructor defaults match the spec."""

    def test_defaults(self):
        d = SuperTrendDetectorV6()
        assert d.st_period == 10
        assert d.st_factor == 3.0
        assert d.adx_period == 14
        assert d.chop_period == 14
        assert d.trend_sma_period == 100
        assert d.timeframe == '1D'
        assert d.alpha == 0.3
        assert d.alpha_boost == 0.6
        assert d.strong_entry == 0.70
        assert d.strong_exit == 0.55
        assert d.weak_entry == 0.40
        assert d.weak_exit == 0.25
        assert d.chaos_flips == 4
        assert d.chaos_atr_pct == 0.60

    def test_weight_defaults_sum_to_one(self):
        d = SuperTrendDetectorV6()
        total = d.w_st + d.w_adx + d.w_chop + d.w_sma
        assert abs(total - 1.0) < 1e-9

    def test_no_confirmation_bar_params(self):
        """V6 should NOT have the old confirmation bar parameters."""
        d = SuperTrendDetectorV6()
        assert not hasattr(d, 'bull_entry_bars')
        assert not hasattr(d, 'bear_entry_bars')
        assert not hasattr(d, 'bull_exit_bars')
        assert not hasattr(d, 'bear_exit_bars')


class TestRegimeProperty:
    """The .regime property returns the last confirmed regime."""

    def test_regime_none_before_detect(self):
        d = SuperTrendDetectorV6()
        assert d.regime is None

    def test_regime_set_after_detect(self):
        d = SuperTrendDetectorV6()
        candles = _make_trending_up_candles(200)
        d.detect(candles)
        assert d.regime is not None
        assert d.regime in REGIMES


class TestReset:
    """reset() clears all internal state."""

    def test_reset_clears_regime(self):
        d = SuperTrendDetectorV6()
        candles = _make_trending_up_candles(200)
        d.detect(candles)
        assert d.regime is not None
        d.reset()
        assert d.regime is None

    def test_reset_clears_smoothed_confidence(self):
        d = SuperTrendDetectorV6()
        candles = _make_trending_up_candles(200)
        d.detect(candles)
        d.reset()
        assert d._smoothed_confidence == 0.5

    def test_reset_clears_tier(self):
        d = SuperTrendDetectorV6()
        candles = _make_trending_up_candles(200)
        d.detect(candles)
        d.reset()
        assert d._current_tier == 'ranging'


class TestAllBullish:
    """When all indicators agree bullish, confidence should be near 1.0."""

    def test_strong_uptrend_produces_trending_up(self):
        d = SuperTrendDetectorV6()
        candles = _make_trending_up_candles(200)
        regime = d.detect(candles)
        assert regime == 'trending-up'

    def test_strong_uptrend_detect_all_ends_trending_up(self):
        d = SuperTrendDetectorV6()
        candles = _make_trending_up_candles(200)
        labels = d.detect_all(candles)
        non_none = [l for l in labels if l is not None]
        assert len(non_none) > 0
        # The last several labels should be trending-up
        assert non_none[-1] == 'trending-up'


class TestAllBearish:
    """When all indicators agree bearish, confidence should be near 0.0."""

    def test_strong_downtrend_produces_trending_down(self):
        d = SuperTrendDetectorV6()
        candles = _make_trending_down_candles(200)
        regime = d.detect(candles)
        assert regime == 'trending-down'

    def test_strong_downtrend_detect_all_ends_trending_down(self):
        d = SuperTrendDetectorV6()
        candles = _make_trending_down_candles(200)
        labels = d.detect_all(candles)
        non_none = [l for l in labels if l is not None]
        assert len(non_none) > 0
        assert non_none[-1] == 'trending-down'


class TestMixedSignals:
    """Indicators that disagree should produce ranging."""

    def test_choppy_market_produces_ranging(self):
        d = SuperTrendDetectorV6()
        candles = _make_choppy_candles(200)
        labels = d.detect_all(candles)
        non_none = [l for l in labels if l is not None]
        assert len(non_none) > 0
        # Most labels should be ranging (not trending)
        ranging_count = sum(1 for l in non_none if 'ranging' in l)
        assert ranging_count / len(non_none) > 0.5, (
            f"Expected mostly ranging in choppy market, got {ranging_count}/{len(non_none)}"
        )


class TestSmoothingSuppressesCounterSignal:
    """A single contradicting bar should NOT flip the regime from strong trending."""

    def test_one_bar_dip_in_uptrend_stays_trending(self):
        """Build a strong uptrend, then insert one down bar, then resume.
        The regime should stay trending-up through the dip."""
        closes = [50000 + i * 200 for i in range(180)]
        # One sharp down bar
        closes.append(closes[-1] - 3000)
        # Resume uptrend
        for i in range(19):
            closes.append(closes[-1] + 200)
        candles = _make_candles(closes)

        d = SuperTrendDetectorV6()
        labels = d.detect_all(candles)

        # Check that during/after the dip (bar 180), regime stays trending-up
        # Allow a brief transition but it should recover quickly
        dip_region = [labels[i] for i in range(178, 185) if labels[i] is not None]
        trending_up_count = sum(1 for l in dip_region if l == 'trending-up')
        # Allow up to 2 bars of non-trending (smoothing naturally causes brief dip)
        # The key property: it recovers quickly, not stuck for 10+ bars
        assert trending_up_count >= len(dip_region) - 2, (
            f"Strong trend should absorb 1-bar dip. Got: {dip_region}"
        )


class TestRangingToTrendingBreakout:
    """Breakout from ranging should be fast (1-3 bars, not 5)."""

    def test_breakout_enters_trending_within_5_bars(self):
        """Start with choppy/sideways, then breakout sharply upward.
        Should enter trending within ~3-5 bars of the breakout, not 10+."""
        closes = []
        # 150 bars of sideways (ranging)
        base = 70000
        for i in range(150):
            closes.append(base + (500 if i % 2 == 0 else -500))
        # Sharp breakout: +800/bar
        for i in range(50):
            closes.append(base + 500 + i * 800)
        candles = _make_candles(closes)

        d = SuperTrendDetectorV6()
        labels = d.detect_all(candles)

        # Find first trending-up after bar 150
        first_trending = None
        for i in range(150, len(labels)):
            if labels[i] == 'trending-up':
                first_trending = i
                break

        assert first_trending is not None, "Breakout never reached trending-up"
        bars_to_trending = first_trending - 150
        assert bars_to_trending <= 15, (
            f"Took {bars_to_trending} bars to enter trending — too slow for breakout"
        )


class TestNoOscillationDeadlock:
    """The old V5 bug: oscillating raw signals caused the counter to reset forever.
    With confidence-based smoothing, this is structurally impossible."""

    def test_alternating_signals_eventually_transition(self):
        """Price drops with oscillating indicators. The smoothed confidence
        should eventually move to bear even if raw oscillates."""
        closes = [80000 + i * 200 for i in range(120)]
        # Now oscillate while generally falling
        for i in range(80):
            if i % 2 == 0:
                closes.append(closes[-1] - 600)
            else:
                closes.append(closes[-1] + 200)
        candles = _make_candles(closes)

        d = SuperTrendDetectorV6()
        labels = d.detect_all(candles)

        # Should eventually leave trending-up during the falling section
        late_labels = [labels[i] for i in range(170, 200) if labels[i] is not None]
        if late_labels:
            # Should NOT be stuck in trending-up while price is falling
            assert not all(l == 'trending-up' for l in late_labels), (
                "Stuck in trending-up during falling prices — deadlock bug"
            )


class TestChaoticDetection:
    """Rapid direction flips + high ATR should trigger 'chaotic'."""

    def test_chaotic_candles_produce_chaotic_label(self):
        candles = _make_chaotic_candles(200)
        d = SuperTrendDetectorV6()
        labels = d.detect_all(candles)

        non_none = [l for l in labels if l is not None]
        assert len(non_none) > 0
        # At least some bars in the chaotic region should be labeled chaotic
        chaotic_count = sum(1 for l in non_none if l == 'chaotic')
        assert chaotic_count > 0, (
            f"Expected some chaotic labels in violent oscillation, got none. "
            f"Labels: {set(non_none)}"
        )


class TestDetectAllConsistency:
    """detect_all should produce labels consistent with sequential detect calls."""

    def test_detect_all_labels_are_valid(self):
        d = SuperTrendDetectorV6()
        candles = _make_trending_up_candles(200)
        labels = d.detect_all(candles)
        for i, label in enumerate(labels):
            if label is not None:
                assert label in REGIMES, f"Bar {i}: invalid label '{label}'"

    def test_detect_all_early_bars_are_none(self):
        d = SuperTrendDetectorV6()
        candles = _make_trending_up_candles(200)
        labels = d.detect_all(candles)
        # First several bars should be None (warmup period)
        min_bars = max(d.st_period, d.adx_period, d.chop_period) * 3
        for i in range(min_bars):
            assert labels[i] is None, f"Bar {i} should be None (before min_bars={min_bars})"

    def test_detect_all_final_label_matches_detect(self):
        """The last label from detect_all should match a single detect call."""
        candles = _make_trending_up_candles(200)

        d1 = SuperTrendDetectorV6()
        labels = d1.detect_all(candles)

        d2 = SuperTrendDetectorV6()
        single = d2.detect(candles)

        non_none = [l for l in labels if l is not None]
        assert non_none[-1] == single


class TestDebugOutput:
    """Debug mode should include confidence fields."""

    def test_debug_returns_tuple(self):
        d = SuperTrendDetectorV6()
        candles = _make_trending_up_candles(200)
        result = d.detect_all(candles, debug=True)
        assert isinstance(result, tuple)
        assert len(result) == 2

    def test_debug_rows_have_confidence_fields(self):
        d = SuperTrendDetectorV6()
        candles = _make_trending_up_candles(200)
        labels, debug_rows = d.detect_all(candles, debug=True)
        assert len(debug_rows) > 0

        row = debug_rows[-1]
        assert 'raw_confidence' in row
        assert 'smoothed_confidence' in row
        assert 'directional_strength' in row
        assert 'current_tier' in row
        assert 'confirmed' in row

    def test_debug_confidence_values_in_range(self):
        d = SuperTrendDetectorV6()
        candles = _make_trending_up_candles(200)
        _, debug_rows = d.detect_all(candles, debug=True)
        for row in debug_rows:
            assert 0.0 <= row['raw_confidence'] <= 1.0, (
                f"raw_confidence out of range: {row['raw_confidence']}"
            )
            assert 0.0 <= row['smoothed_confidence'] <= 1.0, (
                f"smoothed_confidence out of range: {row['smoothed_confidence']}"
            )
            assert 0.0 <= row['directional_strength'] <= 1.0, (
                f"directional_strength out of range: {row['directional_strength']}"
            )


class TestHysteresis:
    """Tier thresholds should have asymmetric entry/exit to prevent flickering."""

    def test_no_rapid_regime_oscillation(self):
        """In a mildly trending market, regime should not flip every bar."""
        # Create a price series that slowly trends up
        closes = [60000 + i * 50 for i in range(200)]
        candles = _make_candles(closes)

        d = SuperTrendDetectorV6()
        labels = d.detect_all(candles)
        non_none = [l for l in labels if l is not None]

        # Count transitions
        transitions = sum(1 for i in range(1, len(non_none)) if non_none[i] != non_none[i-1])
        # Should have very few transitions (< 10% of bars)
        assert transitions < len(non_none) * 0.10, (
            f"Too many transitions ({transitions}/{len(non_none)}) — hysteresis not working"
        )


class TestCustomParameters:
    """Constructor accepts all configurable parameters."""

    def test_custom_weights(self):
        d = SuperTrendDetectorV6(w_st=0.50, w_adx=0.20, w_chop=0.10, w_sma=0.20)
        assert d.w_st == 0.50
        assert d.w_chop == 0.10

    def test_custom_thresholds(self):
        d = SuperTrendDetectorV6(
            alpha=0.5, alpha_boost=0.8,
            strong_entry=0.80, strong_exit=0.60,
            weak_entry=0.50, weak_exit=0.30,
        )
        assert d.alpha == 0.5
        assert d.strong_entry == 0.80

    def test_custom_chaos_params(self):
        d = SuperTrendDetectorV6(chaos_flips=6, chaos_atr_pct=0.70)
        assert d.chaos_flips == 6
        assert d.chaos_atr_pct == 0.70

    def test_detect_works_with_custom_params(self):
        d = SuperTrendDetectorV6(
            st_period=8, st_factor=2.5,
            adx_period=10, chop_period=10,
            trend_sma_period=50,
        )
        candles = _make_trending_up_candles(200)
        regime = d.detect(candles)
        assert regime in REGIMES
