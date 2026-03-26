"""Grid search: RSI + volume entry confirmation for BB-MR ranging trades."""
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

config_base = {
    'starting_balance': 10_000, 'fee': 0.001, 'type': 'futures',
    'futures_leverage': 1, 'futures_leverage_mode': 'cross',
    'exchange': EXCHANGE, 'warm_up_candles': WARMUP,
}
routes = [{'exchange': EXCHANGE, 'strategy': 'RegimeRouter', 'symbol': SYMBOL, 'timeframe': '15m'}]
data_routes = [{'exchange': EXCHANGE, 'symbol': SYMBOL, 'timeframe': '1D'},
               {'exchange': EXCHANGE, 'symbol': SYMBOL, 'timeframe': '4h'}]

HP_BASE = {
    'bb_window': 15, 'bb_mult': 2.5, 'regime_sma': 42, 'regime_adx_min': 20,
    'momentum_lookback': 42, 'risk_pct': 0.05, 'trail_pct': 0.02,
    'trail_activation': 0.0, 'sl_pct': 0.05, 'tp_pct': 0.10,
    'rsi_period': 14, 'rsi_oversold': 30, 'rsi_overbought': 70, 'vol_mult': 1.2,
}

# Grid: RSI thresholds × volume multiplier
configs = [
    # label, rsi_oversold, rsi_overbought, vol_mult
    ('no filter (RSI=50/50 vol=0)',  50, 50, 0.0),  # effectively no RSI/vol filter
    ('RSI 35/65 vol=1.0',           35, 65, 1.0),
    ('RSI 30/70 vol=1.0',           30, 70, 1.0),
    ('RSI 30/70 vol=1.2',           30, 70, 1.2),
    ('RSI 30/70 vol=1.5',           30, 70, 1.5),
    ('RSI 25/75 vol=1.0',           25, 75, 1.0),
    ('RSI 25/75 vol=1.2',           25, 75, 1.2),
    ('RSI 25/75 vol=1.5',           25, 75, 1.5),
    ('RSI 20/80 vol=1.0',           20, 80, 1.0),
    ('RSI 20/80 vol=1.2',           20, 80, 1.2),
    ('RSI 35/65 vol=1.2',           35, 65, 1.2),
    ('RSI 35/65 vol=1.5',           35, 65, 1.5),
    ('RSI 40/60 vol=1.0',           40, 60, 1.0),
    ('RSI 40/60 vol=1.2',           40, 60, 1.2),
]

print(f"\n{'config':>25} {'trades':>6} {'WR%':>6} {'PnL%':>8} {'Sharpe':>8} {'LongWR':>7} {'ShortWR':>7} {'L#':>3} {'S#':>3}")
print('-' * 85)

results = []
for label, rsi_os, rsi_ob, vm in configs:
    hp = dict(HP_BASE)
    hp['rsi_oversold'] = rsi_os
    hp['rsi_overbought'] = rsi_ob
    hp['vol_mult'] = vm
    
    result = backtest(config_base, routes, data_routes, cd, warmup_candles=wd,
                     fast_mode=True, hyperparameters=hp)
    m = result['metrics']
    
    total = m.get('total', 0)
    wr = m.get('win_rate', 0) * 100 if isinstance(m.get('win_rate', 0), float) else 0
    pnl = m.get('net_profit_percentage', 0) * 100 if isinstance(m.get('net_profit_percentage', 0), float) else 0
    sharpe = m.get('sharpe_ratio', 0) if isinstance(m.get('sharpe_ratio', 0), float) else 0
    lwr = m.get('win_rate_longs', 0) * 100 if isinstance(m.get('win_rate_longs', 0), float) else 0
    swr = m.get('win_rate_shorts', 0) * 100 if isinstance(m.get('win_rate_shorts', 0), float) else 0
    lc = m.get('longs_count', 0)
    sc = m.get('shorts_count', 0)
    
    print(f'{label:>25} {total:>6} {wr:>5.1f}% {pnl:>7.2f}% {sharpe:>8.2f} {lwr:>6.1f}% {swr:>6.1f}% {lc:>3} {sc:>3}')
    results.append({'label': label, 'pnl': pnl, 'sharpe': sharpe, 'total': total, 'wr': wr})

print('\n=== Top 3 by PnL ===')
for r in sorted(results, key=lambda x: x['pnl'], reverse=True)[:3]:
    print(f"  {r['label']} → PnL={r['pnl']:.2f}% Sharpe={r['sharpe']:.2f} trades={r['total']} WR={r['wr']:.1f}%")
