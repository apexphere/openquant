"""Short-side trend pullback behavior for trending-down markets.

Mirror of TrendPullbackBehavior for downtrends. Waits for price to
rally back up to the fast EMA, then enters short when price rejects
back below it. The rally creates a better entry price and the rejection
confirms sellers are still in control.

Entry (short):
    1. Fast EMA below slow EMA (confirmed downtrend structure on 4h)
    2. Previous 4h bar's high touched or poked above the fast EMA (the rally)
    3. Current 4h bar closes back below the fast EMA (rejection confirmed)
    4. RSI is not oversold (avoid shorting into capitulation)

Exit:
    - ATR-based stop loss (2x ATR above entry)
    - Trailing stop (ATR-based)
    - No fixed take-profit — let downtrends run

Reads from strategy.hp:
    risk_pct, trail_pct
    pb_fast_ema (default 13), pb_slow_ema (default 34)
    pb_rsi_period (default 14), pb_rsi_min (default 30)
    pb_atr_period (default 14), pb_atr_sl_mult (default 2.0)
"""
import openquant.indicators as ta


class TrendPullbackShortBehavior:
    """Short pullback entries in trending-down markets.

    Entry: price rallied to fast EMA and rejected.
    Stop: ATR-based, trails with profit.
    No fixed TP — let downtrends run.
    """

    def should_long(self, strategy) -> bool:
        return False

    def should_short(self, strategy) -> bool:
        if _in_cooldown(strategy):
            return False

        fast_period = strategy.hp.get('pb_fast_ema', 13)
        slow_period = strategy.hp.get('pb_slow_ema', 34)
        rsi_period = strategy.hp.get('pb_rsi_period', 14)
        rsi_min = strategy.hp.get('pb_rsi_min', 30)

        # Use 4h candles for pullback detection (15m is too noisy)
        candles_4h = strategy.get_candles(strategy.exchange, strategy.symbol, strategy.hp.get('pb_timeframe', '4h'))
        if candles_4h is None or len(candles_4h) < slow_period + 5:
            return False

        fast_ema = ta.ema(candles_4h, period=fast_period, sequential=True)
        slow_ema = ta.ema(candles_4h, period=slow_period, sequential=True)
        rsi = ta.rsi(candles_4h, period=rsi_period)

        # Trend structure: fast EMA below slow EMA (confirmed downtrend)
        if fast_ema[-1] >= slow_ema[-1]:
            return False

        # Current 4h bar closes below fast EMA (rejection confirmed)
        if candles_4h[-1, 2] >= fast_ema[-1]:
            return False

        # Previous 4h bar's high touched or poked above fast EMA (the rally)
        if candles_4h[-2, 3] < fast_ema[-2]:
            return False

        # RSI not oversold (avoid shorting into capitulation)
        if rsi < rsi_min:
            return False

        return True

    def go_long(self, strategy) -> None:
        pass

    def go_short(self, strategy) -> None:
        atr_period = strategy.hp.get('pb_atr_period', 14)
        atr_mult = strategy.hp.get('pb_atr_sl_mult', 2.0)

        candles_4h = strategy.get_candles(strategy.exchange, strategy.symbol, strategy.hp.get('pb_timeframe', '4h'))
        atr = ta.atr(candles_4h, period=atr_period)
        qty = _size(strategy)

        strategy.sell = qty, strategy.price
        strategy.stop_loss = qty, strategy.price + (atr * atr_mult)

    def update_position(self, strategy) -> None:
        if not strategy.is_short:
            return

        atr_period = strategy.hp.get('pb_atr_period', 14)
        trail_pct = strategy.hp.get('trail_pct', 0.03)

        candles_4h = strategy.get_candles(strategy.exchange, strategy.symbol, strategy.hp.get('pb_timeframe', '4h'))
        atr = ta.atr(candles_4h, period=atr_period)

        # Trail stop: min of percentage-based and ATR-based (for shorts, lower is better)
        pct_trail = strategy.price * (1 + trail_pct)
        atr_trail = strategy.price + (atr * 1.5)
        trail_price = min(pct_trail, atr_trail)

        if trail_price < strategy.average_stop_loss:
            strategy.stop_loss = abs(strategy.position.qty), trail_price


def _size(strategy) -> float:
    capital = strategy.balance * strategy.hp.get('risk_pct', 0.05)
    return max(0.001, round(capital / strategy.price, 3))


def _in_cooldown(strategy) -> bool:
    cooldown_bars = strategy.vars.get('cooldown_bars', 8)
    last_exit = strategy.vars.get('last_exit_index', -999999)
    return (strategy.index - last_exit) < cooldown_bars
