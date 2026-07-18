"""RegimeRouterV2B — 4h EMA(21) pullback variant."""
from openquant.regime.composite import CompositeStrategy


class RegimeRouterV2B(CompositeStrategy):
    config_file = 'config.yaml'
