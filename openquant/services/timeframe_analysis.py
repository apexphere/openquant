"""Timeframe analysis: compare indicator values across timeframes for a date range.

Answers the question: "Which timeframe should I use for this indicator to capture
the actual price structure?" A BB on 15m sees intraday noise. A BB on 4h sees the
real range. This tool shows you the difference with real data.
"""
import numpy as np
import openquant.indicators as ta
import openquant.helpers as jh
from openquant.services.candle_service import get_candles_from_db


def analyze_timeframes(
    exchange: str,
    symbol: str,
    start_date: str,
    finish_date: str,
    indicator: str = 'bb',
    period: int = 20,
    timeframes: list = None,
    bb_mult: float = 2.0,
) -> dict:
    """Compare an indicator across multiple timeframes.

    Returns a dict with per-timeframe stats showing coverage, indicator values,
    and how well each timeframe captures the price structure.
    """
    if timeframes is None:
        timeframes = ['15m', '1h', '4h', '1D']

    start_ts = jh.date_to_timestamp(start_date)
    finish_ts = jh.date_to_timestamp(finish_date)
    duration_days = (finish_ts - start_ts) / (1000 * 86400)

    # Get 1m candles for price reference
    _, candles_1m = get_candles_from_db(
        exchange, symbol, '1m', start_ts, finish_ts,
        warmup_candles_num=0, caching=False, is_for_jesse=True
    )
    if candles_1m is None:
        candles_1m = np.array([])

    price_high = float(np.max(candles_1m[:, 3])) if len(candles_1m) > 0 else 0
    price_low = float(np.min(candles_1m[:, 4])) if len(candles_1m) > 0 else 0
    price_range_pct = (price_high - price_low) / price_low * 100 if price_low > 0 else 0

    results = []
    for tf in timeframes:
        try:
            tf_minutes = _timeframe_to_minutes(tf)
            lookback_hours = (period * tf_minutes) / 60
            lookback_days = lookback_hours / 24
            warmup = period + 10

            warmup_candles, trading_candles = get_candles_from_db(
                exchange, symbol, tf, start_ts, finish_ts,
                warmup_candles_num=warmup, caching=False, is_for_jesse=False
            )
            # Combine warmup + trading candles for indicator calculation
            if warmup_candles is not None and trading_candles is not None:
                candles = np.concatenate([warmup_candles, trading_candles])
            elif trading_candles is not None:
                candles = trading_candles
            else:
                candles = None

            if candles is None or len(candles) < period + 1:
                results.append({
                    'timeframe': tf,
                    'error': f'insufficient candles ({len(candles)})',
                })
                continue

            entry = {
                'timeframe': tf,
                'candle_count': len(candles),
                'lookback_hours': round(lookback_hours, 1),
                'lookback_days': round(lookback_days, 1),
                'coverage_vs_period': round(lookback_days / duration_days * 100, 1),
            }

            if indicator == 'bb':
                entry.update(_analyze_bb(candles, period, bb_mult))
            elif indicator == 'ema':
                entry.update(_analyze_ema(candles, period))
            elif indicator == 'rsi':
                entry.update(_analyze_rsi(candles, period))
            elif indicator == 'atr':
                entry.update(_analyze_atr(candles, period))

            results.append(entry)
        except Exception as e:
            results.append({
                'timeframe': tf,
                'error': str(e),
            })

    return {
        'exchange': exchange,
        'symbol': symbol,
        'start_date': start_date,
        'finish_date': finish_date,
        'duration_days': round(duration_days, 1),
        'price_high': round(price_high, 2),
        'price_low': round(price_low, 2),
        'price_range_pct': round(price_range_pct, 2),
        'indicator': indicator,
        'period': period,
        'timeframes': results,
    }


def _analyze_bb(candles, period, mult):
    bb = ta.bollinger_bands(candles, period=period, devup=mult, devdn=mult, sequential=True)
    # bb shape: (3, N) — middle, upper, lower
    upper_series = bb[1]
    lower_series = bb[2]

    # Compute band widths across the period
    widths = (upper_series - lower_series) / lower_series * 100
    # Skip NaN/warmup
    valid = widths[~np.isnan(widths)]
    if len(valid) == 0:
        return {'error': 'no valid BB data'}

    return {
        'avg_band_width_pct': round(float(np.mean(valid)), 2),
        'min_band_width_pct': round(float(np.min(valid)), 2),
        'max_band_width_pct': round(float(np.max(valid)), 2),
        'current_upper': round(float(upper_series[-1]), 2),
        'current_middle': round(float(bb[0][-1]), 2),
        'current_lower': round(float(lower_series[-1]), 2),
        'current_width_pct': round(float(widths[-1]), 2),
    }


def _analyze_ema(candles, period):
    ema = ta.ema(candles, period=period, sequential=True)
    prices = candles[:, 2]  # close prices
    diffs = (prices - ema) / ema * 100
    valid = diffs[~np.isnan(diffs)]
    if len(valid) == 0:
        return {'error': 'no valid EMA data'}

    return {
        'avg_deviation_pct': round(float(np.mean(np.abs(valid))), 3),
        'max_above_pct': round(float(np.max(valid)), 3),
        'max_below_pct': round(float(np.min(valid)), 3),
        'current_ema': round(float(ema[-1]), 2),
    }


def _analyze_rsi(candles, period):
    rsi = ta.rsi(candles, period=period, sequential=True)
    valid = rsi[~np.isnan(rsi)]
    if len(valid) == 0:
        return {'error': 'no valid RSI data'}

    return {
        'avg_rsi': round(float(np.mean(valid)), 1),
        'min_rsi': round(float(np.min(valid)), 1),
        'max_rsi': round(float(np.max(valid)), 1),
        'pct_oversold': round(float(np.sum(valid < 30) / len(valid) * 100), 1),
        'pct_overbought': round(float(np.sum(valid > 70) / len(valid) * 100), 1),
        'current_rsi': round(float(rsi[-1]), 1),
    }


def _analyze_atr(candles, period):
    atr = ta.atr(candles, period=period, sequential=True)
    prices = candles[:, 2]
    atr_pct = atr / prices * 100
    valid = atr_pct[~np.isnan(atr_pct)]
    if len(valid) == 0:
        return {'error': 'no valid ATR data'}

    return {
        'avg_atr_pct': round(float(np.mean(valid)), 3),
        'min_atr_pct': round(float(np.min(valid)), 3),
        'max_atr_pct': round(float(np.max(valid)), 3),
        'current_atr': round(float(atr[-1]), 2),
        'current_atr_pct': round(float(atr_pct[-1]), 3),
    }


def _timeframe_to_minutes(tf: str) -> int:
    mapping = {
        '1m': 1, '3m': 3, '5m': 5, '15m': 15, '30m': 30,
        '1h': 60, '2h': 120, '4h': 240, '6h': 360, '8h': 480,
        '12h': 720, '1D': 1440,
    }
    return mapping.get(tf, 60)
