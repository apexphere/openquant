"""Grid search: trail_pct × trail_activation on Mar 2026 ranging period.

Usage: .venv/bin/python scripts/grid_trail.py
"""
import sys, time
sys.path.insert(0, '.')
from datetime import datetime, timezone
from openquant.research import backtest, get_candles

EXCHANGE = 'Bybit USDT Perpetual'
SYMBOL = 'BTC-USDT'

start_ts = int(datetime(2026, 3, 1, tzinfo=timezone.utc).timestamp() * 1000)
finish_ts = int(datetime(2026, 3, 26, tzinfo=timezone.utc).timestamp() * 1000)
WARMUP = 89 * 1440

print('Fetching candles...')
warmup, candles = get_candles(EXCHANGE, SYMBOL, '1m', start_ts, finish_ts, warmup_candles_num=WARMUP)
key = f'{EXCHANGE}-{SYMBOL}'
cd = {key: {'exchange': EXCHANGE, 'symbol': SYMBOL, 'candles': candles}}
wd = {key: {'exchange': EXCHANGE, 'symbol': SYMBOL, 'candles': warmup}}
print(f'{len(candles)} trading, {len(warmup)} warmup\n')

config_base = {
    'starting_balance': 10_000, 'fee': 0.001, 'type': 'futures',
    'futures_leverage': 1, 'futures_leverage_mode': 'cross',
    'exchange': EXCHANGE, 'warm_up_candles': WARMUP,
}
routes = [{'exchange': EXCHANGE, 'strategy': 'RegimeRouter', 'symbol': SYMBOL, 'timeframe': '15m'}]
data_routes = [
    {'exchange': EXCHANGE, 'symbol': SYMBOL, 'timeframe': '1D'},
    {'exchange': EXCHANGE, 'symbol': SYMBOL, 'timeframe': '4h'},
]

# Grid
trail_pcts = [0.02, 0.03, 0.04, 0.05, 0.06]
trail_activations = [0.0, 0.005, 0.01, 0.015, 0.02]

results = []
total_combos = len(trail_pcts) * len(trail_activations)
i = 0

print(f'{"trail%":>7} {"activ%":>7} {"trades":>7} {"WR%":>7} {"PnL%":>8} {"Sharpe":>8} {"MaxDD%":>8} {"LongWR":>7} {"ShortWR":>7}')
print('-' * 80)

for tp in trail_pcts:
    for ta_val in trail_activations:
        i += 1
        hp = {
            'bb_window': 15,
            'bb_mult': 2.5,
            'regime_sma': 42,
            'regime_adx_min': 20,
            'momentum_lookback': 42,
            'risk_pct': 0.05,
            'trail_pct': tp,
            'trail_activation': ta_val,
            'sl_pct': 0.05,
            'tp_pct': 0.10,
        }
        
        result = backtest(config_base, routes, data_routes, cd, warmup_candles=wd,
                         fast_mode=True, hyperparameters=hp)
        m = result['metrics']
        
        total = m.get('total', 0)
        wr = m.get('win_rate', 0) * 100 if isinstance(m.get('win_rate', 0), float) else 0
        pnl = m.get('net_profit_percentage', 0) * 100 if isinstance(m.get('net_profit_percentage', 0), float) else 0
        sharpe = m.get('sharpe_ratio', 0) if isinstance(m.get('sharpe_ratio', 0), float) else 0
        dd = m.get('max_drawdown', 0) * 100 if isinstance(m.get('max_drawdown', 0), float) else 0
        lwr = m.get('win_rate_longs', 0) * 100 if isinstance(m.get('win_rate_longs', 0), float) else 0
        swr = m.get('win_rate_shorts', 0) * 100 if isinstance(m.get('win_rate_shorts', 0), float) else 0
        
        print(f'{tp*100:>6.1f}% {ta_val*100:>6.1f}% {total:>7} {wr:>6.1f}% {pnl:>7.2f}% {sharpe:>8.2f} {dd:>7.2f}% {lwr:>6.1f}% {swr:>6.1f}%')
        
        results.append({
            'trail': tp, 'activation': ta_val, 'total': total,
            'wr': wr, 'pnl': pnl, 'sharpe': sharpe, 'dd': dd,
            'lwr': lwr, 'swr': swr,
        })

# Top 5 by PnL
print('\n═══ Top 5 by PnL% ═══')
top = sorted(results, key=lambda x: x['pnl'], reverse=True)[:5]
for r in top:
    print(f"  trail={r['trail']*100:.1f}% activ={r['activation']*100:.1f}% → PnL={r['pnl']:.2f}% Sharpe={r['sharpe']:.2f} WR={r['wr']:.1f}% trades={r['total']}")
