"""Backtest RegimeRouter on BTC-USDT 15m.

Usage: cd openquant && .venv/bin/python scripts/bt_regime_router.py
"""
import sys
sys.path.insert(0, '.')

from datetime import datetime, timezone
from openquant.research import backtest, get_candles

EXCHANGE = 'Bybit USDT Perpetual'
SYMBOL = 'BTC-USDT'

# Dec 2024 – Mar 2025: continuous data, mix of trending + ranging
# Nov 2024 as warmup (need D1 SMA42 — 30 days warmup is min)
START_DT = datetime(2024, 12, 1, tzinfo=timezone.utc)
FINISH_DT = datetime(2025, 3, 31, tzinfo=timezone.utc)

start_ts = int(START_DT.timestamp() * 1000)
finish_ts = int(FINISH_DT.timestamp() * 1000)

# Warmup: 29 days (Nov 1 → Nov 30)
WARMUP = 29 * 1440

print(f'Fetching 1m candles {SYMBOL} {START_DT.date()} → {FINISH_DT.date()} (warmup={WARMUP}) ...')
candles, warmup_candles = get_candles(EXCHANGE, SYMBOL, '1m', start_ts, finish_ts, warmup_candles_num=WARMUP)

key = f'{EXCHANGE}-{SYMBOL}'
candles_dict = {key: {'exchange': EXCHANGE, 'symbol': SYMBOL, 'candles': candles}}
warmup_dict = {key: {'exchange': EXCHANGE, 'symbol': SYMBOL, 'candles': warmup_candles}}

print(f'Got {len(candles)} trading candles, {len(warmup_candles)} warmup candles')

config = {
    'starting_balance': 10_000,
    'fee': 0.001,
    'type': 'futures',
    'futures_leverage': 1,
    'futures_leverage_mode': 'cross',
    'exchange': EXCHANGE,
    'warm_up_candles': WARMUP,
}

routes = [
    {'exchange': EXCHANGE, 'strategy': 'RegimeRouter', 'symbol': SYMBOL, 'timeframe': '15m'},
]

# D1 for regime, 4h for momentum
data_routes = [
    {'exchange': EXCHANGE, 'symbol': SYMBOL, 'timeframe': '1D'},
    {'exchange': EXCHANGE, 'symbol': SYMBOL, 'timeframe': '4h'},
]

print('Running backtest...')
result = backtest(
    config,
    routes,
    data_routes,
    candles_dict,
    warmup_candles=warmup_dict,
    generate_equity_curve=True,
    generate_logs=True,
)

metrics = result['metrics']
print('\n═══ RegimeRouter Backtest Results ═══')
print(f'  Period: {START_DT.date()} → {FINISH_DT.date()}')
for k, v in metrics.items():
    if isinstance(v, float):
        print(f'  {k:30s}: {v:.4f}')
    else:
        print(f'  {k:30s}: {v}')
