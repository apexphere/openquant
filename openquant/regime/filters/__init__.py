"""Built-in quality filter registry.

Maps short names (used in YAML configs) to importable class paths.
Custom filters can use full dotted paths instead.
"""

FILTER_REGISTRY = {
    'candle_energy': 'openquant.regime.filters.candle_energy.CandleEnergyFilter',
}
