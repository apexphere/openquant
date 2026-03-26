"""RegimeRouter V2 — composite version using the regime composition framework.

This is the same strategy as RegimeRouter but built using OpenQuant's
regime-aware composition instead of a monolithic strategy file.

Original RegimeRouter: 277 lines of tangled regime detection + momentum
rotation + BB mean reversion + trailing stops in one file.

This version: ~50 lines of configuration wiring three reusable components:
  - ADXRegimeDetector (regime detection)
  - MomentumRotationBehavior (trending-up)
  - BBMeanReversionBehavior (ranging)
"""
from openquant.strategies import Strategy
from openquant.regime import ADXRegimeDetector
from openquant.regime.behaviors import MomentumRotationBehavior, BBMeanReversionBehavior


class RegimeRouterV2(Strategy):

    def __init__(self):
        super().__init__()
        self._detector = None

    def hyperparameters(self):
        return [
            # BB-MR signal
            {'name': 'bb_window', 'type': int, 'min': 10, 'max': 30, 'default': 15},
            {'name': 'bb_mult', 'type': float, 'min': 1.5, 'max': 3.5, 'default': 2.5},
            # Regime classification
            {'name': 'regime_sma', 'type': int, 'min': 20, 'max': 100, 'default': 42},
            {'name': 'regime_adx_min', 'type': float, 'min': 15, 'max': 40, 'default': 30},
            {'name': 'regime_confirm', 'type': int, 'min': 0, 'max': 10, 'default': 3},
            # Momentum rotation
            {'name': 'momentum_lookback', 'type': int, 'min': 10, 'max': 200, 'default': 42},
            # Risk / position sizing
            {'name': 'risk_pct', 'type': float, 'min': 0.01, 'max': 0.2, 'default': 0.05},
            {'name': 'trail_pct', 'type': float, 'min': 0.005, 'max': 0.08, 'default': 0.02},
            {'name': 'sl_pct', 'type': float, 'min': 0.02, 'max': 0.10, 'default': 0.05},
            {'name': 'tp_pct', 'type': float, 'min': 0.05, 'max': 0.30, 'default': 0.10},
            # BB-MR entry confirmation
            {'name': 'rsi_period', 'type': int, 'min': 7, 'max': 21, 'default': 14},
            {'name': 'rsi_oversold', 'type': float, 'min': 20, 'max': 45, 'default': 30},
            {'name': 'rsi_overbought', 'type': float, 'min': 55, 'max': 80, 'default': 70},
            {'name': 'vol_mult', 'type': float, 'min': 0.5, 'max': 3.0, 'default': 1.2},
        ]

    # ── Regime composition ──────────────────────────────────────────

    def regime_detector(self):
        if self.hp is None:
            return None  # not yet initialized by the engine
        if self._detector is None:
            self._detector = ADXRegimeDetector(
                sma_period=self.hp['regime_sma'],
                adx_period=14,
                adx_min=self.hp['regime_adx_min'],
                confirm_bars=self.hp['regime_confirm'],
            )
        return self._detector

    def regimes(self):
        return {
            'trending-up': MomentumRotationBehavior,
            'trending-down': None,   # flat — no trading
            'ranging-up': BBMeanReversionBehavior,
            'ranging-down': BBMeanReversionBehavior,
            'cold-start': None,      # flat — waiting for data
        }

    def on_regime_change(self, old_regime, new_regime):
        # Close positions when switching regimes
        if self.is_long or self.is_short:
            self.liquidate()

    # ── Cooldown tracking ───────────────────────────────────────────

    def on_close_position(self, order, closed_trade=None):
        self.vars['last_exit_index'] = self.index

    # ── Classic strategy methods (used when no behavior is active) ──

    def should_long(self) -> bool:
        return False

    def go_long(self):
        pass

    def should_short(self) -> bool:
        return False

    def go_short(self):
        pass

    def update_position(self):
        pass

    def should_cancel_entry(self):
        return False

    def filters(self):
        return []
