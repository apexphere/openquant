"""SmaFilterPullback — SMA 20/50 alignment as trend filter + EMA pullback entries.

Hypothesis: SMA crossover is too slow as an entry signal but useful as a trend filter.
Use SMA 20>50 alignment to confirm uptrend, then enter on faster EMA pullback bounces.

Logic:
  - Bullish regime (SuperTrend v7) + trend_pullback behavior
  - Entry: EMA 13/34 pullback bounce with RSI < 70
  - Exit: ATR trailing stop, let trends run
  - No shorts — long-only in confirmed bullish
"""
from openquant.regime.composite import CompositeStrategy


class SmaFilterPullback(CompositeStrategy):
    config_file = 'config.yaml'
