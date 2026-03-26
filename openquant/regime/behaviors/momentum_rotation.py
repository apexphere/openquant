"""Momentum rotation behavior for trending-up markets.

Extracted from RegimeRouter's trending-up logic. Goes long on the top-K
coins by momentum (4h return). Rebalances periodically. Exits positions
on coins that drop out of the top-K.

Used as a sub-behavior in composite strategies:
    regimes = {
        'trending-up': MomentumRotationBehavior,
    }
"""
import openquant.indicators as ta


UNIVERSE = [
    'BTC-USDT', 'ETH-USDT', 'SOL-USDT', 'BNB-USDT', 'XRP-USDT',
    'DOGE-USDT', 'ADA-USDT', 'AVAX-USDT', 'LINK-USDT', 'DOT-USDT',
]


class MomentumRotationBehavior:
    """Momentum rotation: long the top-K coins by recent return.

    Reads hyperparameters from the parent strategy's self.hp dict:
        momentum_lookback, risk_pct, sl_pct, tp_pct, trail_pct

    Uses strategy.vars for internal state:
        _mr_selected_coins, _mr_last_rebalance_index
    """

    def __init__(self):
        self._top_k = 3
        self._rebalance_bars = 96 * 7  # 7 days in 15m bars

    def should_long(self, strategy) -> bool:
        if _in_cooldown(strategy):
            return False
        self._rebalance_if_needed(strategy)
        return strategy.symbol in strategy.vars.get('_mr_selected_coins', [])

    def should_short(self, strategy) -> bool:
        return False  # trending-up: long only

    def go_long(self, strategy) -> None:
        qty = _size(strategy)
        strategy.buy = qty, strategy.price
        strategy.stop_loss = qty, strategy.price * (1 - strategy.hp['sl_pct'])
        strategy.take_profit = qty, strategy.price * (1 + strategy.hp['tp_pct'])

    def go_short(self, strategy) -> None:
        pass

    def update_position(self, strategy) -> None:
        if not strategy.is_long:
            return

        # Trailing stop
        trail_price = strategy.price * (1 - strategy.hp['trail_pct'])
        if trail_price > strategy.average_stop_loss:
            strategy.stop_loss = strategy.position.qty, trail_price

        # Exit if coin dropped out of top-K
        self._rebalance_if_needed(strategy)
        if strategy.symbol not in strategy.vars.get('_mr_selected_coins', []):
            strategy.liquidate()

    def _rebalance_if_needed(self, strategy) -> None:
        last_rebalance = strategy.vars.get('_mr_last_rebalance_index', -999999)
        if strategy.index - last_rebalance < self._rebalance_bars:
            return

        lookback = strategy.hp.get('momentum_lookback', 42)
        scores = {}
        for sym in UNIVERSE:
            try:
                c = strategy.get_candles(strategy.exchange, sym, '4h')
                if len(c) < lookback + 5:
                    scores[sym] = 0.0
                    continue
                scores[sym] = (c[-1, 2] - c[-lookback, 2]) / c[-lookback, 2]
            except Exception:
                scores[sym] = 0.0

        ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        strategy.vars['_mr_selected_coins'] = [s for s, _ in ranked[:self._top_k]]
        strategy.vars['_mr_last_rebalance_index'] = strategy.index


# ── Shared helpers ──────────────────────────────────────────────────

def _size(strategy) -> float:
    capital = strategy.balance * strategy.hp['risk_pct']
    return max(0.001, round(capital / strategy.price, 3))


def _in_cooldown(strategy) -> bool:
    cooldown_bars = strategy.vars.get('cooldown_bars', 8)
    last_exit = strategy.vars.get('last_exit_index', -999999)
    return (strategy.index - last_exit) < cooldown_bars
