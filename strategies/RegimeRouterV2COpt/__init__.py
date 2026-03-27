"""RegimeRouterV2COpt — V2C with Trial 413 optimized params.
Training Sharpe: 0.66, Testing Sharpe: 1.21
"""
from openquant.regime.composite import CompositeStrategy


class RegimeRouterV2COpt(CompositeStrategy):
    config_file = 'config.yaml'
