"""Deep analysis of long trades — why WR 17%?"""
import sys
sys.path.insert(0, '.')
from datetime import datetime, timezone
from openquant.research import backtest, get_candles
import numpy as np

EXCHANGE = 'Bybit USDT Perpetual'
SYMBOL = 'BTC-USDT'
start_ts = int(datetime(2025, 9, 1, tzinfo=timezone.utc).timestamp() * 1000)
finish_ts = int(datetime(2026, 3, 26, tzinfo=timezone.utc).timestamp() * 1000)
WARMUP = 150 * 1440

print('Fetching...')
warmup, candles = get_candles(EXCHANGE, SYMBOL, '1m', start_ts, finish_ts, warmup_candles_num=WARMUP)
key = f'{EXCHANGE}-{SYMBOL}'
cd = {key: {'exchange': EXCHANGE, 'symbol': SYMBOL, 'candles': candles}}
wd = {key: {'exchange': EXCHANGE, 'symbol': SYMBOL, 'candles': warmup}}

config = {
    'starting_balance': 10_000, 'fee': 0.001, 'type': 'futures',
    'futures_leverage': 1, 'futures_leverage_mode': 'cross',
    'exchange': EXCHANGE, 'warm_up_candles': WARMUP,
}
routes = [{'exchange': EXCHANGE, 'strategy': 'RegimeRouter', 'symbol': SYMBOL, 'timeframe': '15m'}]
data_routes = [{'exchange': EXCHANGE, 'symbol': SYMBOL, 'timeframe': '1D'},
               {'exchange': EXCHANGE, 'symbol': SYMBOL, 'timeframe': '4h'}]

print('Backtesting...')
result = backtest(config, routes, data_routes, cd, warmup_candles=wd, fast_mode=True)
trades = result.get('trades', [])
longs = [t for t in trades if t['type'] == 'long']

print(f'\n=== {len(longs)} LONG TRADES ===')
print("%3s %12s %8s %8s %7s %5s %6s %6s %10s" % (
    '#', 'date', 'entry', 'exit', 'PnL%', 'hrs', 'MFE%', 'MAE%', 'regime_ctx'))
print('-' * 75)

mfes = []
maes = []
for i, t in enumerate(longs):
    ep = t['entry_price']
    xp = t['exit_price']
    pnl_pct = t['PNL_percentage']
    opened = datetime.fromtimestamp(t['opened_at']/1000, tz=timezone.utc)
    hrs = (t['closed_at'] - t['opened_at']) / 3600000

    mask = (candles[:, 0] >= t['opened_at']) & (candles[:, 0] <= t['closed_at'])
    tc = candles[mask]
    if len(tc) > 0:
        mfe = (tc[:, 3].max() - ep) / ep * 100
        mae = (tc[:, 4].min() - ep) / ep * 100
    else:
        mfe = mae = 0
    mfes.append(mfe)
    maes.append(mae)

    # What regime is this? trending-up (momentum) or ranging (BB-MR)?
    # If entry is via momentum selection → trending-up context
    # If entry is via BB lower band → ranging context
    # Approximate: check if price was near BB lower band
    
    print("%3d %12s %8.0f %8.0f %6.2f%% %5.1f %5.2f%% %5.2f%%" % (
        i+1, opened.strftime('%m-%d %H:%M'), ep, xp, pnl_pct, hrs, mfe, mae))

wins = [t for t in longs if t['PNL'] > 0]
losses = [t for t in longs if t['PNL'] <= 0]

print(f'\n=== LONG SUMMARY ===')
print(f'WR: {len(wins)}/{len(longs)} ({len(wins)/len(longs)*100:.0f}%)')
print(f'Avg PnL: {np.mean([t["PNL_percentage"] for t in longs])*100:.2f}%')

# MFE buckets
print(f'\n=== MFE DISTRIBUTION (entry quality) ===')
for threshold in [0.3, 0.5, 1.0, 2.0, 3.0]:
    count = sum(1 for m in mfes if m < threshold)
    print(f'  MFE < {threshold}%: {count}/{len(mfes)} ({count/len(mfes)*100:.0f}%)')

# MAE buckets
print(f'\n=== MAE DISTRIBUTION (adverse move) ===')
for threshold in [-0.5, -1.0, -2.0, -3.0, -5.0]:
    count = sum(1 for m in maes if m < threshold)
    print(f'  MAE < {threshold}%: {count}/{len(maes)} ({count/len(maes)*100:.0f}%)')

# Lost trades with good MFE (exit problem)
print(f'\n=== EXIT QUALITY ===')
for threshold in [0.5, 1.0, 2.0]:
    missed = sum(1 for j, t in enumerate(longs) if t['PNL'] <= 0 and mfes[j] > threshold)
    print(f'  Lost with MFE > {threshold}%: {missed}/{len(losses)} ({missed/len(losses)*100:.0f}%) → EXIT problem')

# Holding period analysis
print(f'\n=== HOLDING PERIOD ===')
win_hrs = [(t['closed_at'] - t['opened_at'])/3600000 for t in wins]
loss_hrs = [(t['closed_at'] - t['opened_at'])/3600000 for t in losses]
print(f'  Avg win hold: {np.mean(win_hrs):.1f}h' if win_hrs else '  No wins')
print(f'  Avg loss hold: {np.mean(loss_hrs):.1f}h')
print(f'  Losses < 1h: {sum(1 for h in loss_hrs if h < 1)}/{len(loss_hrs)}')
print(f'  Losses < 2h: {sum(1 for h in loss_hrs if h < 2)}/{len(loss_hrs)}')
