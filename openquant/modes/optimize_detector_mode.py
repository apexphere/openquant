"""Detector parameter optimization.

Optimizes regime detector params independently from trading behavior.
Scores based on regime classification accuracy: do the detected regimes
match actual price movements?

Scoring logic:
    For each regime period, measure the actual price change:
    - trending-up period:   reward if price went up, penalize if down
    - trending-down period: reward if price went down, penalize if up
    - ranging periods:      reward if price stayed flat (low % change)

    Final score = mean(period_scores) weighted by period duration.
    Range: -1.0 (perfectly wrong) to +1.0 (perfectly right).

Usage:
    python -m openquant.modes.optimize_detector_mode \\
        --detector breakout_v3 --start 2025-06-01 --finish 2026-03-25
"""
import numpy as np
import optuna
from importlib import import_module
from openquant.services import candle_service
from openquant.store import store
from openquant.config import config
from openquant.routes import router
import openquant.helpers as jh
from openquant.services.redis import sync_publish
from openquant.services import logger


# Map detector short names to classes (same as composite.py registry)
_DETECTOR_REGISTRY = {
    'adx': 'openquant.regime.adx_detector.ADXRegimeDetector',
    'ema_adx': 'openquant.regime.ema_adx_detector.EmaAdxDetector',
    'breakout_v3': 'openquant.regime.breakout_detector.BreakoutDetector',
    'volatility': 'openquant.regime.volatility_detector.VolatilityRegimeDetector',
    'trend_strength': 'openquant.regime.trend_strength_detector.TrendStrengthDetector',
}


def _resolve_detector_class(name: str):
    path = _DETECTOR_REGISTRY.get(name, name)
    module_path, class_name = path.rsplit('.', 1)
    module = import_module(module_path)
    return getattr(module, class_name)


def _resample_to_timeframe(candles_1m: np.ndarray, timeframe_minutes: int) -> np.ndarray:
    """Resample 1-minute candles to a higher timeframe."""
    n = len(candles_1m)
    n_bars = n // timeframe_minutes
    if n_bars == 0:
        return candles_1m

    trimmed = candles_1m[:n_bars * timeframe_minutes]
    reshaped = trimmed.reshape(n_bars, timeframe_minutes, -1)

    result = np.empty((n_bars, 6))
    result[:, 0] = reshaped[:, 0, 0]                    # timestamp (first)
    result[:, 1] = reshaped[:, 0, 1]                    # open (first)
    result[:, 2] = reshaped[:, -1, 2]                   # close (last)
    result[:, 3] = np.max(reshaped[:, :, 3], axis=1)    # high (max)
    result[:, 4] = np.min(reshaped[:, :, 4], axis=1)    # low (min)
    result[:, 5] = np.sum(reshaped[:, :, 5], axis=1)    # volume (sum)
    return result


def score_detector(detector, candles: np.ndarray) -> float:
    """Score a detector's regime classifications against actual price movements.

    Walks through candles bar by bar, building regime periods.
    Then scores each period based on whether price moved in the
    direction the regime predicted.

    Returns a score from -1.0 (perfectly wrong) to +1.0 (perfectly right).
    """
    if len(candles) < 100:
        return -1.0

    # Walk through candles, feeding them to the detector one at a time
    # (simulating how the strategy would call it bar by bar)
    detector.reset()
    periods = []
    current_regime = None
    period_start_idx = 0

    warmup = max(70, len(candles) // 5)  # Skip initial warmup

    for i in range(warmup, len(candles)):
        window = candles[:i + 1]
        try:
            regime = detector.detect(window)
        except (ValueError, IndexError):
            continue

        if current_regime is None:
            current_regime = regime
            period_start_idx = i

        if regime != current_regime:
            periods.append({
                'regime': current_regime,
                'start_idx': period_start_idx,
                'end_idx': i,
            })
            current_regime = regime
            period_start_idx = i

    # Close last period
    if current_regime is not None:
        periods.append({
            'regime': current_regime,
            'start_idx': period_start_idx,
            'end_idx': len(candles) - 1,
        })

    if not periods:
        return -1.0

    # Score each period
    total_score = 0.0
    total_weight = 0.0

    for p in periods:
        start_price = candles[p['start_idx'], 2]  # close
        end_price = candles[p['end_idx'], 2]

        if start_price <= 0:
            continue

        pct_change = (end_price - start_price) / start_price * 100
        duration = p['end_idx'] - p['start_idx']

        if duration < 1:
            continue

        # Score based on regime correctness
        #
        # trending-up:   positive pct_change = good
        # trending-down: negative pct_change = good
        # ranging:       small |pct_change| = good (< 3% is "ranging")
        regime = p['regime']

        if regime == 'trending-up':
            # Reward proportional to how much price went up
            # Cap at 1.0 for large moves
            period_score = min(pct_change / 5.0, 1.0) if pct_change > 0 else max(pct_change / 5.0, -1.0)

        elif regime == 'trending-down':
            # Reward proportional to how much price went down (inverted)
            period_score = min(-pct_change / 5.0, 1.0) if pct_change < 0 else max(-pct_change / 5.0, -1.0)

        elif regime in ('ranging-up', 'ranging-down'):
            # Reward small price changes, penalize big ones
            abs_change = abs(pct_change)
            if abs_change < 2.0:
                period_score = 1.0 - (abs_change / 2.0)  # 0% = 1.0, 2% = 0.0
            else:
                period_score = -min(abs_change / 10.0, 1.0)  # Penalize big moves in ranging
        else:
            period_score = 0.0

        # Weight by duration (longer periods matter more)
        weight = np.sqrt(duration)  # sqrt to avoid huge periods dominating
        total_score += period_score * weight
        total_weight += weight

    if total_weight == 0:
        return -1.0

    return total_score / total_weight


def _get_detector_param_ranges(detector_type: str) -> dict:
    """Return optimizable parameter ranges for each detector type."""
    if detector_type == 'breakout_v3':
        return {
            'breakout_period': {'type': int, 'min': 10, 'max': 40},
            'fast_ema': {'type': int, 'min': 5, 'max': 21},
            'slow_ema': {'type': int, 'min': 21, 'max': 55},
            'separation_pct': {'type': float, 'min': 0.1, 'max': 1.0},
            'macd_fast': {'type': int, 'min': 8, 'max': 16},
            'macd_slow': {'type': int, 'min': 20, 'max': 34},
            'macd_signal': {'type': int, 'min': 5, 'max': 14},
            'confirm_bars': {'type': int, 'min': 1, 'max': 4},
        }
    elif detector_type == 'ema_adx':
        return {
            'fast_period': {'type': int, 'min': 5, 'max': 21},
            'slow_period': {'type': int, 'min': 21, 'max': 55},
            'separation_pct': {'type': float, 'min': 0.1, 'max': 1.0},
            'macd_fast': {'type': int, 'min': 8, 'max': 16},
            'macd_slow': {'type': int, 'min': 20, 'max': 34},
            'macd_signal': {'type': int, 'min': 5, 'max': 14},
            'confirm_bars': {'type': int, 'min': 1, 'max': 4},
        }
    else:
        return {}


def run_detector_optimization(
    detector_type: str,
    candles: np.ndarray,
    timeframe_minutes: int = 1440,  # daily
    n_trials: int = 200,
    session_id: str = None,
) -> dict:
    """Run Optuna optimization for detector parameters.

    Returns dict with best_params, best_score, and all_trials.
    """
    # Resample to detector timeframe
    daily_candles = _resample_to_timeframe(candles, timeframe_minutes)

    if len(daily_candles) < 100:
        raise ValueError(f'Need at least 100 daily candles, got {len(daily_candles)}')

    DetectorClass = _resolve_detector_class(detector_type)
    param_ranges = _get_detector_param_ranges(detector_type)

    if not param_ranges:
        raise ValueError(f'No param ranges defined for detector type: {detector_type}')

    best_trials = []

    def objective(trial):
        # Sample params from Optuna
        params = {}
        for name, spec in param_ranges.items():
            if spec['type'] == int:
                params[name] = trial.suggest_int(name, spec['min'], spec['max'])
            elif spec['type'] == float:
                params[name] = trial.suggest_float(name, spec['min'], spec['max'])

        # Validate: fast < slow for EMA params
        if 'fast_ema' in params and 'slow_ema' in params:
            if params['fast_ema'] >= params['slow_ema']:
                return -1.0
        if 'fast_period' in params and 'slow_period' in params:
            if params['fast_period'] >= params['slow_period']:
                return -1.0
        if 'macd_fast' in params and 'macd_slow' in params:
            if params['macd_fast'] >= params['macd_slow']:
                return -1.0

        # Score on full period
        detector = DetectorClass(**params)
        score = score_detector(detector, daily_candles)

        # Store trial info
        trial_info = {
            'trial': trial.number,
            'params': params,
            'score': round(score, 4),
        }

        # Keep top 20 sorted by score
        best_trials.append(trial_info)
        best_trials.sort(key=lambda t: t['score'], reverse=True)
        if len(best_trials) > 20:
            best_trials.pop()

        return score

    # Run optimization
    study = optuna.create_study(
        direction='maximize',
        storage=f'sqlite:///./storage/temp/optuna/detector_optuna.db',
        study_name=f'{detector_type}_{session_id or jh.generate_unique_id()}',
        load_if_exists=True,
    )

    study.optimize(objective, n_trials=n_trials, show_progress_bar=True)

    return {
        'best_params': study.best_params,
        'best_score': study.best_value,
        'best_trials': best_trials,
        'n_trials': n_trials,
        'total_bars': len(daily_candles),
    }
