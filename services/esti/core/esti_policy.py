"""
ESTIPolicy — Individual Agent Trading Policy

Theory Reference (Section 8.3):
    π_i(a|s) = π(a|s, θ_i, B_t)
    
Each agent has private evolvable parameters θ_i, but also conditions on the
SharedBrain state B_t (collective intelligence). This bridges individual
learning with population-level knowledge.
"""

import torch
import torch.nn as nn
import torch.nn.functional as F
from config import setup_logger, STATE_DIM, BRAIN_DIM, HIDDEN_DIM

logger = setup_logger("esti.core.esti_policy")


class ESTIPolicy(nn.Module):
    """
    Individual trading policy conditioned on private params θ_i AND shared brain B_t.

    Architecture:
        Private Encoder: state_dim → hidden_dim → brain_dim (private θ_i)
        Integration:     [private | brain_state] → hidden_dim → brain_dim
        Output Heads:
            ├── Direction  (3-class: Long/Short/Hold)
            ├── Position Size (sigmoid → [0,1])
            ├── Stop Distance (softplus → ℝ+)
            └── Uncertainty   (sigmoid → [0,1])

    Key Innovation: evolvable private parameters + shared collective intelligence.
    """

    def __init__(
        self,
        state_dim: int = STATE_DIM,
        brain_dim: int = BRAIN_DIM,
        hidden_dim: int = HIDDEN_DIM,
        agent_id: int = 0,
    ):
        super().__init__()
        self.state_dim = state_dim
        self.brain_dim = brain_dim
        self.hidden_dim = hidden_dim
        self.agent_id = agent_id

        # ── Private encoder (evolvable θ_i) ──
        self.private_encoder = nn.Sequential(
            nn.Linear(state_dim, hidden_dim),
            nn.ReLU(),
            nn.Linear(hidden_dim, brain_dim),
            nn.ReLU(),
        )

        # ── Integration layer (merge private + shared brain) ──
        self.integration = nn.Sequential(
            nn.Linear(brain_dim * 2, hidden_dim),
            nn.LayerNorm(hidden_dim),
            nn.ReLU(),
            nn.Linear(hidden_dim, brain_dim),
            nn.ReLU(),
        )

        # ── Output heads ──
        self.direction_head = nn.Linear(brain_dim, 3)     # Long / Short / Hold
        self.position_head = nn.Linear(brain_dim, 1)      # Position size [0, 1]
        self.stop_head = nn.Linear(brain_dim, 1)           # Stop-loss distance ℝ+
        self.uncertainty_head = nn.Linear(brain_dim, 1)    # Confidence [0, 1]

        param_count = sum(p.numel() for p in self.parameters())
        logger.debug(
            f"    Agent-{agent_id:03d} ESTIPolicy created "
            f"| state_dim={state_dim} | brain_dim={brain_dim} | params={param_count:,}"
        )

    def forward(
        self,
        state: torch.Tensor,
        brain_state: torch.Tensor,
    ) -> dict:
        """
        Compute trading decision from market state + shared brain.

        Args:
            state:       (state_dim,) market feature vector
            brain_state: (brain_dim,) shared brain B_t

        Returns:
            dict with keys:
                direction_probs: (3,) softmax — [Long, Short, Hold]
                direction:       int — argmax action (0=Long, 1=Short, 2=Hold)
                position_size:   float in [0, 1]
                stop_distance:   float in ℝ+
                uncertainty:     float in [0, 1]
        """
        # Private encoding
        private_repr = self.private_encoder(state)

        # Integrate with shared brain
        combined = torch.cat([private_repr, brain_state], dim=-1)
        integrated = self.integration(combined)

        # Output heads
        direction_logits = self.direction_head(integrated)
        direction_probs = F.softmax(direction_logits, dim=-1)
        direction = torch.argmax(direction_probs).item()

        position_size = torch.sigmoid(self.position_head(integrated)).squeeze(-1).item()
        stop_distance = F.softplus(self.stop_head(integrated)).squeeze(-1).item()
        uncertainty = torch.sigmoid(self.uncertainty_head(integrated)).squeeze(-1).item()

        return {
            "direction_probs": direction_probs,
            "direction": direction,           # 0=Long, 1=Short, 2=Hold
            "position_size": position_size,   # [0, 1]
            "stop_distance": stop_distance,   # ℝ+
            "uncertainty": uncertainty,        # [0, 1]
        }

    def get_embedding(self, state: torch.Tensor) -> torch.Tensor:
        """
        Get the private encoding of a market state — used to build
        alive_embeddings for the SharedBrain.

        Returns:
            (brain_dim,) tensor
        """
        return self.private_encoder(state).detach()

    def get_flat_params(self) -> torch.Tensor:
        """Flatten all parameters into a single 1-D tensor (for evolutionary ops)."""
        return torch.cat([p.data.view(-1) for p in self.parameters()])

    def set_flat_params(self, flat_params: torch.Tensor):
        """Load parameters from a flat 1-D tensor (for evolutionary ops)."""
        offset = 0
        for p in self.parameters():
            numel = p.numel()
            p.data.copy_(flat_params[offset : offset + numel].view(p.shape))
            offset += numel

    def param_count(self) -> int:
        return sum(p.numel() for p in self.parameters())
