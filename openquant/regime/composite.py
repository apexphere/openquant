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
import openquant.services.logger as logger


# ── Built-in registry ───────────────────────────────────────────────
# Maps short names in YAML to actual classes. Users can also specify
# full import paths like "mymodule.MyDetector" for custom classes.

_DETECTOR_REGISTRY = {
    'adx': 'openquant.regime.adx_detector.ADXRegimeDetector',
}

_BEHAVIOR_REGISTRY = {
    'bb_mean_reversion': 'openquant.regime.behaviors.bb_mean_reversion.BBMeanReversionBehavior',
    'momentum_rotation': 'openquant.regime.behaviors.momentum_rotation.MomentumRotationBehavior',
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

    def _ensure_config(self) -> dict:
        """Lazy-load the YAML config on first access."""
        if not self._config_loaded:
            self._config = _load_config(self)
            self._config_loaded = True
        return self._config

    # ── Regime composition (overrides from Strategy) ────────────────

    def regime_detector(self):
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
            return  # keep positions
        elif on_switch == 'close_all':
            if self.is_long or self.is_short:
                self.liquidate()
        elif on_switch == 'close_opposite':
            # Close positions that conflict with the new regime direction
            if new_regime == 'trending-up' and self.is_short:
                self.liquidate()
            elif new_regime == 'trending-down' and self.is_long:
                self.liquidate()
            elif 'ranging' in new_regime:
                pass  # ranging allows both directions

    def on_close_position(self, order, closed_trade=None):
        config = self._ensure_config()
        transitions = config.get('transitions', {})
        cooldown = transitions.get('cooldown_bars', 0)
        if cooldown > 0:
            self.vars['last_exit_index'] = self.index
            self.vars['cooldown_bars'] = cooldown

    # ── Hyperparameters from YAML ───────────────────────────────────

    def hyperparameters(self):
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
                # Simple value — use as default, derive type, set narrow range
                hp_list.append({
                    'name': name,
                    'type': type(value),
                    'min': value * 0.5 if isinstance(value, (int, float)) else value,
                    'max': value * 2.0 if isinstance(value, (int, float)) else value,
                    'default': value,
                })
        return hp_list

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
