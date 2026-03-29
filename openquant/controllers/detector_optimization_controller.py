from fastapi import APIRouter, Header, Body
from fastapi.responses import JSONResponse
from typing import Optional
from pydantic import BaseModel
import os
import re

from openquant.services import auth as authenticator
from openquant.services.multiprocessing import process_manager
from openquant import helpers as jh


router = APIRouter(prefix="/detector-optimization", tags=["Detector Optimization"])

OPTUNA_DB = './storage/temp/optuna/detector_optuna.db'

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
    trials: int = 200


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

        candles_raw = (
            Candle.select()
            .where(
                Candle.exchange == exchange,
                Candle.symbol == symbol,
                Candle.timestamp >= start_ts,
                Candle.timestamp <= finish_ts,
            )
            .order_by(Candle.timestamp)
        )

        candles = np.array([
            [c.timestamp, c.open, c.close, c.high, c.low, c.volume]
            for c in candles_raw
        ])

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


class DetectorPreviewRequestJson(BaseModel):
    detector_type: str
    params: dict
    exchange: str = 'Bybit USDT Perpetual'
    symbol: str = 'BTC-USDT'
    start_date: str
    finish_date: str


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
        _resample_to_timeframe,
    )
    from openquant.models.Candle import Candle
    import numpy as np

    start_ts = jh.date_to_timestamp(request_json.start_date)
    finish_ts = jh.date_to_timestamp(request_json.finish_date)

    candles_raw = (
        Candle.select()
        .where(
            Candle.exchange == request_json.exchange,
            Candle.symbol == request_json.symbol,
            Candle.timestamp >= start_ts,
            Candle.timestamp <= finish_ts,
        )
        .order_by(Candle.timestamp)
    )

    candles_1m = np.array([
        [c.timestamp, c.open, c.close, c.high, c.low, c.volume]
        for c in candles_raw
    ])

    if len(candles_1m) == 0:
        return JSONResponse({'error': 'No candle data found'}, status_code=404)

    daily_candles = _resample_to_timeframe(candles_1m, 1440)

    if len(daily_candles) < 100:
        return JSONResponse({'error': f'Need 100+ daily candles, got {len(daily_candles)}'}, status_code=400)

    # Run detector bar by bar
    DetectorClass = _resolve_detector_class(request_json.detector_type)
    detector = DetectorClass(**request_json.params)
    detector.reset()

    regime_periods = []
    current_regime = None
    period_start_idx = 0

    for i in range(1, len(daily_candles)):
        window = daily_candles[:i + 1]
        try:
            regime = detector.detect(window)
        except (ValueError, IndexError):
            continue

        if current_regime is None:
            current_regime = regime
            period_start_idx = i

        if regime != current_regime:
            regime_periods.append({
                'regime': current_regime,
                'start': int(daily_candles[period_start_idx, 0] / 1000),
                'end': int(daily_candles[i, 0] / 1000),
            })
            current_regime = regime
            period_start_idx = i

    # Close last period
    if current_regime is not None:
        regime_periods.append({
            'regime': current_regime,
            'start': int(daily_candles[period_start_idx, 0] / 1000),
            'end': int(daily_candles[-1, 0] / 1000),
        })

    # Build candle data for chart (daily OHLCV, timestamps in seconds)
    candles_chart = []
    for row in daily_candles:
        candles_chart.append({
            'time': int(row[0] / 1000),
            'open': round(float(row[1]), 2),
            'close': round(float(row[2]), 2),
            'high': round(float(row[3]), 2),
            'low': round(float(row[4]), 2),
            'volume': round(float(row[5]), 2),
        })

    return JSONResponse({
        'candles': candles_chart,
        'regime_periods': regime_periods,
    })


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
    import json as json_lib

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

        candles_raw = (
            Candle.select()
            .where(
                Candle.exchange == exchange,
                Candle.symbol == symbol,
                Candle.timestamp >= start_ts,
                Candle.timestamp <= finish_ts,
            )
            .order_by(Candle.timestamp)
        )

        candles_1m = np.array([
            [c.timestamp, c.open, c.close, c.high, c.low, c.volume]
            for c in candles_raw
        ])

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

    types = {}
    for name in ['breakout_v3', 'momentum_v4', 'ema_adx']:
        ranges = _get_detector_param_ranges(name)
        types[name] = {
            k: {'type': v['type'].__name__, 'min': v['min'], 'max': v['max']}
            for k, v in ranges.items()
        }

    return JSONResponse({'detector_types': types})
