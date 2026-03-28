"""RegimeRouterV2Breakout — breakout for trends, BB for ranges."""
from openquant.regime.composite import CompositeStrategy


class RegimeRouterV2Breakout(CompositeStrategy):
    config_file = 'config.yaml'
