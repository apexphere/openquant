"""Quality filter protocol and aggregation for regime-aware strategies.

Quality filters score the current regime from 0 (junk) to 10 (pristine).
They sit between regime detection and behavior execution, gating entries
when the detected regime isn't worth trading.

    Candles -> [Detector] -> regime label -> [Quality Filters] -> score 0-10
                                                    |
                                           score < threshold? -> skip entry
"""
import math
from typing import Protocol, runtime_checkable


@runtime_checkable
class QualityFilter(Protocol):
    """Scores the quality of the current regime from 0 (junk) to 10 (pristine).

    All scores are continuous floats in [0, 10]. If a filter cannot compute
    a score (insufficient data, warmup period), it returns None. The
    aggregation layer excludes None scores.
    """

    @property
    def warmup_bars(self) -> int:
        """Minimum candle bars needed before this filter can produce a score."""
        ...

    @property
    def required_timeframe(self) -> str | None:
        """Candle timeframe this filter needs (e.g., '1D', '4h').

        None means use the strategy's route timeframe. The Strategy base
        class calls get_candles() for each filter's required_timeframe
        and passes the correct candle array.
        """
        ...

    @property
    def name(self) -> str:
        """Human-readable filter name for logging/debugging."""
        ...

    def score(self, candles, regime: str) -> float | None:
        """Return quality score 0-10 for the current regime, or None if insufficient data."""
        ...


def aggregate_scores(scores: list[float | None], method: str = 'min') -> float | None:
    """Aggregate quality filter scores, excluding None and NaN values.

    Returns None if no valid scores remain (gate should be bypassed).

    Examples:
        aggregate_scores([7.2, None, 5.4], 'min')  -> 5.4
        aggregate_scores([7.2, None, 5.4], 'mean') -> 6.3
        aggregate_scores([None, None], 'min')       -> None
        aggregate_scores([], 'min')                  -> None
    """
    valid = [s for s in scores if s is not None and not math.isnan(s)]
    if not valid:
        return None
    if method == 'mean':
        return sum(valid) / len(valid)
    return min(valid)
