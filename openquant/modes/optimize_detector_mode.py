"""Detector parameter optimization.

Optimizes regime detector params independently from trading behavior.
Uses a composite score of 4 metrics:

1. Capture ratio (25%): What fraction of up/down moves did the detector
   correctly classify as trending-up/trending-down?
2. Stability (20%): Penalizes whipsawing — short-lived regime flips.
3. Regime-conditional Sharpe (25%): Do the regime labels actually separate
   return distributions? trending-up should have positive Sharpe, etc.
4. Economic value (30%): Sharpe ratio of a simple regime-following strategy
   (long in trending-up, short in trending-down, flat in ranging).

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
    'momentum_v4': 'openquant.regime.momentum_detector.MomentumDetector',
    'supertrend_v5': 'openquant.regime.supertrend_detector.SuperTrendDetector',
    'structure_v6': 'openquant.regime.structure_detector.StructureDetector',
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


def _walk_detector(detector, candles: np.ndarray):
    """Walk a detector bar-by-bar and return per-bar regime labels.

    Returns array of regime strings aligned with candles (warmup bars = None).
    """
    detector.reset()
    labels = [None] * len(candles)

    for i in range(1, len(candles)):
        window = candles[:i + 1]
        try:
            labels[i] = detector.detect(window)
        except (ValueError, IndexError):
            continue

    return labels


_BULLISH_LABELS = frozenset({'trending-up', 'ranging-up'})
_BEARISH_LABELS = frozenset({'trending-down', 'ranging-down'})


def _capture_ratio(candles: np.ndarray, labels: list) -> float:
    """What fraction of up/down moves did the detector capture?

    Any bullish label (trending-up or ranging-up) counts as capturing upside.
    Any bearish label (trending-down or ranging-down) counts as capturing downside.
    Returns average of upside and downside capture in [0, 1].
    """
    up_moves = 0.0
    captured_up = 0.0
    down_moves = 0.0
    captured_down = 0.0

    for i in range(1, len(candles)):
        if labels[i] is None:
            continue
        ret = candles[i, 2] - candles[i - 1, 2]
        if ret > 0:
            up_moves += ret
            if labels[i] in _BULLISH_LABELS:
                captured_up += ret
        elif ret < 0:
            down_moves += abs(ret)
            if labels[i] in _BEARISH_LABELS:
                captured_down += abs(ret)

    up_cap = captured_up / up_moves if up_moves > 0 else 0
    down_cap = captured_down / down_moves if down_moves > 0 else 0
    return (up_cap + down_cap) / 2


def _stability_score(labels: list, min_duration: int = 3) -> float:
    """Penalize whipsawing — short-lived regime flips.

    Returns score in [0, 1]. Higher = more stable.
    """
    durations = []
    current = None
    duration = 0

    for lbl in labels:
        if lbl is None:
            continue
        if lbl == current:
            duration += 1
        else:
            if current is not None:
                durations.append(duration)
            current = lbl
            duration = 1
    if current is not None:
        durations.append(duration)

    if not durations:
        return 0.0

    mean_dur = np.mean(durations)
    short_frac = sum(1 for d in durations if d < min_duration) / len(durations)

    # Normalize: 1 bar mean = 0, 20+ bar mean = 1
    dur_score = min(mean_dur / 20.0, 1.0)
    return dur_score * (1.0 - short_frac)


def _regime_conditional_sharpe(candles: np.ndarray, labels: list) -> float:
    """Do detected regimes separate return distributions?

    trending-up should have positive Sharpe, trending-down negative mean,
    ranging should have low variance relative to trending.
    Returns score (higher = better separation).
    """
    returns = np.diff(candles[:, 2]) / (candles[:-1, 2] + 1e-10)
    aligned_labels = labels[1:]

    regime_returns = {}
    for i in range(len(returns)):
        lbl = aligned_labels[i]
        if lbl is None:
            continue
        regime_returns.setdefault(lbl, []).append(returns[i])

    score = 0.0
    total_bars = sum(len(v) for v in regime_returns.values())
    if total_bars == 0:
        return 0.0

    trending_stds = []

    for regime, rets in regime_returns.items():
        if len(rets) < 5:
            continue
        r = np.array(rets)
        mean_r = np.mean(r)
        std_r = np.std(r) + 1e-10
        sharpe = mean_r / std_r
        count = len(r)

        if regime == 'trending-up':
            score += max(sharpe, 0) * count
            trending_stds.append(std_r)
        elif regime == 'trending-down':
            score += max(-sharpe, 0) * count
            trending_stds.append(std_r)

    # Ranging: reward low variance relative to trending
    avg_trending_std = np.mean(trending_stds) if trending_stds else 1.0
    for regime in ('ranging-up', 'ranging-down'):
        if regime in regime_returns and len(regime_returns[regime]) >= 5:
            r = np.array(regime_returns[regime])
            ratio = np.std(r) / avg_trending_std
            score += max(1.0 - ratio, 0) * len(r)

    return score / total_bars


def _economic_value(candles: np.ndarray, labels: list) -> float:
    """Sharpe of a simple regime-following strategy.

    Long in trending-up, short in trending-down, flat in ranging.
    Penalized by max drawdown.
    """
    returns = np.diff(candles[:, 2]) / (candles[:-1, 2] + 1e-10)
    aligned_labels = labels[1:]

    strat_returns = np.zeros_like(returns)
    for i in range(len(returns)):
        lbl = aligned_labels[i]
        if lbl in _BULLISH_LABELS:
            strat_returns[i] = returns[i]
        elif lbl in _BEARISH_LABELS:
            strat_returns[i] = -returns[i]

    std = np.std(strat_returns)
    if std < 1e-10:
        return 0.0

    sharpe = np.mean(strat_returns) / std

    # Drawdown penalty
    cumulative = np.cumsum(strat_returns)
    running_max = np.maximum.accumulate(cumulative)
    max_dd = np.max(running_max - cumulative)
    dd_penalty = 1.0 / (1.0 + max_dd * 10)

    return sharpe * dd_penalty


def _labels_to_regime_periods(candles: np.ndarray, labels: list) -> list:
    """Convert per-bar labels into regime period dicts with price stats."""
    periods = []
    current = None
    start_idx = 0

    for i, lbl in enumerate(labels):
        if lbl is None:
            continue
        if current is None:
            current = lbl
            start_idx = i
        elif lbl != current:
            periods.append(_build_period(candles, current, start_idx, i))
            current = lbl
            start_idx = i

    if current is not None:
        periods.append(_build_period(candles, current, start_idx, len(candles) - 1))

    return periods


def _build_period(candles: np.ndarray, regime: str, si: int, ei: int) -> dict:
    segment = candles[si:ei + 1]
    start_price = float(segment[0, 2])
    end_price = float(segment[-1, 2])
    return {
        'regime': regime,
        'start_ts': int(candles[si, 0]),
        'end_ts': int(candles[ei, 0]),
        'days': round((candles[ei, 0] - candles[si, 0]) / (24 * 60 * 60 * 1000)),
        'start_price': round(start_price, 2),
        'end_price': round(end_price, 2),
        'high': round(float(np.max(segment[:, 3])), 2),
        'low': round(float(np.min(segment[:, 4])), 2),
        'pct_change': round((end_price - start_price) / start_price * 100, 2) if start_price > 0 else 0,
    }


def _magnitude_weighted_accuracy(candles: np.ndarray, labels: list) -> float:
    """Score how well labels match reality, weighted by move size.

    Each bar: if label direction matches price direction, score += |return|.
    If wrong, score -= |return|. Bigger moves count more.
    Normalized to [-1, 1]. Positive = better than random.
    """
    total_magnitude = 0.0
    weighted_correct = 0.0

    for i in range(1, len(candles)):
        lbl = labels[i]
        if lbl is None:
            continue
        ret = candles[i, 2] - candles[i - 1, 2]
        magnitude = abs(ret)
        total_magnitude += magnitude

        if magnitude == 0:
            continue

        # Bullish label + price up = correct. Bearish label + price down = correct.
        if lbl in _BULLISH_LABELS and ret > 0:
            weighted_correct += magnitude
        elif lbl in _BEARISH_LABELS and ret < 0:
            weighted_correct += magnitude
        else:
            weighted_correct -= magnitude

    if total_magnitude == 0:
        return 0.0

    return weighted_correct / total_magnitude


def _directional_accuracy(candles: np.ndarray, labels: list) -> float:
    """Penalize trending labels that go the wrong direction.

    For each trending-up bar, did price actually go up?
    For each trending-down bar, did price actually go down?
    Returns accuracy in [0, 1]. 0.5 = random, 1.0 = perfect.
    """
    correct = 0
    total = 0

    for i in range(1, len(candles)):
        lbl = labels[i]
        if lbl is None:
            continue
        ret = candles[i, 2] - candles[i - 1, 2]
        if ret == 0:
            continue
        total += 1
        if lbl in _BULLISH_LABELS and ret > 0:
            correct += 1
        elif lbl in _BEARISH_LABELS and ret < 0:
            correct += 1

    return correct / total if total > 0 else 0.5


def score_detector(detector, candles: np.ndarray) -> tuple[float, list]:
    """Score = does the labeled regime match reality?

    For each regime period, check if the label matched actual price behavior.
    That's it. No proxy metrics, no synthetic strategies.

    Returns (score, regime_periods).
    """
    if len(candles) < 100:
        return -1.0, []

    labels = _walk_detector(detector, candles)

    labeled_count = sum(1 for l in labels if l is not None)
    if labeled_count < 50:
        return -1.0, []

    regime_periods = _labels_to_regime_periods(candles, labels)

    if len(regime_periods) < 2:
        return -1.0, regime_periods

    # Must have both bullish and bearish periods — one-directional detectors
    # are not detecting anything, just reflecting the overall trend.
    has_bullish = any(rp['regime'] in ('trending-up', 'ranging-up') for rp in regime_periods)
    has_bearish = any(rp['regime'] in ('trending-down', 'ranging-down') for rp in regime_periods)
    if not (has_bullish and has_bearish):
        return -1.0, regime_periods

    # Score each regime period: did the label match what price actually did?
    # Weight by the size of the move — getting big moves right matters more.
    total_weight = 0.0
    total_score = 0.0

    for rp in regime_periods:
        pct = rp['pct_change']
        weight = abs(pct)
        if weight < 0.1:
            continue

        is_bullish = rp['regime'] in ('trending-up', 'ranging-up')
        correct = (is_bullish and pct > 0) or (not is_bullish and pct < 0)

        total_weight += weight
        total_score += weight if correct else -weight

    score = total_score / total_weight if total_weight > 0 else 0.0

    return score, regime_periods


def _get_detector_param_ranges(detector_type: str) -> dict:
    """Return optimizable parameter ranges for each detector type."""
    if detector_type == 'breakout_v3':
        # Ranges for 4h candles — wide exploration
        return {
            'breakout_period': {'type': int, 'min': 18, 'max': 360},
            'fast_ema': {'type': int, 'min': 12, 'max': 180},
            'slow_ema': {'type': int, 'min': 60, 'max': 500},
            'separation_pct': {'type': float, 'min': 0.01, 'max': 2.0},
            'macd_fast': {'type': int, 'min': 18, 'max': 150},
            'macd_slow': {'type': int, 'min': 60, 'max': 300},
            'macd_signal': {'type': int, 'min': 12, 'max': 120},
            'confirm_bars': {'type': int, 'min': 1, 'max': 36},
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
    elif detector_type == 'momentum_v4':
        # Ranges scaled for 4h candles (6 bars per day)
        return {
            'fast_ema': {'type': int, 'min': 30, 'max': 126},
            'slow_ema': {'type': int, 'min': 126, 'max': 330},
            'separation_pct': {'type': float, 'min': 0.05, 'max': 0.5},
            'confirm_bars': {'type': int, 'min': 0, 'max': 18},
        }
    elif detector_type == 'supertrend_v5':
        # Ranges for 4h candles
        return {
            'st_period': {'type': int, 'min': 5, 'max': 80},
            'st_factor': {'type': float, 'min': 1.5, 'max': 5.0},
            'adx_period': {'type': int, 'min': 7, 'max': 60},
            'adx_threshold': {'type': float, 'min': 12.0, 'max': 35.0},
            'chop_period': {'type': int, 'min': 7, 'max': 60},
            'chop_ranging': {'type': float, 'min': 45.0, 'max': 70.0},
            'chop_trending': {'type': float, 'min': 30.0, 'max': 55.0},
            'confirm_bars': {'type': int, 'min': 0, 'max': 12},
        }
    else:
        return {}


def run_detector_optimization(
    detector_type: str,
    candles: np.ndarray,
    timeframe_minutes: int = 240,  # 4h — more bars = better param differentiation
    n_trials: int = 200,
    session_id: str = None,
) -> dict:
    """Run Optuna optimization for detector parameters.

    Returns dict with best_params, best_score, and all_trials.
    """
    # Resample to detector timeframe
    daily_candles = _resample_to_timeframe(candles, timeframe_minutes)

    if len(daily_candles) < 200:
        raise ValueError(f'Need at least 200 candles, got {len(daily_candles)}')

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
        score, regime_periods = score_detector(detector, daily_candles)

        # Store regime periods in Optuna trial attrs (persisted in SQLite)
        import json
        trial.set_user_attr('regime_periods', json.dumps(regime_periods))

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
