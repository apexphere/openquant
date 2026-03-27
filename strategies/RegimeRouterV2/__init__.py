"""RegimeRouter V2 — pure YAML-configured composite strategy.

All wiring (detector, regime→behavior mapping, parameters) lives in config.yaml.
This file is just the entry point.
"""
from openquant.regime.composite import CompositeStrategy


class RegimeRouterV2(CompositeStrategy):
    config_file = 'config.yaml'
