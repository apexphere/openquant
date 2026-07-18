"""RegimeRouterV3 — v3 breakout detector, breakout for trends, BB for ranges."""
from openquant.regime.composite import CompositeStrategy


class RegimeRouterV3(CompositeStrategy):
    config_file = 'config.yaml'
