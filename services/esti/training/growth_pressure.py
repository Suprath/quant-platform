"""
Growth Pressure Controller — "Push Until Plateau" Logic

Monitors the model's improvement rate across walk-forward cycles.
If growth stalls, it escalates evolutionary pressure (mutation rates, diversity)
to force the population out of local optima.

States:
    GROWTH:   Significant improvement > MIN_IMPROVEMENT
    STALLING: Improvement slowed, minor pressure applied
    PRESSURE: No improvement, escalating mutation & injection
    PLATEAU:  Failed to improve after max pressure (convergence)
"""

import numpy as np
from dataclasses import dataclass
from typing import List, Dict, Optional
from config import (
    setup_logger,
    PRESSURE_LOOKBACK,
    MIN_IMPROVEMENT,
    MAX_PRESSURE_LEVEL,
    BREAKOUT_CYCLES,
    MUTATION_SIGMA,
    CROSSOVER_RATE,
    TOURNAMENT_SIZE
)

logger = setup_logger("esti.training.growth_pressure")


@dataclass
class PressureState:
    level: int              # 0=Normal, 1-3=Pressure
    status: str             # GROWING, STALLING, PRESSURE, PLATEAU
    mutation_sigma: float
    crossover_rate: float
    tournament_size: int
    injection_rate: float   # New random agents to inject
    message: str


class GrowthPressure:
    def __init__(self):
        self.history: List[float] = []  # History of best backtest Sharpes
        self.pressure_level = 0
        self.stagnant_cycles = 0
        self.best_sharpe = -999.0
        self.plateau_declared = False

    def update(self, backtest_sharpe: float) -> PressureState:
        """
        Update growth state based on latest backtest result.
        Returns the new evolutionary parameters to use.
        """
        self.history.append(backtest_sharpe)
        
        # Improvement calculation
        improvement = 0.0
        if backtest_sharpe > self.best_sharpe:
            if self.best_sharpe > -900: # Avoid initial jump
                improvement = (backtest_sharpe - self.best_sharpe) / abs(self.best_sharpe + 1e-6)
            self.best_sharpe = backtest_sharpe
            self.stagnant_cycles = 0
            self.pressure_level = 0  # Reset pressure on new high
            self.plateau_declared = False
            status = "GROWING"
            msg = f"🚀 New best Sharpe: {backtest_sharpe:.4f}"
        else:
            self.stagnant_cycles += 1
            if self.stagnant_cycles >= PRESSURE_LOOKBACK:
                self.pressure_level = min(self.pressure_level + 1, MAX_PRESSURE_LEVEL)
                status = "PRESSURE"
                msg = f"🔥 Stagnation detected ({self.stagnant_cycles} cycles). Escalating pressure to Level {self.pressure_level}"
            else:
                status = "STALLING"
                msg = f"⚠️  Stalling... ({self.stagnant_cycles}/{PRESSURE_LOOKBACK})"

        # Plateau detection
        if self.stagnant_cycles > (PRESSURE_LOOKBACK + BREAKOUT_CYCLES):
            status = "PLATEAU"
            msg = "🛑 Model has plateaued. Maximum capability reached for this data regime."
            self.plateau_declared = True

        # Calculate dynamic parameters based on pressure level
        return self._get_params(status)

    def _get_params(self, status: str) -> PressureState:
        """Derive evolutionary parameters from current pressure level."""
        
        # Base config
        sigma = MUTATION_SIGMA
        cr = CROSSOVER_RATE
        ts = TOURNAMENT_SIZE
        inject = 0.0

        if self.pressure_level == 1:
            sigma *= 1.5
            inject = 0.05  # Inject 5% random agents
        elif self.pressure_level == 2:
            sigma *= 2.0
            cr *= 0.8      # Less crossover, more mutation
            inject = 0.10
        elif self.pressure_level == 3:
            sigma *= 3.0
            cr = 0.1
            ts = 10        # Selection pressure UP (only best survive high mutation)
            inject = 0.20

        return PressureState(
            level=self.pressure_level,
            status=status,
            mutation_sigma=round(sigma, 3),
            crossover_rate=round(cr, 2),
            tournament_size=ts,
            injection_rate=inject,
            message=f"[{status}] Lvl {self.pressure_level}"
        )

    def reset(self):
        """Reset internal state (e.g. for new symbol set)."""
        self.history = []
        self.pressure_level = 0
        self.stagnant_cycles = 0
        self.best_sharpe = -999.0
        self.plateau_declared = False
