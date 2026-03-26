"""Debug D1 regime classification over time."""
import sys
sys.path.insert(0, '.')
from datetime import datetime, timezone
from openquant.research import get_candles
import openquant.indicators as ta
import numpy as np

EXCHANGE = 'Bybit USDT Perpetual'
SYMBOL = 'BTC-USDT'

start_ts = int(datetime(2025, 12, 1, tzinfo=timezone.utc).timestamp() * 1000)
finish_ts = int(datetime(2026, 3, 26, tzinfo=timezone.utc).timestamp() * 1000)
_, candles = get_candles(EXCHANGE, SYMBOL, '1D', start_ts, finish_ts, warmup_candles_num=0)

print(f'{len(candles)} D1 candles\n')

sma_period = 42
adx_period = 14
adx_min = 20

header = "%12s %8s %8s %7s %6s %15s" % ('date', 'close', 'SMA42', 'diff%', 'ADX', 'regime')
print(header)
print('-' * 65)

regime_changes = []
prev_regime = None

for i in range(max(sma_period, adx_period+1), len(candles)):
    subset = candles[:i+1]
    sma = ta.sma(subset, period=sma_period)
    adx = ta.adx(subset, period=adx_period)
    close = subset[-1, 2]
    ts = subset[-1, 0]
    dt = datetime.fromtimestamp(ts/1000, tz=timezone.utc)
    diff_pct = (close - sma) / sma * 100
    
    trending = adx >= adx_min
    if trending and close > sma:
        regime = 'trending-up'
    elif trending and close < sma:
        regime = 'trending-down'
    elif close >= sma:
        regime = 'ranging-up'
    else:
        regime = 'ranging-down'
    
    if regime != prev_regime:
        regime_changes.append((dt, regime, prev_regime))
        prev_regime = regime
    
    if dt >= datetime(2026, 2, 1, tzinfo=timezone.utc):
        marker = ' <<<' if len(regime_changes) > 0 and regime_changes[-1][0] == dt else ''
        print("%12s %8.0f %8.0f %6.1f%% %5.1f %15s%s" % (
            dt.strftime('%m-%d'), close, sma, diff_pct, adx, regime, marker))

print('\n=== REGIME CHANGES ===')
for dt, new, old in regime_changes:
    if dt >= datetime(2026, 2, 1, tzinfo=timezone.utc):
        print(f"  {dt.strftime('%m-%d')}: {old} → {new}")

print(f'\nTotal regime changes (Feb-Mar): {sum(1 for d,_,_ in regime_changes if d >= datetime(2026,2,1,tzinfo=timezone.utc))}')
