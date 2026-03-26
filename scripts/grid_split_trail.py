"""Grid: split trail params — long-specific trail vs shared short trail."""
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
    'trail_pct': 0.02, 'trail_activation': 0.0,  # short uses these
    'trail_pct_long': 0.0, 'trail_activation_long': 0.0,  # 0 = use shared
    'sl_pct': 0.05, 'tp_pct': 0.10,
    'rsi_period': 14, 'rsi_oversold': 30, 'rsi_overbought': 70, 'vol_mult': 1.2,
}

# Grid: long trail × long activation (short stays at 2%/0%)
configs = [
    # label, trail_pct_long, trail_activation_long
    ('baseline (shared 2%/0%)',  0.0,  0.0),   # fallback to shared
    ('L:3% a0%',                 0.03, 0.0),
    ('L:4% a0%',                 0.04, 0.0),
    ('L:5% a0%',                 0.05, 0.0),
    ('L:3% a1%',                 0.03, 0.01),
    ('L:4% a1%',                 0.04, 0.01),
    ('L:5% a1%',                 0.05, 0.01),
    ('L:3% a1.5%',               0.03, 0.015),
    ('L:4% a1.5%',               0.04, 0.015),
    ('L:5% a1.5%',               0.05, 0.015),
    ('L:3% a2%',                 0.03, 0.02),
    ('L:4% a2%',                 0.04, 0.02),
    ('L:5% a2%',                 0.05, 0.02),
    ('L:4% a3%',                 0.04, 0.03),
    ('L:5% a3%',                 0.05, 0.03),
]

print()
header = "%25s %5s %5s %8s %8s %6s %6s %6s %5s %3s %3s" % (
    'config', 'trd', 'WR%', 'PnL%', 'Sharpe', 'DD%', 'LgWR', 'ShWR', 'AvWL', 'L', 'S')
print(header)
print('-' * 100)

results = []
for label, tl, al in configs:
    hp = dict(HP_BASE)
    hp['trail_pct_long'] = tl
    hp['trail_activation_long'] = al

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

    print("%25s %5d %4.1f%% %7.1f%% %8.2f %5.1f%% %5.1f%% %5.1f%% %4.2f %3d %3d" % (
        label, total, wr, pnl, sharpe, dd, lwr, swr, awl, lc, sc))
    results.append({'label': label, 'pnl': pnl, 'sharpe': sharpe, 'total': total,
                    'wr': wr, 'lwr': lwr, 'swr': swr, 'dd': dd, 'lc': lc, 'sc': sc})

print('\n=== Top 5 by Sharpe ===')
for r in sorted(results, key=lambda x: x['sharpe'], reverse=True)[:5]:
    print("  %s → Sharpe=%.2f PnL=%.1f%% WR=%.1f%% LongWR=%.1f%% ShortWR=%.1f%% DD=%.1f%% L=%d S=%d" % (
        r['label'], r['sharpe'], r['pnl'], r['wr'], r['lwr'], r['swr'], r['dd'], r['lc'], r['sc']))
