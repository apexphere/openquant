"""RegimeRouter V4 — SuperTrend V5 detector, pullback for trends, BB for ranges."""
from openquant.regime.composite import CompositeStrategy


class RegimeRouterV4(CompositeStrategy):
    config_file = 'config.yaml'
