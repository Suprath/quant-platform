"""
Backtester — Out-of-Sample Performance Validation

Runs a population of agents on historical data *without* evolution to measure
true out-of-sample performance. Critical for validating whether the neural
network is learning generalizable patterns or just overfitting.
"""

import torch
import pandas as pd
import numpy as np
from typing import List, Tuple, Dict, Any
from data.feature_engineering import FeatureEngineering
from core.esti_policy import ESTIPolicy
from config import setup_logger, DEVICE, STATE_DIM, BRAIN_DIM

logger = setup_logger("esti.training.backtester")


class Backtester:
    """
    Runs fixed agents on historical data to measure OOS performance.
    """

    def __init__(self):
        self.feature_eng = FeatureEngineering(state_dim=STATE_DIM)

    def run(
        self,
        population: List[Tuple[ESTIPolicy, Any]],  # List of (policy, state)
        brain_state: torch.Tensor,
        data: Dict[str, pd.DataFrame],
        start_date: str,
        end_date: str,
    ) -> Dict[str, float]:
        """
        Run a backtest on the provided data range.

        Args:
            population: List of agents to test (usually top N from training)
            brain_state: The shared brain state B_t fixed during backtest
            data: Dictionary of {symbol: DataFrame} with features pre-computed
            start_date: Backtest start
            end_date: Backtest end

        Returns:
            Dict of aggregate metrics {
                "sharpe": float,
                "total_return": float,
                "max_drawdown": float,
                "win_rate": float
            }
        """
        logger.info(f"🧪 Starting backtest | {start_date} → {end_date} | {len(population)} agents")
        
        # Filter data to date range
        test_data = {}
        for symbol, df in data.items():
            mask = (df['timestamp'] >= start_date) & (df['timestamp'] <= end_date)
            if mask.sum() > 0:
                test_data[symbol] = df.loc[mask].reset_index(drop=True)

        if not test_data:
            logger.warning("⚠️  No data in backtest range")
            return {"sharpe": 0.0, "total_return": 0.0}

        # Run simulation
        total_pnl = 0.0
        daily_returns = []

        # Find max length across symbols
        max_steps = max(len(df) for df in test_data.values())
        
        # Simulation loop
        for t in range(max_steps):
            daily_pnl = 0.0
            
            for symbol, df in test_data.items():
                if t >= len(df):
                    continue

                row = df.iloc[t]
                state_vec = torch.tensor(
                    self.feature_eng.get_state_vector(row), 
                    dtype=torch.float32
                ).to(DEVICE)
                
                actual_return = row.get("returns", 0.0)
                volatility = row.get("volatility_20", 0.02)

                # Each agent trades
                for policy, _ in population:
                    with torch.no_grad():
                        decision = policy(state_vec, brain_state)
                    
                    # Simple execution logic for backtest
                    direction = decision["direction"]  # 0=Long, 1=Short, 2=Hold
                    raw_size = decision["position_size"]
                    
                    # Apply volatility sizing (simplified)
                    size = raw_size * (0.01 / max(volatility, 0.01))
                    size = min(max(size, 0.0), 1.0) # Cap at 100% leverage

                    if direction == 0:
                        daily_pnl += actual_return * size
                    elif direction == 1:
                        daily_pnl += -actual_return * size

            # Average PnL per agent
            avg_daily_pnl = daily_pnl / len(population)
            daily_returns.append(avg_daily_pnl)
            total_pnl += avg_daily_pnl

        # Compute metrics
        returns_arr = np.array(daily_returns)
        if len(returns_arr) > 1:
            mean = returns_arr.mean()
            std = returns_arr.std(ddof=1) + 1e-6
            sharpe = (mean / std) * np.sqrt(252)
        else:
            sharpe = 0.0

        stats = {
            "sharpe": float(sharpe),
            "total_return": float(total_pnl),
            "period_days": len(daily_returns)
        }
        
        logger.info(f"✅ Backtest complete | Sharpe={sharpe:.4f} | R={total_pnl:.2%}")
        return stats
    
from typing import Any # Fix for circular import if needed
