"""Grid search: regime params (SMA length, ADX threshold, confirm days)."""
import sys
sys.path.insert(0, '.')
from datetime import datetime, timezone
from openquant.research import backtest, get_candles

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
    'bb_window': 15, 'bb_mult': 2.5, 'momentum_lookback': 42,
    'risk_pct': 0.05, 'trail_pct': 0.02, 'trail_activation': 0.0,
    'sl_pct': 0.05, 'tp_pct': 0.10,
    'rsi_period': 14, 'rsi_oversold': 30, 'rsi_overbought': 70, 'vol_mult': 1.2,
}

# Grid
configs = []
for sma in [42, 60, 80, 100]:
    for adx in [20, 25, 30]:
        for confirm in [0, 3, 5]:
            configs.append((sma, adx, confirm))

header = "%6s %4s %5s %6s %6s %8s %8s %7s %7s %3s %3s" % (
    'SMA', 'ADX', 'conf', 'trades', 'WR%', 'PnL%', 'Sharpe', 'LongWR', 'ShrtWR', 'L#', 'S#')
print(f'\n{header}')
print('-' * 80)

results = []
for sma, adx, confirm in configs:
    hp = dict(HP_BASE)
    hp['regime_sma'] = sma
    hp['regime_adx_min'] = adx
    hp['regime_confirm'] = confirm

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

    print("%6d %4d %5d %6d %5.1f%% %7.2f%% %8.2f %6.1f%% %6.1f%% %3d %3d" % (
        sma, adx, confirm, total, wr, pnl, sharpe, lwr, swr, lc, sc))
    results.append({'sma': sma, 'adx': adx, 'confirm': confirm,
                    'pnl': pnl, 'sharpe': sharpe, 'total': total, 'wr': wr,
                    'lc': lc, 'sc': sc, 'lwr': lwr, 'swr': swr})

print('\n=== Top 5 by PnL ===')
for r in sorted(results, key=lambda x: x['pnl'], reverse=True)[:5]:
    print("  SMA=%d ADX=%d confirm=%d → PnL=%.2f%% Sharpe=%.2f trades=%d WR=%.1f%% L=%d(%.0f%%) S=%d(%.0f%%)" % (
        r['sma'], r['adx'], r['confirm'], r['pnl'], r['sharpe'], r['total'], r['wr'],
        r['lc'], r['lwr'], r['sc'], r['swr']))

print('\n=== Top 5 by Sharpe ===')
for r in sorted(results, key=lambda x: x['sharpe'], reverse=True)[:5]:
    print("  SMA=%d ADX=%d confirm=%d → Sharpe=%.2f PnL=%.2f%% trades=%d WR=%.1f%%" % (
        r['sma'], r['adx'], r['confirm'], r['sharpe'], r['pnl'], r['total'], r['wr']))
