"""Detailed trade-level analysis: MFE/MAE, exit cause, entry quality."""
import sys
sys.path.insert(0, '.')
from datetime import datetime, timezone
from openquant.research import backtest, get_candles
import numpy as np

EXCHANGE = 'Bybit USDT Perpetual'
SYMBOL = 'BTC-USDT'
start_ts = int(datetime(2026, 3, 1, tzinfo=timezone.utc).timestamp() * 1000)
finish_ts = int(datetime(2026, 3, 26, tzinfo=timezone.utc).timestamp() * 1000)
WARMUP = 89 * 1440

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

header = f"{'#':>3} {'type':>5} {'entry':>9} {'exit':>9} {'PnL%':>7} {'hrs':>5} {'date':>12} {'exit':>10} {'MFE%':>6} {'MAE%':>7}"
print(f'\n{header}')
print('-' * 90)

for i, t in enumerate(trades):
    tp = t['type']
    ep = t['entry_price']
    xp = t['exit_price']
    pnl_pct = t['PNL_percentage']
    opened = datetime.fromtimestamp(t['opened_at']/1000, tz=timezone.utc)
    closed = datetime.fromtimestamp(t['closed_at']/1000, tz=timezone.utc)
    hrs = (t['closed_at'] - t['opened_at']) / 3600000
    
    # MFE/MAE from 1m candles
    mask = (candles[:, 0] >= t['opened_at']) & (candles[:, 0] <= t['closed_at'])
    tc = candles[mask]
    
    if len(tc) > 0:
        if tp == 'long':
            mfe = (tc[:, 3].max() - ep) / ep * 100
            mae = (tc[:, 4].min() - ep) / ep * 100
        else:
            mfe = (ep - tc[:, 4].min()) / ep * 100
            mae = (ep - tc[:, 3].max()) / ep * 100
    else:
        mfe = mae = 0
    
    # Exit cause
    orders = t.get('orders', [])
    exit_cause = '?'
    if len(orders) >= 2:
        last = orders[-1]
        if isinstance(last, dict):
            exit_cause = last.get('role', '?')
    
    print(f"{i+1:>3} {tp:>5} {ep:>9.0f} {xp:>9.0f} {pnl_pct:>6.2f}% {hrs:>5.1f} {opened.strftime('%m-%d %H:%M'):>12} {exit_cause:>10} {mfe:>5.2f}% {mae:>6.2f}%")

# Summary
longs = [t for t in trades if t['type'] == 'long']
shorts = [t for t in trades if t['type'] == 'short']

print(f'\n=== SUMMARY ===')
print(f'Longs: {len(longs)} | Shorts: {len(shorts)}')

for label, subset in [('LONGS', longs), ('SHORTS', shorts)]:
    if not subset:
        continue
    wins = [t for t in subset if t['PNL'] > 0]
    losses = [t for t in subset if t['PNL'] <= 0]
    avg_pnl = np.mean([t['PNL_percentage'] for t in subset])
    avg_hrs = np.mean([(t['closed_at'] - t['opened_at'])/3600000 for t in subset])
    
    # MFE/MAE for subset
    mfes = []
    maes = []
    for t in subset:
        mask = (candles[:, 0] >= t['opened_at']) & (candles[:, 0] <= t['closed_at'])
        tc = candles[mask]
        if len(tc) > 0:
            ep = t['entry_price']
            if t['type'] == 'long':
                mfes.append((tc[:, 3].max() - ep) / ep * 100)
                maes.append((tc[:, 4].min() - ep) / ep * 100)
            else:
                mfes.append((ep - tc[:, 4].min()) / ep * 100)
                maes.append((ep - tc[:, 3].max()) / ep * 100)
    
    print(f'  {label}:')
    print(f'    WR: {len(wins)}/{len(subset)} ({len(wins)/len(subset)*100:.0f}%)')
    print(f'    Avg PnL: {avg_pnl:.2f}% | Avg hold: {avg_hrs:.1f}h')
    print(f'    Avg MFE: {np.mean(mfes):.2f}% | Avg MAE: {np.mean(maes):.2f}%')
    print(f'    Max MFE: {max(mfes):.2f}% | Max MAE: {min(maes):.2f}%')
    
    # How many had MFE > 1% but still lost?
    missed = sum(1 for j, t in enumerate(subset) if t['PNL'] <= 0 and mfes[j] > 1.0)
    print(f'    Lost with MFE>1%: {missed}/{len(losses)} (EXIT problem)')
    no_bounce = sum(1 for m in mfes if m < 0.3)
    print(f'    MFE<0.3% (no bounce): {no_bounce}/{len(subset)} (ENTRY problem)')
