"""SmaCrossAlignedV2 — SMA 20/50 direction-aligned + ranging longs.

Trending-up: long-only SMA crossover
Trending-down: short-only SMA crossover
Ranging: long-only SMA crossover (captures moves in transitional zones)

V1 finding: ranging periods contained the biggest winners.
"""
from openquant.regime.composite import CompositeStrategy


class SmaCrossAlignedV2(CompositeStrategy):
    config_file = 'config.yaml'
