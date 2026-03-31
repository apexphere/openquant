from fastapi import APIRouter, Header, Body
from fastapi.responses import JSONResponse
from typing import Optional
from pydantic import BaseModel
from functools import lru_cache
import os
import re
import json as json_lib
import uuid
from datetime import datetime, timezone

from openquant.services import auth as authenticator
from openquant.services.multiprocessing import process_manager
from openquant import helpers as jh


router = APIRouter(prefix="/detector-optimization", tags=["Detector Optimization"])

OPTUNA_DB = './storage/temp/optuna/detector_optuna.db'
PREVIEW_HISTORY_FILE = './storage/json/detector_preview_history.json'
MAX_PREVIEW_HISTORY = 50

# UUID pattern at the end of study names: {detector_type}_{uuid}
_UUID_PATTERN = re.compile(r'^(.+)_([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})$')


def _parse_detector_type(study_name: str) -> str:
    """Extract detector type from study name like 'breakout_v3_593c81aa-...'."""
    m = _UUID_PATTERN.match(study_name)
    return m.group(1) if m else study_name


class DetectorOptimizationRequestJson(BaseModel):
    detector_type: str
    exchange: str = 'Bybit USDT Perpetual'
    symbol: str = 'BTC-USDT'
    start_date: str
    finish_date: str
    trials: int = 1000


def _run_detector_optimization_task(
    session_id: str,
    detector_type: str,
    exchange: str,
    symbol: str,
    start_date: str,
    finish_date: str,
    trials: int,
):
    """Wrapper to run detector optimization inside the process manager."""
    from openquant.modes.optimize_detector_mode import (
        run_detector_optimization,
    )
    from openquant.services.db import database
    from openquant.models.Candle import Candle
    import numpy as np

    database.open_connection()
    try:
        start_ts = jh.date_to_timestamp(start_date)
        finish_ts = jh.date_to_timestamp(finish_date)

        candles = np.array(list(
            Candle.select(
                Candle.timestamp, Candle.open, Candle.close, Candle.high, Candle.low, Candle.volume
            )
            .where(
                Candle.exchange == exchange,
                Candle.symbol == symbol,
                Candle.timeframe == '1m',
                Candle.timestamp >= start_ts,
                Candle.timestamp <= finish_ts,
            )
            .order_by(Candle.timestamp)
            .tuples()
        ))

        if len(candles) == 0:
            raise ValueError(f'No candle data for {symbol} on {exchange} in {start_date} to {finish_date}')

        run_detector_optimization(
            detector_type=detector_type,
            candles=candles,
            n_trials=trials,
            session_id=session_id,
        )
    finally:
        database.close_connection()


@router.post("")
async def start_detector_optimization(
    request_json: DetectorOptimizationRequestJson,
    authorization: Optional[str] = Header(None),
):
    """Start a detector optimization."""
    if not authenticator.is_valid_token(authorization):
        return authenticator.unauthorized_response()

    from openquant.modes.optimize_detector_mode import _get_detector_param_ranges

    param_ranges = _get_detector_param_ranges(request_json.detector_type)
    if not param_ranges:
        return JSONResponse({
            'error': f'Unknown detector type: {request_json.detector_type}',
            'available': ['breakout_v3', 'ema_adx'],
        }, status_code=400)

    session_id = jh.generate_unique_id()

    process_manager.add_task(
        _run_detector_optimization_task,
        session_id,
        request_json.detector_type,
        request_json.exchange,
        request_json.symbol,
        request_json.start_date,
        request_json.finish_date,
        request_json.trials,
        task_type='detector_optimization',
    )

    return JSONResponse({
        'message': 'Detector optimization started',
        'session_id': session_id,
        'detector_type': request_json.detector_type,
    }, status_code=202)


@router.post("/sessions")
def get_detector_optimization_sessions(
    authorization: Optional[str] = Header(None),
):
    """List all detector optimization studies from the Optuna DB."""
    if not authenticator.is_valid_token(authorization):
        return authenticator.unauthorized_response()

    if not os.path.exists(OPTUNA_DB):
        return JSONResponse({'sessions': []})

    import optuna

    storage = f'sqlite:///{OPTUNA_DB}'
    summaries = optuna.study.get_all_study_summaries(storage=storage)

    sessions = []
    for s in summaries:
        detector_type = _parse_detector_type(s.study_name)

        best_value = s.best_trial.value if s.best_trial else None
        best_params = s.best_trial.params if s.best_trial else {}

        sessions.append({
            'study_name': s.study_name,
            'detector_type': detector_type,
            'n_trials': s.n_trials,
            'best_score': round(best_value, 4) if best_value is not None else None,
            'best_params': {
                k: round(v, 4) if isinstance(v, float) else v
                for k, v in best_params.items()
            },
            'datetime_start': s.datetime_start.isoformat() if s.datetime_start else None,
        })

    # Sort by datetime descending
    sessions.sort(key=lambda x: x['datetime_start'] or '', reverse=True)

    return JSONResponse({'sessions': sessions})


@router.post("/sessions/{study_name}")
def get_detector_optimization_session(
    study_name: str,
    authorization: Optional[str] = Header(None),
):
    """Get detailed results for a specific detector optimization study."""
    if not authenticator.is_valid_token(authorization):
        return authenticator.unauthorized_response()

    if not os.path.exists(OPTUNA_DB):
        return JSONResponse({'error': 'No optimization data found'}, status_code=404)

    import optuna

    storage = f'sqlite:///{OPTUNA_DB}'

    try:
        study = optuna.load_study(study_name=study_name, storage=storage)
    except KeyError:
        return JSONResponse({'error': f'Study {study_name} not found'}, status_code=404)

    detector_type = _parse_detector_type(study_name)

    # Build sorted trials list (top 20 by value)
    trials_sorted = sorted(
        [t for t in study.trials if t.value is not None],
        key=lambda t: t.value,
        reverse=True,
    )[:20]

    trials = []
    for t in trials_sorted:
        trials.append({
            'trial': t.number,
            'params': {
                k: round(v, 4) if isinstance(v, float) else v
                for k, v in t.params.items()
            },
            'score': round(t.value, 4) if t.value is not None else None,
        })

    best_value = study.best_value if study.best_trial else None
    best_params = study.best_params if study.best_trial else {}

    return JSONResponse({
        'session': {
            'study_name': study_name,
            'detector_type': detector_type,
            'n_trials': len(study.trials),
            'best_score': round(best_value, 4) if best_value is not None else None,
            'best_params': {
                k: round(v, 4) if isinstance(v, float) else v
                for k, v in best_params.items()
            },
            'trials': trials,
        },
    })


@router.post("/sessions/{study_name}/remove")
def remove_detector_optimization_session(
    study_name: str,
    authorization: Optional[str] = Header(None),
):
    """Delete a detector optimization study."""
    if not authenticator.is_valid_token(authorization):
        return authenticator.unauthorized_response()

    if not os.path.exists(OPTUNA_DB):
        return JSONResponse({'error': 'No optimization data found'}, status_code=404)

    import optuna

    storage = f'sqlite:///{OPTUNA_DB}'

    try:
        optuna.delete_study(study_name=study_name, storage=storage)
    except KeyError:
        return JSONResponse({'error': f'Study {study_name} not found'}, status_code=404)

    return JSONResponse({'message': f'Study {study_name} removed'})


def _load_preview_history() -> list:
    """Load preview history from JSON file."""
    if not os.path.exists(PREVIEW_HISTORY_FILE):
        return []
    try:
        with open(PREVIEW_HISTORY_FILE, 'r') as f:
            entries = json_lib.load(f)
        return entries if isinstance(entries, list) else []
    except (json_lib.JSONDecodeError, IOError):
        return []


def _save_preview_history(entries: list) -> None:
    """Save preview history to JSON file."""
    os.makedirs(os.path.dirname(PREVIEW_HISTORY_FILE), exist_ok=True)
    with open(PREVIEW_HISTORY_FILE, 'w') as f:
        json_lib.dump(entries, f, indent=2)


def _is_duplicate_entry(a: dict, b: dict) -> bool:
    """Check if two history entries are identical (ignoring id/timestamp)."""
    return (
        a.get('detector_type') == b.get('detector_type')
        and a.get('params') == b.get('params')
        and a.get('symbol') == b.get('symbol')
        and a.get('start_date') == b.get('start_date')
        and a.get('finish_date') == b.get('finish_date')
    )


def _add_preview_history_entry(
    detector_type: str,
    params: dict,
    exchange: str,
    symbol: str,
    start_date: str,
    finish_date: str,
) -> None:
    """Add a preview run to history. Dedupes against the last entry, caps at MAX_PREVIEW_HISTORY."""
    entries = _load_preview_history()

    new_entry = {
        'id': str(uuid.uuid4()),
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'detector_type': detector_type,
        'params': params,
        'exchange': exchange,
        'symbol': symbol,
        'start_date': start_date,
        'finish_date': finish_date,
    }

    # Dedupe: skip if identical to the most recent entry
    if entries and _is_duplicate_entry(entries[0], new_entry):
        return

    entries = [new_entry, *entries][:MAX_PREVIEW_HISTORY]
    _save_preview_history(entries)


class DetectorPreviewRequestJson(BaseModel):
    detector_type: str
    params: dict
    exchange: str = 'Bybit USDT Perpetual'
    symbol: str = 'BTC-USDT'
    start_date: str
    finish_date: str


def _load_daily_candles(exchange: str, symbol: str, start_ts: int, finish_ts: int):
    """Load daily candles by aggregating 1m data in SQL. Much faster than loading all 1m rows."""
    from openquant.services.db import database
    import numpy as np

    warmup_ms = 150 * 24 * 60 * 60 * 1000
    warmup_start_ts = start_ts - warmup_ms

    sql = '''
    SELECT
        (timestamp / 86400000) * 86400000 AS day_ts,
        (array_agg(open ORDER BY timestamp))[1] AS open,
        (array_agg(close ORDER BY timestamp DESC))[1] AS close,
        MAX(high) AS high,
        MIN(low) AS low,
        SUM(volume) AS volume
    FROM candle
    WHERE exchange = %s AND symbol = %s AND timeframe = %s
      AND timestamp >= %s AND timestamp <= %s
    GROUP BY day_ts
    ORDER BY day_ts
    '''
    if database.is_closed():
        database.open_connection()
    cursor = database.db.execute_sql(sql, [exchange, symbol, '1m', warmup_start_ts, finish_ts])
    rows = cursor.fetchall()

    if not rows:
        return None
    return np.array(rows, dtype=np.float64)


# Cache: keyed by (exchange, symbol, start_ts, finish_ts). Avoids reloading
# 500K+ rows from DB when previewing different detector params on the same date range.
_daily_candles_cache: dict = {}


def _get_daily_candles_cached(exchange: str, symbol: str, start_ts: int, finish_ts: int):
    key = (exchange, symbol, start_ts, finish_ts)
    if key not in _daily_candles_cache:
        # Keep cache bounded — evict oldest if >8 entries
        if len(_daily_candles_cache) >= 8:
            oldest_key = next(iter(_daily_candles_cache))
            del _daily_candles_cache[oldest_key]
        _daily_candles_cache[key] = _load_daily_candles(exchange, symbol, start_ts, finish_ts)
    return _daily_candles_cache[key]


@router.post("/preview")
def preview_detector(
    request_json: DetectorPreviewRequestJson,
    authorization: Optional[str] = Header(None),
):
    """Run a detector with given params and return daily candles + regime periods."""
    if not authenticator.is_valid_token(authorization):
        return authenticator.unauthorized_response()

    from openquant.modes.optimize_detector_mode import (
        _resolve_detector_class,
        _walk_detector,
        _labels_to_regime_periods,
    )
    import numpy as np

    start_ts = jh.date_to_timestamp(request_json.start_date)
    finish_ts = jh.date_to_timestamp(request_json.finish_date)

    daily_candles = _get_daily_candles_cached(
        request_json.exchange, request_json.symbol, start_ts, finish_ts
    )

    if daily_candles is None or len(daily_candles) == 0:
        return JSONResponse({'error': 'No candle data found'}, status_code=404)

    if len(daily_candles) < 50:
        return JSONResponse({'error': f'Need 50+ daily candles, got {len(daily_candles)}'}, status_code=400)

    # Find index where visible range starts (at or after start_date)
    visible_start_idx = 0
    for idx in range(len(daily_candles)):
        if daily_candles[idx, 0] >= start_ts:
            visible_start_idx = idx
            break

    # Run detector — uses detect_all() (O(n)) when available
    DetectorClass = _resolve_detector_class(request_json.detector_type)
    detector = DetectorClass(**request_json.params)
    labels = _walk_detector(detector, daily_candles)

    # Convert labels to regime periods
    regime_periods = _labels_to_regime_periods(daily_candles, labels)

    # Only return candles and regimes from the visible range (after start_date)
    visible_start_ms = int(daily_candles[visible_start_idx, 0])

    candles_chart = []
    for row in daily_candles[visible_start_idx:]:
        candles_chart.append({
            'time': int(row[0] / 1000),
            'open': round(float(row[1]), 2),
            'close': round(float(row[2]), 2),
            'high': round(float(row[3]), 2),
            'low': round(float(row[4]), 2),
            'volume': round(float(row[5]), 2),
        })

    # Filter/clip regime periods to visible range (convert ms → seconds for frontend)
    visible_regimes = []
    for rp in regime_periods:
        end_ms = rp['end_ts']
        if end_ms < visible_start_ms:
            continue
        visible_regimes.append({
            'regime': rp['regime'],
            'start': max(rp['start_ts'], visible_start_ms) // 1000,
            'end': end_ms // 1000,
        })

    # Build detailed regime periods (with dates, prices, pct_change) for the table
    visible_regime_details = []
    for rp in regime_periods:
        end_ms = rp['end_ts']
        if end_ms < visible_start_ms:
            continue
        visible_regime_details.append({
            'regime': rp['regime'],
            'start': max(rp['start_ts'], visible_start_ms) // 1000,
            'end': end_ms // 1000,
            'start_ts': rp['start_ts'],
            'end_ts': rp['end_ts'],
            'start_date': jh.timestamp_to_date(rp['start_ts']),
            'end_date': jh.timestamp_to_date(rp['end_ts']),
            'days': rp.get('days', 0),
            'start_price': rp.get('start_price', 0),
            'end_price': rp.get('end_price', 0),
            'high': rp.get('high', 0),
            'low': rp.get('low', 0),
            'pct_change': rp.get('pct_change', 0),
        })

    # Auto-save to preview history on success
    _add_preview_history_entry(
        detector_type=request_json.detector_type,
        params=request_json.params,
        exchange=request_json.exchange,
        symbol=request_json.symbol,
        start_date=request_json.start_date,
        finish_date=request_json.finish_date,
    )

    return JSONResponse({
        'candles': candles_chart,
        'regime_periods': visible_regime_details,
    })


@router.post("/preview/history")
def get_preview_history(
    authorization: Optional[str] = Header(None),
):
    """Return detector preview history (newest first)."""
    if not authenticator.is_valid_token(authorization):
        return authenticator.unauthorized_response()

    return JSONResponse({'history': _load_preview_history()})


@router.post("/preview/history/clear")
def clear_preview_history(
    authorization: Optional[str] = Header(None),
):
    """Clear all preview history."""
    if not authenticator.is_valid_token(authorization):
        return authenticator.unauthorized_response()

    _save_preview_history([])
    return JSONResponse({'message': 'History cleared'})


@router.post("/preview/history/{entry_id}/details")
def get_preview_history_details(
    entry_id: str,
    authorization: Optional[str] = Header(None),
):
    """Re-run a history entry's detector and return full regime periods."""
    if not authenticator.is_valid_token(authorization):
        return authenticator.unauthorized_response()

    from openquant.modes.optimize_detector_mode import (
        _resolve_detector_class,
        _walk_detector,
        _labels_to_regime_periods,
    )

    entries = _load_preview_history()
    entry = next((e for e in entries if e.get('id') == entry_id), None)
    if entry is None:
        return JSONResponse({'error': 'Entry not found'}, status_code=404)

    start_ts = jh.date_to_timestamp(entry['start_date'])
    finish_ts = jh.date_to_timestamp(entry['finish_date'])

    daily_candles = _get_daily_candles_cached(
        entry.get('exchange', 'Bybit USDT Perpetual'), entry['symbol'], start_ts, finish_ts
    )

    if daily_candles is None or len(daily_candles) < 50:
        return JSONResponse({'error': 'Insufficient candle data'}, status_code=400)

    DetectorClass = _resolve_detector_class(entry['detector_type'])
    detector = DetectorClass(**entry['params'])
    labels = _walk_detector(detector, daily_candles)
    regime_periods = _labels_to_regime_periods(daily_candles, labels)

    visible_start_idx = 0
    for idx in range(len(daily_candles)):
        if daily_candles[idx, 0] >= start_ts:
            visible_start_idx = idx
            break
    visible_start_ms = int(daily_candles[visible_start_idx, 0])

    visible_regime_details = []
    for rp in regime_periods:
        if rp['end_ts'] < visible_start_ms:
            continue
        visible_regime_details.append({
            'regime': rp['regime'],
            'start_date': jh.timestamp_to_date(rp['start_ts']),
            'end_date': jh.timestamp_to_date(rp['end_ts']),
            'days': rp.get('days', 0),
            'start_price': rp.get('start_price', 0),
            'end_price': rp.get('end_price', 0),
            'high': rp.get('high', 0),
            'low': rp.get('low', 0),
            'pct_change': rp.get('pct_change', 0),
        })

    return JSONResponse({
        'entry': entry,
        'regime_periods': visible_regime_details,
    })


@router.post("/preview/history/{entry_id}/remove")
def remove_preview_history_entry(
    entry_id: str,
    authorization: Optional[str] = Header(None),
):
    """Delete a single preview history entry."""
    if not authenticator.is_valid_token(authorization):
        return authenticator.unauthorized_response()

    entries = _load_preview_history()
    updated = [e for e in entries if e.get('id') != entry_id]

    if len(updated) == len(entries):
        return JSONResponse({'error': 'Entry not found'}, status_code=404)

    _save_preview_history(updated)
    return JSONResponse({'message': 'Entry removed'})


@router.post("/sessions/{study_name}/trials/{trial_number}/regimes")
def get_trial_regimes(
    study_name: str,
    trial_number: int,
    authorization: Optional[str] = Header(None),
):
    """Get regime details for a specific trial in a study.

    Reads pre-computed regime periods from Optuna user_attrs (stored during
    optimization). Falls back to recomputation for older trials.
    """
    if not authenticator.is_valid_token(authorization):
        return authenticator.unauthorized_response()

    if not os.path.exists(OPTUNA_DB):
        return JSONResponse({'error': 'No optimization data found'}, status_code=404)

    import optuna

    storage = f'sqlite:///{OPTUNA_DB}'

    try:
        study = optuna.load_study(study_name=study_name, storage=storage)
    except KeyError:
        return JSONResponse({'error': f'Study {study_name} not found'}, status_code=404)

    # Find the trial
    trial = None
    for t in study.trials:
        if t.number == trial_number:
            trial = t
            break

    if trial is None:
        return JSONResponse({'error': f'Trial {trial_number} not found'}, status_code=404)

    detector_type = _parse_detector_type(study_name)
    params = trial.params

    # Try reading stored regime periods first
    stored = trial.user_attrs.get('regime_periods') if trial.user_attrs else None

    if stored:
        # Stored as JSON string during optimization
        regime_periods = json_lib.loads(stored)
        # Convert timestamps to dates
        for rp in regime_periods:
            if 'start_ts' in rp and 'start_date' not in rp:
                rp['start_date'] = jh.timestamp_to_date(rp['start_ts'])
                rp['end_date'] = jh.timestamp_to_date(rp['end_ts'])
    else:
        # Fallback: recompute for older trials without stored data
        import numpy as np
        from openquant.modes.optimize_detector_mode import (
            _resolve_detector_class,
            _resample_to_timeframe,
            _walk_detector,
            _labels_to_regime_periods,
        )
        from openquant.models.Candle import Candle

        exchange = 'Bybit USDT Perpetual'
        symbol = 'BTC-USDT'
        start_ts = jh.date_to_timestamp('2025-06-01')
        finish_ts = jh.date_to_timestamp('2026-03-25')

        candles_1m = np.array(list(
            Candle.select(
                Candle.timestamp, Candle.open, Candle.close, Candle.high, Candle.low, Candle.volume
            )
            .where(
                Candle.exchange == exchange,
                Candle.symbol == symbol,
                Candle.timeframe == '1m',
                Candle.timestamp >= start_ts,
                Candle.timestamp <= finish_ts,
            )
            .order_by(Candle.timestamp)
            .tuples()
        ))

        if len(candles_1m) == 0:
            return JSONResponse({'error': 'No candle data found'}, status_code=404)

        daily_candles = _resample_to_timeframe(candles_1m, 1440)
        DetectorClass = _resolve_detector_class(detector_type)
        detector = DetectorClass(**params)
        labels = _walk_detector(detector, daily_candles)
        regime_periods = _labels_to_regime_periods(daily_candles, labels)

    # Ensure dates are present
    for rp in regime_periods:
        if 'start_date' not in rp and 'start_ts' in rp:
            rp['start_date'] = jh.timestamp_to_date(rp['start_ts'])
            rp['end_date'] = jh.timestamp_to_date(rp['end_ts'])

    return JSONResponse({
        'trial': trial_number,
        'score': round(trial.value, 4) if trial.value is not None else None,
        'params': {
            k: round(v, 4) if isinstance(v, float) else v
            for k, v in params.items()
        },
        'detector_type': detector_type,
        'regime_periods': regime_periods,
    })


@router.post("/detector-types")
def get_detector_types(
    authorization: Optional[str] = Header(None),
):
    """Get available detector types and their parameter ranges."""
    if not authenticator.is_valid_token(authorization):
        return authenticator.unauthorized_response()

    from openquant.modes.optimize_detector_mode import _get_detector_param_ranges
    from openquant.regime.composite import _DETECTOR_REGISTRY

    # Base detectors + any versioned ones from the registry
    base_names = ['breakout_v3', 'momentum_v4', 'supertrend_v5', 'ema_adx']
    versioned_names = [k for k in _DETECTOR_REGISTRY if '__' in k]
    all_names = base_names + versioned_names

    types = {}
    for name in all_names:
        ranges = _get_detector_param_ranges(name)
        if ranges:
            types[name] = {
                k: {'type': v['type'].__name__, 'min': v['min'], 'max': v['max']}
                for k, v in ranges.items()
            }

    return JSONResponse({'detector_types': types})
