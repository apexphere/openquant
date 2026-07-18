"""RegimeRouterV2C — daily EMA(8/21) pullback variant."""
from openquant.regime.composite import CompositeStrategy


class RegimeRouterV2C(CompositeStrategy):
    config_file = 'config.yaml'
