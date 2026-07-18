"""SmaCrossAlignedV3 — SMA 20/50 with supertrend_v7 detector.

Uses the faster 3-regime supertrend detector instead of trend_strength.
Bullish: long-only SMA crossover
Bearish: short-only SMA crossover
Ranging: long-only SMA crossover
"""
from openquant.regime.composite import CompositeStrategy


class SmaCrossAlignedV3(CompositeStrategy):
    config_file = 'config.yaml'
