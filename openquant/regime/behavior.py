"""Strategy behavior protocol for regime-aware composition.

A StrategyBehavior defines what a strategy does in a specific market regime.
Sub-behaviors are method bags that operate on the parent strategy's state
via delegation — they are NOT Strategy instances.

Usage:
    class TrendFollowBehavior:
        def should_long(self, strategy) -> bool:
            return strategy.price > ta.sma(strategy.candles, 50)

        def go_long(self, strategy) -> None:
            qty = (strategy.balance * 0.05) / strategy.price
            strategy.buy = qty, strategy.price
            strategy.stop_loss = qty, strategy.price * 0.95
"""
from typing import Protocol, runtime_checkable


@runtime_checkable
class StrategyBehavior(Protocol):
    """Interface for regime-specific strategy behaviors.

    All methods receive the parent Strategy instance so they can access
    market data (candles, price, indicators) and submit orders (buy, sell,
    stop_loss, take_profit).

    Methods are optional — unimplemented methods fall back to the default
    behavior (no entry, no exit modification).
    """

    def should_long(self, strategy) -> bool:
        """Return True if the strategy should enter a long position."""
        ...

    def should_short(self, strategy) -> bool:
        """Return True if the strategy should enter a short position."""
        ...

    def go_long(self, strategy) -> None:
        """Set entry, stop-loss, and take-profit for a long position."""
        ...

    def go_short(self, strategy) -> None:
        """Set entry, stop-loss, and take-profit for a short position."""
        ...

    def update_position(self, strategy) -> None:
        """Manage an open position (trailing stops, exits, etc.)."""
        ...
