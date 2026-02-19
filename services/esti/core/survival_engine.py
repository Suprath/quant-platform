"""
SurvivalEngine — Capital Dynamics, Growth, Health & Composite Score

Theory References:
    Section 3: C_i(t+1) = C_i(t) · (1 + r_i(t))
    Section 4: G_i(t) < G_base ⇒ H_i(t+1) = H_i(t) - λ
    Section 5: R_i(t) = rank(G_i(t))
    Section 6: Σ_i(t) = w_c·C̃_i + w_g·G̃_i + w_h·H_i + w_r·R_i
"""

import torch
import numpy as np
from dataclasses import dataclass, field
from typing import Optional
from config import (
    setup_logger,
    INITIAL_CAPITAL,
    BASE_GROWTH,
    HEALTH_DECAY,
    GROWTH_WINDOW,
    WEIGHT_CAPITAL,
    WEIGHT_GROWTH,
    WEIGHT_HEALTH,
    WEIGHT_RANK,
)

logger = setup_logger("esti.core.survival")


@dataclass
class AgentState:
    """Tracks the survival state of a single trading agent."""

    agent_id: int
    capital: float = INITIAL_CAPITAL
    health: float = 1.0          # H_i ∈ [0, 1]
    peak_capital: float = INITIAL_CAPITAL
    alive: bool = True
    birth_step: int = 0
    current_step: int = 0

    # History buffers
    capital_history: list = field(default_factory=list)
    return_history: list = field(default_factory=list)

    # Computed each step
    growth: float = 0.0          # G_i(t)
    rank: float = 0.5            # R_i(t) ∈ [0, 1]
    survival_score: float = 1.0  # Σ_i(t)
    sharpe: float = 0.0

    # Death info
    death_step: Optional[int] = None
    death_cause: Optional[str] = None

    def __post_init__(self):
        self.capital_history = [self.capital]


class SurvivalEngine:
    """
    Implements survival mechanics from ESTI Theory Sections 3-6.

    Responsibilities:
        1. Update capital after trades
        2. Calculate growth G_i(t) and enforce mandatory growth law
        3. Compute population-relative ranks R_i(t)
        4. Calculate composite survival score Σ_i(t)
        5. Determine extinctions
    """

    def __init__(
        self,
        initial_capital: float = INITIAL_CAPITAL,
        g_base: float = BASE_GROWTH,
        health_decay: float = HEALTH_DECAY,
        growth_window: int = GROWTH_WINDOW,
        w_c: float = WEIGHT_CAPITAL,
        w_g: float = WEIGHT_GROWTH,
        w_h: float = WEIGHT_HEALTH,
        w_r: float = WEIGHT_RANK,
    ):
        self.initial_capital = initial_capital
        self.g_base = g_base
        self.health_decay = health_decay
        self.growth_window = growth_window
        self.w_c = w_c
        self.w_g = w_g
        self.w_h = w_h
        self.w_r = w_r

        logger.info(
            f"⚙️  SurvivalEngine initialised | G_base={g_base} | λ={health_decay} "
            f"| window={growth_window} | weights=[{w_c},{w_g},{w_h},{w_r}]"
        )

    # ──────────────────────────────────────────
    #  Step 1: Capital update (Section 3)
    # ──────────────────────────────────────────

    def update_capital(self, agent: AgentState, trade_return: float) -> float:
        """
        C_i(t+1) = C_i(t) · (1 + r_i(t))

        Args:
            agent: agent state
            trade_return: fractional return for this step (e.g. 0.005 for +0.5%)

        Returns:
            New capital value
        """
        old_capital = agent.capital
        agent.capital = agent.capital * (1.0 + trade_return)
        agent.capital = max(agent.capital, 0.0)  # Cannot go negative

        agent.return_history.append(trade_return)
        agent.capital_history.append(agent.capital)
        agent.current_step += 1

        # Track peak
        if agent.capital > agent.peak_capital:
            agent.peak_capital = agent.capital

        # Extinction Condition 1: Capital ≤ 0
        if agent.capital <= 0:
            agent.alive = False
            agent.death_step = agent.current_step
            agent.death_cause = "capital_collapse"
            logger.warning(
                f"💀 Agent-{agent.agent_id:03d} EXTINCT (capital collapse) | "
                f"step={agent.current_step} | return={trade_return:+.4f} "
                f"| capital: ₹{old_capital:,.0f} → ₹0"
            )
        elif logger.isEnabledFor(10):  # DEBUG
            logger.debug(
                f"   Agent-{agent.agent_id:03d} capital update | "
                f"₹{old_capital:,.0f} → ₹{agent.capital:,.0f} ({trade_return:+.4%})"
            )

        return agent.capital

    # ──────────────────────────────────────────
    #  Step 2: Mandatory Growth & Health (Section 4)
    # ──────────────────────────────────────────

    def update_growth_and_health(self, agent: AgentState):
        """
        G_i(t) = (C_i(t) - C_i(t-k)) / C_i(t-k)
        If G_i(t) < G_base: H_i(t+1) = H_i(t) - λ

        Stagnation implies gradual death.
        """
        if not agent.alive:
            return

        k = min(self.growth_window, len(agent.capital_history) - 1)
        if k <= 0:
            return

        past_capital = agent.capital_history[-k - 1]
        if past_capital > 0:
            agent.growth = (agent.capital - past_capital) / past_capital
        else:
            agent.growth = 0.0

        # Mandatory growth law
        if agent.growth < self.g_base:
            old_health = agent.health
            agent.health = max(0.0, agent.health - self.health_decay)

            if agent.health <= 0:
                agent.alive = False
                agent.death_step = agent.current_step
                agent.death_cause = "stagnation_death"
                logger.warning(
                    f"💀 Agent-{agent.agent_id:03d} EXTINCT (stagnation) | "
                    f"growth={agent.growth:+.4f} < G_base={self.g_base} "
                    f"| health decayed to 0 over {agent.current_step - agent.birth_step} steps"
                )
            elif logger.isEnabledFor(10):
                logger.debug(
                    f"   Agent-{agent.agent_id:03d} stagnating | "
                    f"growth={agent.growth:+.4f} | health: {old_health:.3f} → {agent.health:.3f}"
                )
        else:
            # Reward growth with small health recovery
            agent.health = min(1.0, agent.health + self.health_decay * 0.1)

    # ──────────────────────────────────────────
    #  Step 3: Population-relative ranking (Section 5)
    # ──────────────────────────────────────────

    def compute_ranks(self, agents: list[AgentState]):
        """
        R_i(t) = rank(G_i(t)) normalised to [0, 1].
        """
        alive_agents = [a for a in agents if a.alive]
        if not alive_agents:
            return

        # Sort by growth rate
        sorted_agents = sorted(alive_agents, key=lambda a: a.growth)
        n = len(sorted_agents)
        for rank_idx, agent in enumerate(sorted_agents):
            agent.rank = rank_idx / max(n - 1, 1)

    # ──────────────────────────────────────────
    #  Step 4: Composite Survival Score (Section 6)
    # ──────────────────────────────────────────

    def compute_survival_scores(self, agents: list[AgentState]):
        """
        Σ_i(t) = w_c·C̃_i + w_g·G̃_i + w_h·H_i + w_r·R_i

        C̃ and G̃ are min-max normalised across the population.
        Extinction if Σ_i(t) ≤ 0.
        """
        alive_agents = [a for a in agents if a.alive]
        if not alive_agents:
            return

        capitals = [a.capital for a in alive_agents]
        growths = [a.growth for a in alive_agents]

        cap_min, cap_max = min(capitals), max(capitals)
        gro_min, gro_max = min(growths), max(growths)

        cap_range = cap_max - cap_min if cap_max > cap_min else 1.0
        gro_range = gro_max - gro_min if gro_max > gro_min else 1.0

        newly_extinct = []

        for agent in alive_agents:
            c_norm = (agent.capital - cap_min) / cap_range
            g_norm = (agent.growth - gro_min) / gro_range

            agent.survival_score = (
                self.w_c * c_norm
                + self.w_g * g_norm
                + self.w_h * agent.health
                + self.w_r * agent.rank
            )

            # Extinction Condition 2: Σ ≤ 0
            if agent.survival_score <= 0:
                agent.alive = False
                agent.death_step = agent.current_step
                agent.death_cause = "score_extinction"
                newly_extinct.append(agent)
                logger.warning(
                    f"💀 Agent-{agent.agent_id:03d} EXTINCT (score=0) | "
                    f"Σ={agent.survival_score:.4f} | "
                    f"C̃={c_norm:.3f} G̃={g_norm:.3f} H={agent.health:.3f} R={agent.rank:.3f}"
                )

        if newly_extinct:
            logger.info(
                f"☠️  Extinction event: {len(newly_extinct)} agents died | "
                f"remaining alive: {len(alive_agents) - len(newly_extinct)}"
            )

    # ──────────────────────────────────────────
    #  Combined step
    # ──────────────────────────────────────────

    def step(self, agents: list[AgentState], returns: list[float]) -> list[AgentState]:
        """
        Run one full survival step for all agents.

        Args:
            agents:  all agent states
            returns: trade returns per agent (aligned by index)

        Returns:
            List of agents that went extinct this step
        """
        newly_dead = []
        alive_before = sum(1 for a in agents if a.alive)

        for agent, ret in zip(agents, returns):
            if not agent.alive:
                continue

            self.update_capital(agent, ret)
            self.update_growth_and_health(agent)

            if not agent.alive:
                newly_dead.append(agent)

        # Population-relative computations
        self.compute_ranks(agents)
        self.compute_survival_scores(agents)

        # Check for score-based extinctions
        for agent in agents:
            if not agent.alive and agent not in newly_dead:
                newly_dead.append(agent)

        alive_after = sum(1 for a in agents if a.alive)

        if newly_dead or alive_before != alive_after:
            logger.info(
                f"📊 Survival step complete | alive: {alive_before} → {alive_after} "
                f"| newly extinct: {len(newly_dead)}"
            )

        return newly_dead

    # ──────────────────────────────────────────
    #  Diagnostics
    # ──────────────────────────────────────────

    def get_population_stats(self, agents: list[AgentState]) -> dict:
        """Return aggregate population statistics for monitoring."""
        alive = [a for a in agents if a.alive]
        dead = [a for a in agents if not a.alive]

        if not alive:
            return {
                "alive_count": 0,
                "dead_count": len(dead),
                "avg_capital": 0,
                "avg_health": 0,
                "avg_growth": 0,
                "avg_survival_score": 0,
            }

        return {
            "alive_count": len(alive),
            "dead_count": len(dead),
            "total_agents": len(agents),
            "avg_capital": round(np.mean([a.capital for a in alive]), 2),
            "max_capital": round(max(a.capital for a in alive), 2),
            "min_capital": round(min(a.capital for a in alive), 2),
            "avg_health": round(np.mean([a.health for a in alive]), 4),
            "avg_growth": round(np.mean([a.growth for a in alive]), 6),
            "avg_survival_score": round(np.mean([a.survival_score for a in alive]), 4),
            "avg_rank": round(np.mean([a.rank for a in alive]), 4),
        }
