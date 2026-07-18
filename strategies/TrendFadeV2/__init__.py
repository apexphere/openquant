"""TrendFadeV2 — symmetric trend pullback strategy for futures.

Exploits pullbacks in both directions on crypto perpetuals.
Bullish: long pullbacks to fast EMA in confirmed uptrends.
Bearish: short rallies to fast EMA in confirmed downtrends.
Ranging: fade Bollinger Band extremes (mean reversion).
"""
from openquant.regime.composite import CompositeStrategy


class TrendFadeV2(CompositeStrategy):
    config_file = 'config.yaml'
