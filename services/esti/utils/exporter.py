"""
Exporter: Extracts the god_agent's best PyTorch Brain and Policy.
Returns a Base64-encoded string representing the Neural Network weights
that can be injected directly into a Python Strategy template.
"""
import io
import base64
import torch
import logging

logger = logging.getLogger("esti.exporter")

def export_best_agent_weights(god_agent) -> str:
    """
    Finds the best surviving agent, extracts the neural weights, and
    serializes them into a base64 string for embedding.
    """
    alive_pairs = god_agent.population.get_alive()
    if not alive_pairs:
        raise ValueError("No agents survived to export.")

    rankings = god_agent.sharpe.rank_by_sharpe([s.return_history for _, s in alive_pairs])
    if not rankings:
         raise ValueError("Could not rank agents.")

    best_idx, best_sharpe = rankings[0]
    best_policy, best_state = alive_pairs[best_idx]

    logger.info(f"🏆 Exporting Agent {best_state.agent_id} (Sharpe: {best_sharpe:.2f})")

    # Serialize policy state_dict
    buffer = io.BytesIO()
    torch.save({
        'brain_state_dict': god_agent.brain.state_dict(),
        'policy_state_dict': best_policy.state_dict(),
        'agent_id': best_state.agent_id,
        'sharpe': best_sharpe
    }, buffer)
    
    buffer.seek(0)
    encoded = base64.b64encode(buffer.read()).decode('utf-8')
    return encoded
