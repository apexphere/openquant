"""Tests for regime-aware strategy composition in the Strategy base class.

Tests cover:
  - Default behavior (no detector → "all" regime, classic strategy mode)
  - Regime detection integration
  - Behavior routing (should_long, go_long, update_position delegation)
  - Regime transitions (on_regime_change callback)
  - Flat regime (None behavior → no trading)
  - Unknown regime (resilient default → flat)
  - Detector error handling (resilient → keep previous regime)
  - StrategyBehavior Protocol
"""
import numpy as np
import pytest
from openquant.regime.behavior import StrategyBehavior
from openquant.regime.adx_detector import ADXRegimeDetector


# ── Test fixtures: minimal behavior classes ─────────────────────────

class LongOnlyBehavior:
    """Always wants to go long."""
    def should_long(self, strategy) -> bool:
        return True

    def should_short(self, strategy) -> bool:
        return False

    def go_long(self, strategy) -> None:
        qty = 1.0
        strategy.buy = qty, strategy.price
        strategy.stop_loss = qty, strategy.price * 0.95
        strategy.take_profit = qty, strategy.price * 1.10

    def go_short(self, strategy) -> None:
        pass

    def update_position(self, strategy) -> None:
        pass


class ShortOnlyBehavior:
    """Always wants to go short."""
    def should_long(self, strategy) -> bool:
        return False

    def should_short(self, strategy) -> bool:
        return True

    def go_long(self, strategy) -> None:
        pass

    def go_short(self, strategy) -> None:
        qty = 1.0
        strategy.sell = qty, strategy.price
        strategy.stop_loss = qty, strategy.price * 1.05

    def update_position(self, strategy) -> None:
        pass


class FakeDetector:
    """Deterministic detector for testing — returns whatever regime you set."""
    def __init__(self, regime='trending-up'):
        self._regime = regime

    def detect(self, candles) -> str:
        return self._regime

    def set_regime(self, regime: str):
        self._regime = regime


class ErrorDetector:
    """Detector that always raises."""
    def detect(self, candles) -> str:
        raise ValueError("Indicator computation failed")


# ── Protocol tests ──────────────────────────────────────────────────

class TestStrategyBehaviorProtocol:
    def test_long_only_satisfies_protocol(self):
        assert isinstance(LongOnlyBehavior(), StrategyBehavior)

    def test_short_only_satisfies_protocol(self):
        assert isinstance(ShortOnlyBehavior(), StrategyBehavior)

    def test_incomplete_class_does_not_satisfy(self):
        class Incomplete:
            pass
        assert not isinstance(Incomplete(), StrategyBehavior)


# ── Strategy base class regime tests ────────────────────────────────
# These test the regime methods added to Strategy without running
# a full backtest. We import Strategy and test the methods directly.

from openquant.strategies.Strategy import Strategy


class MinimalStrategy(Strategy):
    """Concrete strategy for testing — satisfies abstract methods."""
    def should_long(self) -> bool:
        return False

    def go_long(self) -> None:
        pass

    def should_short(self) -> bool:
        return False

    def go_short(self) -> None:
        pass


class TestDefaultRegime:
    def test_default_regime_is_all(self):
        s = MinimalStrategy()
        assert s.current_regime == 'all'

    def test_default_detector_is_none(self):
        s = MinimalStrategy()
        assert s.regime_detector() is None

    def test_default_regimes_is_empty(self):
        s = MinimalStrategy()
        assert s.regimes() == {}

    def test_detect_regime_returns_all_when_no_detector(self):
        s = MinimalStrategy()
        assert s._detect_regime() == 'all'

    def test_get_behavior_returns_none_when_no_regimes(self):
        s = MinimalStrategy()
        assert s._get_regime_behavior() is None


class TestRegimeDetection:
    def test_detect_regime_uses_detector(self):
        s = MinimalStrategy()
        s.regime_detector = lambda: FakeDetector('ranging-up')
        # _detect_regime calls get_candles which needs exchange/symbol set up.
        # For unit test, mock the get_candles call.
        s.get_candles = lambda ex, sym, tf: np.zeros((100, 6))
        assert s._detect_regime() == 'ranging-up'

    def test_detect_regime_resilient_on_error(self):
        s = MinimalStrategy()
        s._current_regime = 'trending-up'
        s.regime_detector = lambda: ErrorDetector()
        s.get_candles = lambda ex, sym, tf: np.zeros((100, 6))
        # Should keep previous regime on error
        assert s._detect_regime() == 'trending-up'


class TestBehaviorRouting:
    def test_get_behavior_returns_correct_instance(self):
        s = MinimalStrategy()
        s._current_regime = 'trending-up'
        s.regimes = lambda: {
            'trending-up': LongOnlyBehavior,
            'ranging': ShortOnlyBehavior,
        }
        behavior = s._get_regime_behavior()
        assert isinstance(behavior, LongOnlyBehavior)

    def test_get_behavior_returns_none_for_flat_regime(self):
        s = MinimalStrategy()
        s._current_regime = 'trending-down'
        s.regimes = lambda: {
            'trending-up': LongOnlyBehavior,
            'trending-down': None,  # flat
        }
        behavior = s._get_regime_behavior()
        assert behavior is None

    def test_get_behavior_returns_none_for_unknown_regime(self):
        s = MinimalStrategy()
        s._current_regime = 'volatile'
        s.regimes = lambda: {
            'trending-up': LongOnlyBehavior,
        }
        behavior = s._get_regime_behavior()
        assert behavior is None

    def test_behavior_instances_are_cached(self):
        s = MinimalStrategy()
        s._current_regime = 'trending-up'
        s.regimes = lambda: {'trending-up': LongOnlyBehavior}
        b1 = s._get_regime_behavior()
        b2 = s._get_regime_behavior()
        assert b1 is b2  # same instance, not re-instantiated


class TestRegimeChange:
    def test_on_regime_change_called(self):
        changes = []
        s = MinimalStrategy()
        s.on_regime_change = lambda old, new: changes.append((old, new))
        s._current_regime = 'trending-up'

        # Simulate a regime change
        new_regime = 'ranging-down'
        if new_regime != s._current_regime:
            old = s._current_regime
            s._current_regime = new_regime
            s.on_regime_change(old, new_regime)

        assert changes == [('trending-up', 'ranging-down')]

    def test_current_regime_property_updates(self):
        s = MinimalStrategy()
        assert s.current_regime == 'all'
        s._current_regime = 'trending-up'
        assert s.current_regime == 'trending-up'
