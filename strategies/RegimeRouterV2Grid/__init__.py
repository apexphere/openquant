"""RegimeRouterV2Grid — grid trading in ranges."""
from openquant.regime.composite import CompositeStrategy


class RegimeRouterV2Grid(CompositeStrategy):
    config_file = 'config.yaml'
