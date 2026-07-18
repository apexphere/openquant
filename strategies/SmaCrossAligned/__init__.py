"""SmaCrossAligned — SMA 20/50 crossover direction-aligned with regime.

Trending-up: long-only SMA crossover (golden cross entries)
Trending-down: short-only SMA crossover (death cross entries)
Ranging: flat (no trading)

Eliminates counter-trend trades that bleed PnL in SmaCrossRegime.
"""
from openquant.regime.composite import CompositeStrategy


class SmaCrossAligned(CompositeStrategy):
    config_file = 'config.yaml'
