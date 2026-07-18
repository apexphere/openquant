"""RegimeRouterV2Opt — V2 with optimizer-found params."""
from openquant.regime.composite import CompositeStrategy


class RegimeRouterV2Opt(CompositeStrategy):
    config_file = 'config.yaml'
