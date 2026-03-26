"""Import candles from Bybit via ccxt into openquant DB.

Usage: .venv/bin/python scripts/import_ccxt.py
"""
import sys, time
sys.path.insert(0, '.')

import ccxt
import numpy as np
import psycopg2
from datetime import datetime, timezone

EXCHANGE_NAME = 'Bybit USDT Perpetual'
SYMBOL = 'BTC/USDT:USDT'  # ccxt format for USDT perp
DB_SYMBOL = 'BTC-USDT'     # openquant format
START = '2025-09-25'
BATCH_SIZE = 1000  # max candles per request

exchange = ccxt.bybit({'enableRateLimit': True})
conn = psycopg2.connect(host='127.0.0.1', port=5433, dbname='openquant_db', user='openquant', password='password')

start_ts = int(datetime.strptime(START, '%Y-%m-%d').replace(tzinfo=timezone.utc).timestamp() * 1000)
now_ts = int(datetime.now(timezone.utc).timestamp() * 1000)

print(f'Importing {DB_SYMBOL} from {START} to now...')
total = 0
since = start_ts

while since < now_ts:
    try:
        ohlcv = exchange.fetch_ohlcv(SYMBOL, '1m', since=since, limit=BATCH_SIZE)
    except Exception as e:
        print(f'  Error at {datetime.fromtimestamp(since/1000, tz=timezone.utc)}: {e}')
        time.sleep(5)
        continue
    
    if not ohlcv:
        break
    
    cur = conn.cursor()
    for c in ohlcv:
        ts, o, h, l, close, vol = c
        cur.execute("""
            INSERT INTO candle (id, exchange, symbol, timeframe, timestamp, open, close, high, low, volume)
            VALUES (gen_random_uuid(), %s, %s, '1m', %s, %s, %s, %s, %s, %s)
            ON CONFLICT DO NOTHING
        """, (EXCHANGE_NAME, DB_SYMBOL, ts, o, close, h, l, vol))
    conn.commit()
    cur.close()
    
    total += len(ohlcv)
    last_ts = ohlcv[-1][0]
    since = last_ts + 60000
    
    if total % 10000 == 0:
        dt = datetime.fromtimestamp(last_ts/1000, tz=timezone.utc)
        print(f'  {total} candles imported, up to {dt.strftime("%Y-%m-%d %H:%M")}')

print(f'Done! {total} candles imported.')
conn.close()
