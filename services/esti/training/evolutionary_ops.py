"""
Evolutionary Operators — Mutation, Crossover, and Tournament Selection

Theory Reference (Section 8):
    Mutation:               θ' = θ + ε, ε ~ N(0, σ²)
    Knowledge-guided:       ε ~ D(K)
    Tournament selection:   top-k from random pool
"""

import torch
import numpy as np
from typing import Optional
from config import (
    setup_logger,
    MUTATION_SIGMA,
    CROSSOVER_RATE,
    TOURNAMENT_SIZE,
)

logger = setup_logger("esti.training.evolution")


def mutate(
    params: torch.Tensor,
    sigma: float = MUTATION_SIGMA,
    guidance_std: Optional[torch.Tensor] = None,
) -> torch.Tensor:
    """
    Mutate agent parameters.

    If `guidance_std` is provided (from KnowledgeArchive), use knowledge-guided
    mutation that concentrates noise on dimensions where dead agents varied most.

    Args:
        params:        flat parameter vector (1-D tensor)
        sigma:         base mutation standard deviation
        guidance_std:  per-dimension std from extinct agents (optional)

    Returns:
        Mutated parameter vector
    """
    if guidance_std is not None and guidance_std.shape == params.shape:
        # Knowledge-guided mutation: ε ~ D(K)
        # Scale noise by dead agent parameter variance — explore where failures diverged
        noise = torch.randn_like(params) * guidance_std * sigma
        logger.debug(
            f"🧬 Knowledge-guided mutation | σ={sigma:.4f} "
            f"| guidance_std_mean={guidance_std.mean():.6f}"
        )
    else:
        # Standard Gaussian mutation
        noise = torch.randn_like(params) * sigma
        logger.debug(f"🧬 Standard mutation | σ={sigma:.4f}")

    return params + noise


def crossover(
    parent1: torch.Tensor,
    parent2: torch.Tensor,
    rate: float = CROSSOVER_RATE,
) -> tuple[torch.Tensor, torch.Tensor]:
    """
    Uniform crossover between two parent parameter vectors.

    Each parameter dimension is swapped with probability `rate`.

    Returns:
        (child1, child2) — two new parameter vectors
    """
    mask = torch.rand_like(parent1) < rate
    child1 = torch.where(mask, parent2, parent1)
    child2 = torch.where(mask, parent1, parent2)

    swapped_pct = mask.float().mean().item() * 100
    logger.debug(f"🔀 Crossover | rate={rate:.2f} | swapped={swapped_pct:.1f}% dims")

    return child1, child2


def tournament_select(
    fitness_scores: list[float],
    pool_size: int = TOURNAMENT_SIZE,
) -> int:
    """
    Tournament selection: pick `pool_size` random agents, return index of the fittest.

    Args:
        fitness_scores: Sharpe ratios (or other fitness metric) for each agent
        pool_size:      number of candidates to sample

    Returns:
        Index of the selected agent
    """
    n = len(fitness_scores)
    pool_size = min(pool_size, n)
    candidates = np.random.choice(n, size=pool_size, replace=False)
    winner = candidates[np.argmax([fitness_scores[i] for i in candidates])]

    logger.debug(
        f"🏆 Tournament | pool={pool_size} | "
        f"candidates={list(candidates)} | winner={winner} "
        f"(fitness={fitness_scores[winner]:.4f})"
    )
    return int(winner)


def create_offspring(
    parent1_params: torch.Tensor,
    parent2_params: torch.Tensor,
    sigma: float = MUTATION_SIGMA,
    crossover_rate: float = CROSSOVER_RATE,
    guidance_std: Optional[torch.Tensor] = None,
) -> torch.Tensor:
    """
    Full reproduction: crossover two parents, then mutate offspring.

    Returns:
        New parameter vector for the child agent
    """
    child1, _ = crossover(parent1_params, parent2_params, crossover_rate)
    child = mutate(child1, sigma, guidance_std)

    logger.debug(
        f"👶 Offspring created | parent_norm={parent1_params.norm():.4f} "
        f"| child_norm={child.norm():.4f}"
    )
    return child
