"""SmaCross2050E — SMA 20/50 crossover gated by V7 SuperTrend regime.

Only trades SMA crossover signals during bullish regime.
Sits flat during bearish and ranging. Uses supertrend_v7 detector
(confidence-based, 3-regime model) for faster regime transitions
than lagging SMA/EMA-based detectors.
"""
from openquant.regime.composite import CompositeStrategy


class SmaCross2050E(CompositeStrategy):
    config_file = 'config.yaml'
