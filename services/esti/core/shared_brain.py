"""
SharedBrain — Global Collective Intelligence Module

Theory Reference (Section 8.3):
    B_t = f(K_alive, K_dead)
    
The SharedBrain compresses knowledge from both living (successful) and extinct
(failed) agents into a global brain state that every agent can condition on.
This implements the "collective memory" of the population.
"""

import torch
import torch.nn as nn
from config import setup_logger, BRAIN_DIM

logger = setup_logger("esti.core.shared_brain")


class SharedBrain(nn.Module):
    """
    Global collective intelligence compressed from population knowledge.

    Architecture:
        Input:  alive_repr (brain_dim) + dead_repr (brain_dim) = 2*brain_dim
        Hidden: 2-layer MLP with LayerNorm
        Output: brain_dim global brain state B_t

    The brain learns from BOTH living successful agents AND extinct failed agents,
    creating a "collective memory" of what works and what kills.
    """

    def __init__(self, brain_dim: int = BRAIN_DIM):
        super().__init__()
        self.brain_dim = brain_dim
        input_dim = brain_dim * 2  # alive + dead representations

        self.network = nn.Sequential(
            nn.Linear(input_dim, brain_dim * 2),
            nn.LayerNorm(brain_dim * 2),
            nn.ReLU(),
            nn.Linear(brain_dim * 2, brain_dim * 2),
            nn.LayerNorm(brain_dim * 2),
            nn.ReLU(),
            nn.Linear(brain_dim * 2, brain_dim),
        )

        # Running statistics for alive and dead populations
        self.register_buffer("alive_mean", torch.zeros(brain_dim))
        self.register_buffer("dead_mean", torch.zeros(brain_dim))
        self._update_count = 0

        logger.info(
            f"🧠 SharedBrain initialised | brain_dim={brain_dim} "
            f"| input_dim={input_dim} | params={sum(p.numel() for p in self.parameters()):,}"
        )

    # ────────────────────────────────────────────
    #  Core forward pass
    # ────────────────────────────────────────────

    def forward(self, alive_repr: torch.Tensor, dead_repr: torch.Tensor) -> torch.Tensor:
        """
        Compute global brain state B_t.

        Args:
            alive_repr:  (brain_dim,) — mean embedding from alive agents
            dead_repr:   (brain_dim,) — mean embedding from archived dead agents

        Returns:
            B_t: (brain_dim,) — global brain state that all agents condition on
        """
        combined = torch.cat([alive_repr, dead_repr], dim=-1)
        brain_state = self.network(combined)

        if logger.isEnabledFor(10):  # DEBUG
            logger.debug(
                f"B_t computed | alive_norm={alive_repr.norm():.4f} "
                f"| dead_norm={dead_repr.norm():.4f} "
                f"| brain_norm={brain_state.norm():.4f}"
            )
        return brain_state

    # ────────────────────────────────────────────
    #  Population-level updates
    # ────────────────────────────────────────────

    def update_from_population(
        self,
        alive_embeddings: list[torch.Tensor],
        dead_embeddings: list[torch.Tensor],
    ) -> torch.Tensor:
        """
        Compute B_t from raw lists of agent embeddings.

        This is the main entry point called by the GodAgent every evolutionary step.
        It aggregates per-agent embeddings into population-level representations,
        then passes them through the brain network.

        Args:
            alive_embeddings: list of (brain_dim,) tensors from alive agents
            dead_embeddings:  list of (brain_dim,) tensors from knowledge archive

        Returns:
            B_t: (brain_dim,) global brain state
        """
        # Aggregate alive agents
        if alive_embeddings:
            alive_stack = torch.stack(alive_embeddings)
            alive_repr = alive_stack.mean(dim=0)
        else:
            alive_repr = torch.zeros(self.brain_dim)
            logger.warning("⚠️  No alive embeddings provided — using zero vector")

        # Aggregate dead agents (knowledge archive)
        if dead_embeddings:
            dead_stack = torch.stack(dead_embeddings)
            dead_repr = dead_stack.mean(dim=0)
        else:
            dead_repr = torch.zeros(self.brain_dim)
            logger.debug("No dead embeddings yet (archive empty) — using zero vector")

        # Update running means for monitoring
        self.alive_mean = alive_repr.detach()
        self.dead_mean = dead_repr.detach()
        self._update_count += 1

        brain_state = self.forward(alive_repr, dead_repr)

        if self._update_count % 50 == 0:
            logger.info(
                f"🧠 SharedBrain | update #{self._update_count} "
                f"| alive_agents={len(alive_embeddings)} "
                f"| dead_agents={len(dead_embeddings)} "
                f"| B_t_norm={brain_state.norm():.4f}"
            )

        return brain_state

    def get_state_summary(self) -> dict:
        """Return diagnostic information about the brain state."""
        return {
            "brain_dim": self.brain_dim,
            "update_count": self._update_count,
            "alive_mean_norm": float(self.alive_mean.norm()),
            "dead_mean_norm": float(self.dead_mean.norm()),
            "total_params": sum(p.numel() for p in self.parameters()),
        }
