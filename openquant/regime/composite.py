"""YAML-driven composite strategy loader.

Loads a regime-aware composite strategy from a YAML config file.
YAML handles wiring (detector, behaviors, params, transitions).
Python classes handle logic (custom detectors, custom behaviors).

Usage:
    # strategies/MyComposite/__init__.py
    from openquant.regime.composite import CompositeStrategy
    class MyComposite(CompositeStrategy):
        config_file = 'config.yaml'
"""
import os
import yaml
from importlib import import_module

from openquant.strategies import Strategy
import openquant.helpers as jh
import openquant.services.logger as logger


# ── Built-in registry ───────────────────────────────────────────────
# Maps short names in YAML to actual classes. Users can also specify
# full import paths like "mymodule.MyDetector" for custom classes.

_DETECTOR_REGISTRY = {
    'adx': 'openquant.regime.adx_detector.ADXRegimeDetector',
    'ema_adx': 'openquant.regime.ema_adx_detector.EmaAdxDetector',
    'volatility': 'openquant.regime.volatility_detector.VolatilityRegimeDetector',
    'trend_strength': 'openquant.regime.trend_strength_detector.TrendStrengthDetector',
    'breakout_v3': 'openquant.regime.breakout_detector.BreakoutDetector',
    'momentum_v4': 'openquant.regime.momentum_detector.MomentumDetector',
    'supertrend_v5': 'openquant.regime.supertrend_detector.SuperTrendDetector',
}

_BEHAVIOR_REGISTRY = {
    'bb_mean_reversion': 'openquant.regime.behaviors.bb_mean_reversion.BBMeanReversionBehavior',
    'momentum_rotation': 'openquant.regime.behaviors.momentum_rotation.MomentumRotationBehavior',
    'trend_follow': 'openquant.regime.behaviors.trend_follow.TrendFollowBehavior',
    'trend_pullback': 'openquant.regime.behaviors.trend_pullback.TrendPullbackBehavior',
    'trend_pullback_short': 'openquant.regime.behaviors.trend_pullback_short.TrendPullbackShortBehavior',
    'grid': 'openquant.regime.behaviors.grid.GridBehavior',
    'breakout': 'openquant.regime.behaviors.breakout.BreakoutBehavior',
}

_FILTER_REGISTRY = {
    'candle_energy': 'openquant.regime.filters.candle_energy.CandleEnergyFilter',
}


def _resolve_class(name: str, registry: dict):
    """Resolve a short name or dotted import path to an actual class."""
    # Check built-in registry first
    if name in registry:
        dotted_path = registry[name]
    else:
        dotted_path = name

    # Split into module path and class name
    parts = dotted_path.rsplit('.', 1)
    if len(parts) != 2:
        raise ValueError(f'Cannot resolve class: "{name}". '
                         f'Use a built-in name ({list(registry.keys())}) '
                         f'or a dotted path like "mymodule.MyClass".')
    module_path, class_name = parts
    try:
        module = import_module(module_path)
        return getattr(module, class_name)
    except (ImportError, AttributeError) as e:
        raise ValueError(f'Cannot import "{dotted_path}": {e}') from e


def _load_config_for_class(cls) -> dict:
    """Load YAML config using the class definition (no instance needed).

    Used by the optimizer which calls hyperparameters(None) to discover
    parameter ranges without a live strategy instance.
    """
    config_file = getattr(cls, 'config_file', 'config.yaml')
    import sys
    module = sys.modules[cls.__module__]
    strategy_dir = os.path.dirname(os.path.abspath(module.__file__))
    config_path = os.path.join(strategy_dir, config_file)

    if not os.path.exists(config_path):
        raise FileNotFoundError(
            f'Composite strategy config not found: {config_path}. '
            f'Create a config.yaml in your strategy directory.')

    with open(config_path, 'r') as f:
        return yaml.safe_load(f)


def _load_config(strategy_instance) -> dict:
    """Load and parse the YAML config file relative to the strategy's directory."""
    config_file = getattr(strategy_instance, 'config_file', 'config.yaml')

    # Resolve path relative to the strategy's __init__.py
    import sys
    module = sys.modules[strategy_instance.__class__.__module__]
    strategy_dir = os.path.dirname(os.path.abspath(module.__file__))
    config_path = os.path.join(strategy_dir, config_file)

    if not os.path.exists(config_path):
        raise FileNotFoundError(
            f'Composite strategy config not found: {config_path}. '
            f'Create a config.yaml in your strategy directory.')

    with open(config_path, 'r') as f:
        return yaml.safe_load(f)


class CompositeStrategy(Strategy):
    """Base class for YAML-configured composite strategies.

    Subclass this and set config_file to your YAML config:

        class MyStrategy(CompositeStrategy):
            config_file = 'config.yaml'

    The YAML defines:
      - detector: regime detection (type, params)
      - regimes: behavior mapping per regime
      - params: shared hyperparameters
      - transitions: what happens on regime switch
      - data_routes: extra timeframes needed
    """

    config_file = 'config.yaml'

    def __init__(self):
        super().__init__()
        self._detector = None
        self._config = None
        self._config_loaded = False
        self._fixed_params_injected = False

    def _ensure_config(self) -> dict:
        """Lazy-load the YAML config on first access."""
        if not self._config_loaded:
            self._config = _load_config(self)
            self._config_loaded = True
        return self._config

    def _inject_fixed_params(self) -> None:
        """Merge non-numeric YAML params into hp.

        The optimizer only sets tunable (numeric) params on strategy.hp.
        Fixed params (strings, bools) from the YAML config must be injected
        so behaviors can read them via strategy.hp.get('pb_timeframe', ...).
        """
        if self._fixed_params_injected or self.hp is None:
            return
        self._fixed_params_injected = True
        config = self._ensure_config()
        for name, value in config.get('params', {}).items():
            if isinstance(value, dict):
                continue  # tunable param with min/max — already in hp
            if not isinstance(value, (int, float)):
                # Fixed param (string, bool) — inject if not already set
                if name not in self.hp:
                    self.hp[name] = value

    # ── Regime composition (overrides from Strategy) ────────────────

    def regime_detector(self):
        self._inject_fixed_params()
        if self.hp is None:
            return None

        if self._detector is not None:
            return self._detector

        config = self._ensure_config()
        detector_cfg = config.get('detector')
        if not detector_cfg:
            return None

        detector_type = detector_cfg.get('type', 'adx')
        DetectorClass = _resolve_class(detector_type, _DETECTOR_REGISTRY)

        # Build detector params — merge YAML detector params with strategy hp
        params = dict(detector_cfg.get('params', {}))
        self._detector = DetectorClass(**params)
        return self._detector

    def regimes(self) -> dict:
        config = self._ensure_config()
        regimes_cfg = config.get('regimes', {})
        result = {}
        for regime_name, regime_def in regimes_cfg.items():
            if regime_def is None:
                result[regime_name] = None  # flat
            elif isinstance(regime_def, str):
                # Short form: just a behavior name
                result[regime_name] = _resolve_class(regime_def, _BEHAVIOR_REGISTRY)
            elif isinstance(regime_def, dict):
                behavior_name = regime_def.get('behavior')
                if behavior_name is None:
                    result[regime_name] = None
                else:
                    result[regime_name] = _resolve_class(behavior_name, _BEHAVIOR_REGISTRY)
            else:
                result[regime_name] = None
        return result

    def on_regime_change(self, old_regime, new_regime):
        config = self._ensure_config()
        transitions = config.get('transitions', {})
        on_switch = transitions.get('on_switch', 'close_all')

        if on_switch == 'hold':
            return

        # Only close when the BEHAVIOR changes, not just the regime label.
        # ranging-up → ranging-down both use the same behavior (e.g. BB MR)
        # so closing the position is wasteful.
        regimes_cfg = config.get('regimes', {})
        old_behavior = regimes_cfg.get(old_regime)
        new_behavior = regimes_cfg.get(new_regime)
        if old_behavior == new_behavior:
            return  # same behavior — keep position

        if on_switch == 'close_all':
            if self.is_long or self.is_short:
                self.liquidate()
        elif on_switch == 'close_opposite':
            if new_regime == 'trending-up' and self.is_short:
                self.liquidate()
            elif new_regime == 'trending-down' and self.is_long:
                self.liquidate()
            elif 'ranging' in new_regime:
                pass

    def on_close_position(self, order, closed_trade=None):
        config = self._ensure_config()
        transitions = config.get('transitions', {})
        cooldown = transitions.get('cooldown_bars', 0)
        if cooldown > 0:
            self.vars['last_exit_index'] = self.index
            self.vars['cooldown_bars'] = cooldown

    # ── Hyperparameters from YAML ───────────────────────────────────

    def hyperparameters(self):
        # Jesse's optimizer calls strategy_class.hyperparameters(None) to
        # discover parameter ranges without a live instance. Load config
        # from the class definition in that case.
        if self is None:
            # Find the actual subclass by walking the MRO of whoever
            # defined config_file. The optimizer imported the class already.
            from openquant.routes import router
            strategy_class = jh.get_strategy_class(router.routes[0].strategy_name)
            config = _load_config_for_class(strategy_class)
        else:
            config = self._ensure_config()
        params = config.get('params', {})

        hp_list = []
        for name, value in params.items():
            if isinstance(value, dict):
                # Full definition with min/max
                hp_list.append({
                    'name': name,
                    'type': type(value.get('default', 0)),
                    'min': value.get('min', 0),
                    'max': value.get('max', 100),
                    'default': value.get('default', 0),
                })
            else:
                # Simple value — skip non-numeric (strings, bools are fixed config)
                if not isinstance(value, (int, float)):
                    continue
                hp_list.append({
                    'name': name,
                    'type': type(value),
                    'min': value * 0.5,
                    'max': value * 2.0,
                    'default': value,
                })
        return hp_list

    # ── Quality filters from YAML ────────────────────────────────────

    def quality_filters(self) -> list:
        config = self._ensure_config()
        filters_cfg = config.get('quality_filters', [])
        if not filters_cfg:
            return []

        result = []
        for filter_def in filters_cfg:
            if isinstance(filter_def, str):
                filter_type = filter_def
                params = {}
                enabled = True
            elif isinstance(filter_def, dict):
                filter_type = filter_def.get('type')
                params = dict(filter_def.get('params', {}))
                enabled = filter_def.get('enabled', True)
            else:
                continue

            if not enabled:
                continue

            FilterClass = _resolve_class(filter_type, _FILTER_REGISTRY)
            result.append(FilterClass(**params))
        return result

    @property
    def min_quality(self) -> float:
        config = self._ensure_config()
        return float(config.get('min_quality', 0))

    @property
    def score_aggregation(self) -> str:
        config = self._ensure_config()
        return config.get('score_aggregation', 'min')

    # ── Fallback methods (when no behavior is active) ───────────────

    def should_long(self) -> bool:
        return False

    def should_short(self) -> bool:
        return False

    def go_long(self):
        pass

    def go_short(self):
        pass

    def update_position(self):
        pass

    def should_cancel_entry(self):
        return False

    def filters(self):
        return []
