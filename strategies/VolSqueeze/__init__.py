"""VolSqueeze -- volatility-regime composite strategy.

Thesis: catch breakouts after volatility squeezes.
- High-vol: Donchian breakout (expansion = directional move)
- Low-vol: BB mean-reversion (compressed range = fade extremes)
- Normal: trend-follow (moderate conditions = ride the trend)
- Cold-start: flat

All wiring lives in config.yaml.
"""
from openquant.regime.composite import CompositeStrategy


class VolSqueeze(CompositeStrategy):
    config_file = 'config.yaml'
