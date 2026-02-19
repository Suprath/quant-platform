"""
PopulationManager — Lifecycle Management for the Agent Population

Handles creation, extinction, repopulation, and diversity monitoring.
"""

import torch
from typing import Optional
from core.esti_policy import ESTIPolicy
from core.survival_engine import AgentState
from core.knowledge_archive import KnowledgeArchive
from training.evolutionary_ops import tournament_select, create_offspring
from config import (
    setup_logger,
    POPULATION_SIZE,
    INITIAL_CAPITAL,
    STATE_DIM,
    BRAIN_DIM,
    HIDDEN_DIM,
    MUTATION_SIGMA,
    CROSSOVER_RATE,
    MIN_POPULATION,
    DEVICE,
)

logger = setup_logger("esti.agents.population")


class PopulationManager:
    """
    Manages the full lifecycle of agent population:
        - Initialisation with diverse random strategies
        - Tracking alive/dead status
        - Evolutionary repopulation when agents die
        - Population diversity monitoring
    """

    def __init__(
        self,
        population_size: int = POPULATION_SIZE,
        initial_capital: float = INITIAL_CAPITAL,
        archive: Optional[KnowledgeArchive] = None,
    ):
        self.population_size = population_size
        self.initial_capital = initial_capital
        self.archive = archive

        self.policies: list[ESTIPolicy] = []
        self.agents: list[AgentState] = []
        self._next_id = 0
        self._total_births = 0
        self._total_deaths = 0

        logger.info(
            f"👥 PopulationManager initialised | size={population_size} "
            f"| capital=₹{initial_capital:,.0f}"
        )

    # ──────────────────────────────────────────
    #  Initialisation
    # ──────────────────────────────────────────

    def initialize_population(self) -> int:
        """
        Create the initial population with diverse random strategies.

        Returns:
            Number of agents created
        """
        logger.info(f"🌱 Initialising population of {self.population_size} agents...")

        for i in range(self.population_size):
            self._spawn_agent(birth_step=0)

        self._total_births = self.population_size
        logger.info(
            f"✅ Population initialised | {len(self.policies)} agents | "
            f"params_per_agent={self.policies[0].param_count():,}"
        )
        return len(self.policies)

    def _spawn_agent(self, birth_step: int = 0, params: Optional[torch.Tensor] = None) -> int:
        """Create a new agent with optional initial parameters."""
        agent_id = self._next_id
        self._next_id += 1

        # Create policy network
        policy = ESTIPolicy(
            state_dim=STATE_DIM,
            brain_dim=BRAIN_DIM,
            hidden_dim=HIDDEN_DIM,
            agent_id=agent_id,
        ).to(DEVICE)

        # Load specific params if provided (offspring)
        if params is not None:
            policy.set_flat_params(params)

        # Create survival state
        state = AgentState(
            agent_id=agent_id,
            capital=self.initial_capital,
            birth_step=birth_step,
            current_step=birth_step,
        )

        self.policies.append(policy)
        self.agents.append(state)
        self._total_births += 1

        logger.debug(f"    🌱 Agent-{agent_id:03d} spawned at step {birth_step}")
        return agent_id

    # ──────────────────────────────────────────
    #  Extinction handling
    # ──────────────────────────────────────────

    def handle_extinctions(
        self,
        extinct_agents: list[AgentState],
        brain_state: torch.Tensor,
        fitness_scores: list[float],
        current_step: int,
    ) -> int:
        """
        Process extinct agents: archive knowledge, then repopulate slots.

        Args:
            extinct_agents:  agents that died this step
            brain_state:     current B_t for embedding computation
            fitness_scores:  Sharpe ratios for alive agents (for parent selection)
            current_step:    current training timestep

        Returns:
            Number of new agents spawned
        """
        if not extinct_agents:
            return 0

        logger.info(
            f"☠️  Processing {len(extinct_agents)} extinctions at step {current_step}"
        )

        # 1. Archive dead agents
        for agent in extinct_agents:
            self._archive_extinct(agent, brain_state)

        # 2. Repopulate with offspring from surviving agents
        alive_policies = [
            (p, s) for p, s in zip(self.policies, self.agents)
            if s.alive
        ]

        if len(alive_policies) < 2:
            logger.warning("⚠️  Fewer than 2 alive agents — cannot reproduce, spawning random")
            for _ in extinct_agents:
                self._spawn_agent(birth_step=current_step)
            return len(extinct_agents)

        # Get fitness scores for alive agents only
        alive_fitness = [
            fitness_scores[i] for i, a in enumerate(self.agents) if a.alive
        ]

        # Get knowledge-guided mutation noise
        guidance_std = None
        if self.archive:
            guidance_std = self.archive.sample_mutation_guidance()

        spawned = 0
        for dead_agent in extinct_agents:
            # Tournament selection for parents
            p1_idx = tournament_select(alive_fitness)
            p2_idx = tournament_select(alive_fitness)
            while p2_idx == p1_idx and len(alive_fitness) > 1:
                p2_idx = tournament_select(alive_fitness)

            parent1 = alive_policies[p1_idx][0]
            parent2 = alive_policies[p2_idx][0]

            # Create offspring
            child_params = create_offspring(
                parent1.get_flat_params(),
                parent2.get_flat_params(),
                sigma=MUTATION_SIGMA,
                crossover_rate=CROSSOVER_RATE,
                guidance_std=guidance_std,
            )

            self._spawn_agent(birth_step=current_step, params=child_params)
            spawned += 1

            logger.info(
                f"👶 Agent-{self._next_id - 1:03d} born "
                f"| parents: Agent-{alive_policies[p1_idx][1].agent_id:03d} × "
                f"Agent-{alive_policies[p2_idx][1].agent_id:03d} "
                f"| replacing Agent-{dead_agent.agent_id:03d}"
            )

        self._total_deaths += len(extinct_agents)
        return spawned

    def _archive_extinct(self, agent: AgentState, brain_state: torch.Tensor):
        """Archive an extinct agent's knowledge."""
        if not self.archive:
            return

        # Find the agent's policy
        policy = None
        for p, s in zip(self.policies, self.agents):
            if s.agent_id == agent.agent_id:
                policy = p
                break

        if policy is None:
            logger.warning(f"⚠️  Could not find policy for extinct Agent-{agent.agent_id}")
            return

        # Get agent embedding
        dummy_state = torch.zeros(STATE_DIM)
        embedding = policy.get_embedding(dummy_state)

        self.archive.archive_agent(
            agent_id=agent.agent_id,
            flat_params=policy.get_flat_params(),
            embedding=embedding,
            lifetime_steps=agent.current_step - agent.birth_step,
            final_capital=agent.capital,
            peak_capital=agent.peak_capital,
            final_sharpe=agent.sharpe,
            failure_category=agent.death_cause or "score_extinction",
        )

    # ──────────────────────────────────────────
    #  Emergency repopulation
    # ──────────────────────────────────────────

    def emergency_repopulate(self, current_step: int) -> int:
        """
        Reset population if near extinction.
        Called when alive < MIN_POPULATION.
        """
        alive = sum(1 for a in self.agents if a.alive)
        needed = self.population_size - alive

        logger.warning(
            f"🚨 EMERGENCY REPOPULATE | alive={alive} < min={MIN_POPULATION} "
            f"| spawning {needed} new random agents"
        )

        for _ in range(needed):
            self._spawn_agent(birth_step=current_step)

        return needed

    # ──────────────────────────────────────────
    #  Accessors
    # ──────────────────────────────────────────

    def get_alive(self) -> list[tuple[ESTIPolicy, AgentState]]:
        """Return (policy, state) pairs for all alive agents."""
        return [
            (p, s) for p, s in zip(self.policies, self.agents)
            if s.alive
        ]

    def alive_count(self) -> int:
        return sum(1 for a in self.agents if a.alive)

    def get_stats(self) -> dict:
        return {
            "alive": self.alive_count(),
            "total_agents": len(self.agents),
            "total_births": self._total_births,
            "total_deaths": self._total_deaths,
            "next_id": self._next_id,
        }
