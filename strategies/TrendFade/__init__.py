"""TrendFade — ride confirmed trends, fade ranges.

SuperTrend V7 detector (3-regime: bullish/bearish/ranging).
Bullish: buy pullbacks to fast EMA in confirmed uptrends.
Ranging: fade Bollinger Band extremes (mean reversion).
Bearish: flat (capital preservation).
"""
from openquant.regime.composite import CompositeStrategy


class TrendFade(CompositeStrategy):
    config_file = 'config.yaml'
