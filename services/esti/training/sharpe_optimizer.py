"""
SharpeOptimizer — Risk-Adjusted Return Fitness Metric

Uses the Sharpe Ratio as the primary fitness metric for evolutionary selection.
India-specific: uses India 10Y Government Bond yield (~7.1%) as risk-free rate.

Key safeguards against Sharpe inflation:
    - Minimum 30 returns required (not 5)
    - Annualization only for agents with ≥ 50 steps
    - Lifetime penalty for short-lived agents
    - Volatility floor to prevent divide-by-near-zero
"""

import numpy as np
from typing import Optional
from config import setup_logger, RISK_FREE_RATE, SHARPE_WINDOW, SHARPE_ELITE_THR

logger = setup_logger("esti.training.sharpe")

# Minimum steps before we trust the Sharpe
MIN_RETURNS_FOR_SHARPE = 30
# Only annualise if the agent has survived this many steps
MIN_STEPS_FOR_ANNUALISE = 50
# Minimum volatility floor to prevent division by near-zero
VOLATILITY_FLOOR = 1e-4


class SharpeOptimizer:
    """
    Calculates and tracks Sharpe ratios for the ESTI population.

    Sharpe Ratio:
        SR_i = (E[R_i] - R_f) / max(σ_i, σ_floor) × lifetime_penalty

    Where:
        E[R_i] = mean return of agent i
        R_f    = risk-free rate (daily: annual_rate / 252)
        σ_i    = std dev of returns (floored at 1e-4)
        lifetime_penalty = sqrt(min(steps, 252) / 252)
    """

    def __init__(
        self,
        risk_free_annual: float = RISK_FREE_RATE,
        window: int = SHARPE_WINDOW,
        elite_threshold: float = SHARPE_ELITE_THR,
    ):
        self.daily_rf = risk_free_annual / 252.0
        self.window = window
        self.elite_threshold = elite_threshold

        # Track elite strategies
        self._elite_sharpes: list[float] = []

        logger.info(
            f"📈 SharpeOptimizer initialised | R_f(annual)={risk_free_annual:.3f} "
            f"| R_f(daily)={self.daily_rf:.6f} | window={window} "
            f"| elite_threshold={elite_threshold} "
            f"| min_returns={MIN_RETURNS_FOR_SHARPE} "
            f"| min_annualise={MIN_STEPS_FOR_ANNUALISE} "
            f"| vol_floor={VOLATILITY_FLOOR}"
        )

    def calculate_sharpe(
        self,
        returns: list[float],
        annualise: bool = True,
    ) -> float:
        """
        Calculate the Sharpe ratio for a series of returns.

        Safeguards:
            1. Requires >= 30 returns (not 5)
            2. Volatility floored at 1e-4 to prevent inflate-by-division
            3. Only annualised if >= 50 steps (otherwise raw daily Sharpe)
            4. Lifetime-penalised: sqrt(min(steps, 252) / 252) so short
               lifetimes can never score as high as long survivors

        Args:
            returns:    list of period returns (e.g. daily)
            annualise:  if True AND agent has 50+ steps, annualise

        Returns:
            Sharpe ratio (float). Returns 0.0 if insufficient data.
        """
        n = len(returns)

        if n < MIN_RETURNS_FOR_SHARPE:
            logger.debug(
                f"Insufficient returns ({n} < {MIN_RETURNS_FOR_SHARPE}) — Sharpe=0.0"
            )
            return 0.0

        # Use the most recent `window` returns
        recent = returns[-self.window :]
        arr = np.array(recent, dtype=np.float64)

        excess_returns = arr - self.daily_rf
        mean_excess = excess_returns.mean()
        std_returns = arr.std(ddof=1)

        # Floor standard deviation to prevent inflation from near-zero vol
        effective_std = max(std_returns, VOLATILITY_FLOOR)

        sharpe = mean_excess / effective_std

        # Only annualise if agent has survived long enough for it to be meaningful
        if annualise and n >= MIN_STEPS_FOR_ANNUALISE:
            sharpe *= np.sqrt(252)
        elif annualise:
            logger.debug(
                f"Skipping annualisation ({n} < {MIN_STEPS_FOR_ANNUALISE} steps)"
            )

        # Lifetime penalty: short-lived agents are penalised because their
        # statistics are less trustworthy. An agent with 30 steps gets
        # penalty = sqrt(30/252) ≈ 0.345, while 252 steps gets 1.0
        lifetime_factor = np.sqrt(min(n, 252) / 252.0)
        sharpe *= lifetime_factor

        logger.info(
            f"🎯 Agent-{n:03d} Sharpe: {sharpe:.4f} | "
            f"Mean Excess: {mean_excess:.6f} | "
            f"Volatility: {effective_std:.6f} | "
            f"Penalty: {lifetime_factor:.3f}"
        )

        return round(float(sharpe), 4)

    def rank_by_sharpe(
        self,
        all_returns: list[list[float]],
    ) -> list[tuple[int, float]]:
        """
        Rank all agents by their Sharpe ratio.

        Args:
            all_returns: list of return histories, one per agent

        Returns:
            [(agent_idx, sharpe)] sorted descending by Sharpe
        """
        scores = []
        for i, returns in enumerate(all_returns):
            sharpe = self.calculate_sharpe(returns)
            scores.append((i, sharpe))

        scores.sort(key=lambda x: x[1], reverse=True)

        if scores:
            best = scores[0]
            worst = scores[-1]
            avg = np.mean([s for _, s in scores])
            logger.info(
                f"📊 Sharpe rankings | n={len(scores)} | "
                f"best=[{best[0]}]={best[1]:.4f} | worst=[{worst[0]}]={worst[1]:.4f} "
                f"| avg={avg:.4f}"
            )

            # Track elites
            new_elites = [(i, s) for i, s in scores if s >= self.elite_threshold]
            if new_elites:
                logger.info(
                    f"⭐ Elite agents (Sharpe ≥ {self.elite_threshold}): "
                    + ", ".join(f"Agent-{i:03d}({s:.3f})" for i, s in new_elites)
                )

        return scores

    def get_fitness_scores(
        self,
        all_returns: list[list[float]],
    ) -> list[float]:
        """
        Get Sharpe-based fitness scores for evolutionary selection.

        Returns list aligned by agent index.
        """
        return [self.calculate_sharpe(r) for r in all_returns]

    def get_stats(self) -> dict:
        """Return optimizer statistics."""
        return {
            "risk_free_annual": round(self.daily_rf * 252, 4),
            "risk_free_daily": round(self.daily_rf, 8),
            "window": self.window,
            "elite_threshold": self.elite_threshold,
            "min_returns": MIN_RETURNS_FOR_SHARPE,
            "min_annualise_steps": MIN_STEPS_FOR_ANNUALISE,
            "volatility_floor": VOLATILITY_FLOOR,
        }
