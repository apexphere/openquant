"""Grid search: trail + activation specifically for long improvement."""
import sys
sys.path.insert(0, '.')
from datetime import datetime, timezone
from openquant.research import backtest, get_candles

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

config_base = {
    'starting_balance': 10_000, 'fee': 0.001, 'type': 'futures',
    'futures_leverage': 1, 'futures_leverage_mode': 'cross',
    'exchange': EXCHANGE, 'warm_up_candles': WARMUP,
}
routes = [{'exchange': EXCHANGE, 'strategy': 'RegimeRouter', 'symbol': SYMBOL, 'timeframe': '15m'}]
data_routes = [{'exchange': EXCHANGE, 'symbol': SYMBOL, 'timeframe': '1D'},
               {'exchange': EXCHANGE, 'symbol': SYMBOL, 'timeframe': '4h'}]

HP_BASE = {
    'bb_window': 15, 'bb_mult': 2.5, 'regime_sma': 42, 'regime_adx_min': 30,
    'regime_confirm': 3, 'momentum_lookback': 42, 'risk_pct': 0.05,
    'sl_pct': 0.05, 'tp_pct': 0.10,
    'rsi_period': 14, 'rsi_oversold': 30, 'rsi_overbought': 70, 'vol_mult': 1.2,
}

configs = [
    # label, trail_pct, trail_activation
    ('t2% a0% (baseline)',   0.02, 0.00),
    ('t3% a0%',              0.03, 0.00),
    ('t4% a0%',              0.04, 0.00),
    ('t5% a0%',              0.05, 0.00),
    ('t2% a1%',              0.02, 0.01),
    ('t3% a1%',              0.03, 0.01),
    ('t4% a1%',              0.04, 0.01),
    ('t2% a1.5%',            0.02, 0.015),
    ('t3% a1.5%',            0.03, 0.015),
    ('t4% a1.5%',            0.04, 0.015),
    ('t2% a2%',              0.02, 0.02),
    ('t3% a2%',              0.03, 0.02),
    ('t4% a2%',              0.04, 0.02),
    ('t3% a3%',              0.03, 0.03),
]

print()
header = "%22s %5s %5s %8s %8s %5s %6s %6s %6s %3s %3s" % (
    'config', 'trd', 'WR%', 'PnL%', 'Sharpe', 'DD%', 'LongWR', 'ShrtWR', 'AvgWL', 'L', 'S')
print(header)
print('-' * 100)

results = []
for label, trail, activ in configs:
    hp = dict(HP_BASE)
    hp['trail_pct'] = trail
    hp['trail_activation'] = activ

    result = backtest(config_base, routes, data_routes, cd, warmup_candles=wd,
                     fast_mode=True, hyperparameters=hp)
    m = result['metrics']

    total = m.get('total', 0)
    wr = m.get('win_rate', 0) * 100 if isinstance(m.get('win_rate'), float) else 0
    pnl = m.get('net_profit_percentage', 0) * 100 if isinstance(m.get('net_profit_percentage'), float) else 0
    sharpe = m.get('sharpe_ratio', 0) if isinstance(m.get('sharpe_ratio'), float) else 0
    dd = m.get('max_drawdown', 0) * 100 if isinstance(m.get('max_drawdown'), float) else 0
    lwr = m.get('win_rate_longs', 0) * 100 if isinstance(m.get('win_rate_longs'), float) else 0
    swr = m.get('win_rate_shorts', 0) * 100 if isinstance(m.get('win_rate_shorts'), float) else 0
    awl = m.get('ratio_avg_win_loss', 0) if isinstance(m.get('ratio_avg_win_loss'), float) else 0
    lc = m.get('longs_count', 0)
    sc = m.get('shorts_count', 0)

    print("%22s %5d %4.1f%% %7.1f%% %8.2f %4.1f%% %5.1f%% %5.1f%% %5.2f %3d %3d" % (
        label, total, wr, pnl, sharpe, dd, lwr, swr, awl, lc, sc))
    results.append({'label': label, 'pnl': pnl, 'sharpe': sharpe, 'total': total,
                    'wr': wr, 'lwr': lwr, 'swr': swr, 'dd': dd})

print('\n=== Top 5 by Sharpe ===')
for r in sorted(results, key=lambda x: x['sharpe'], reverse=True)[:5]:
    print("  %s → Sharpe=%.2f PnL=%.1f%% WR=%.1f%% LongWR=%.1f%% DD=%.1f%%" % (
        r['label'], r['sharpe'], r['pnl'], r['wr'], r['lwr'], r['dd']))
