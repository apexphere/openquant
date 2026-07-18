"""SmaCrossRegime — SMA 20/50 crossover gated by regime detection.

Only trades SMA crossover signals during trending regimes.
Sits flat during ranging/cold-start. Uses trend_strength detector.
"""
from openquant.regime.composite import CompositeStrategy


class SmaCrossRegime(CompositeStrategy):
    config_file = 'config.yaml'
