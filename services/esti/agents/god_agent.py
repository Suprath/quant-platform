"""
GodAgent — Supreme Controller for the ESTI Ecosystem

Orchestrates:
    - Data pipeline management
    - Training epochs
    - Evolutionary selection & mutation
    - Sharpe ratio optimization
    - Risk management & circuit breakers
    - Checkpoint persistence
"""

import os
import time
import asyncio
import torch
import numpy as np
from typing import Optional, List

from core.shared_brain import SharedBrain
from core.knowledge_archive import KnowledgeArchive
from core.survival_engine import SurvivalEngine, AgentState
from agents.population_manager import PopulationManager
from training.sharpe_optimizer import SharpeOptimizer
from risk.circuit_breakers import CircuitBreakers
from risk.position_sizing import PositionSizer
from data.data_pipeline import DataPipeline
from data.feature_engineering import FeatureEngineering
from config import (
    setup_logger,
    POPULATION_SIZE,
    INITIAL_CAPITAL,
    BRAIN_DIM,
    STATE_DIM,
    EVOLUTION_INTERVAL,
    CHECKPOINT_INTERVAL,
    CHECKPOINT_DIR,
    DEFAULT_SYMBOLS,
    SYMBOL_NAMES,
    DEVICE,
)

logger = setup_logger("esti.agents.god_agent")


class GodAgent:
    """
    Supreme controller that orchestrates training, data routing,
    and Sharpe ratio maximisation across the ESTI population.
    """

    def __init__(
        self,
        population_size: int = POPULATION_SIZE,
        initial_capital: float = INITIAL_CAPITAL,
        symbols: list[str] = None,
    ):
        self.symbols = symbols or DEFAULT_SYMBOLS

        logger.info("=" * 70)
        logger.info("🌌 GOD AGENT CONTROLLER — ESTI Hedge Fund System")
        logger.info("=" * 70)
        logger.info(
            f"Population: {population_size} | Capital: ₹{initial_capital:,.0f} "
            f"| Symbols: {len(self.symbols)} | Device: {DEVICE}"
        )

        # ── Core components ──
        self.archive = KnowledgeArchive()
        self.brain = SharedBrain(brain_dim=BRAIN_DIM).to(DEVICE)
        self.survival = SurvivalEngine(initial_capital=initial_capital)
        self.population = PopulationManager(
            population_size=population_size,
            initial_capital=initial_capital,
            archive=self.archive,
        )
        self.sharpe = SharpeOptimizer()
        self.circuit_breakers = CircuitBreakers()
        self.position_sizer = PositionSizer()

        # ── Data pipeline ──
        self.data_pipeline = DataPipeline()
        self.feature_eng = FeatureEngineering(state_dim=STATE_DIM)

        # ── State ──
        self.current_epoch = 0
        self.total_steps = 0
        self.is_training = False
        self._training_start_time = None
        self._brain_state = torch.zeros(BRAIN_DIM).to(DEVICE)

        # Training data cache
        self._training_data = {}
        self._feature_cache = {}

        logger.info("✅ GodAgent fully initialised")

    # ──────────────────────────────────────────────
    #  Training orchestration
    # ──────────────────────────────────────────────

    def train(
        self,
        epochs: int = 100,
        steps_per_epoch: int = 252,
        start_date: str = "2024-01-01",
        end_date: str = "2025-01-01",
        timeframe: str = "1d",
    ):
        """
        Main training entry point.

        Phase 1: Fetch & prepare data
        Phase 2: Initialize population
        Phase 3: Run training epochs
        Phase 4: Evaluate and export
        """
        self.is_training = True
        self._training_start_time = time.time()

        logger.info("=" * 70)
        logger.info(
            f"🚀 TRAINING START | epochs={epochs} | steps_per_epoch={steps_per_epoch} "
            f"| data={start_date}→{end_date} | tf={timeframe}"
        )
        logger.info("=" * 70)

        try:
            # Phase 1: Data
            self._prepare_training_data(start_date, end_date, timeframe)

            # Phase 2: Population
            self.population.initialize_population()

            # Phase 3: Training loop
            for epoch in range(1, epochs + 1):
                self.current_epoch = epoch
                self._run_epoch(epoch, steps_per_epoch)

                if not self.is_training:
                    logger.warning("⛔ Training stopped by external signal")
                    break

            # Phase 4: Final evaluation
            self._final_evaluation()

        except Exception as e:
            logger.error(f"❌ TRAINING FAILED: {type(e).__name__}: {e}", exc_info=True)
            raise
        finally:
            self.is_training = False
            elapsed = time.time() - self._training_start_time
            logger.info(
                f"🏁 Training session ended | duration={elapsed:.1f}s "
                f"| epochs_completed={self.current_epoch} "
                f"| total_steps={self.total_steps}"
            )

    def stop(self):
        """Signal the training loop to stop gracefully."""
        logger.info("⛔ Stop signal received")
        self.is_training = False

    # ──────────────────────────────────────────────
    #  Phase 1: Data preparation
    # ──────────────────────────────────────────────

    def _prepare_training_data(self, start_date: str, end_date: str, timeframe: str):
        """Fetch OHLC data and pre-compute features."""
        logger.info(f"📊 Phase 1: Preparing training data...")

        raw_data = self.data_pipeline.fetch_training_data(
            symbols=self.symbols,
            start_date=start_date,
            end_date=end_date,
            timeframe=timeframe,
        )

        if not raw_data:
            logger.error(
                "❌ No training data available! "
                "Ensure data has been backfilled via: POST /api/v1/backfill/start"
            )
            raise RuntimeError("No training data available from API gateway")

        # Pre-compute features
        for symbol, df in raw_data.items():
            name = SYMBOL_NAMES.get(symbol, symbol)
            features_df = self.feature_eng.compute_features(df)
            if len(features_df) > 0:
                self._training_data[symbol] = features_df
                self._feature_cache[symbol] = self.feature_eng.get_all_state_vectors(features_df)
                logger.info(
                    f"    ✅ {name}: {len(features_df)} timesteps ready, "
                    f"state_dim={self._feature_cache[symbol].shape[1]}"
                )
            else:
                logger.warning(f"    ⚠️  {name}: no usable data after feature computation")

        logger.info(
            f"✅ Training data ready | {len(self._training_data)} symbols | "
            f"total timesteps: {sum(len(df) for df in self._training_data.values()):,}"
        )

    # ──────────────────────────────────────────────
    #  Phase 3: Training epoch
    # ──────────────────────────────────────────────

    def _run_epoch(self, epoch: int, max_steps: int):
        """Run one training epoch across all available data."""
        epoch_start = time.time()

        # Select a random symbol for this epoch (data diversification)
        symbols = list(self._feature_cache.keys())
        if not symbols:
            logger.error("No training data in cache — skipping epoch")
            return

        symbol = symbols[epoch % len(symbols)]
        states = self._feature_cache[symbol]
        feature_df = self._training_data[symbol]
        name = SYMBOL_NAMES.get(symbol, symbol)

        steps = min(max_steps, len(states) - 1)
        if steps <= 0:
            logger.warning(f"⚠️  Not enough data for {name} — skipping epoch")
            return

        logger.info(
            f"📈 Epoch {epoch} | symbol={name} | steps={steps} "
            f"| alive={self.population.alive_count()}"
        )

        epoch_returns = {i: [] for i in range(len(self.population.agents))}

        for step_idx in range(steps):
            self.total_steps += 1

            # Get market state
            state_vec = torch.tensor(states[step_idx], dtype=torch.float32).to(DEVICE)

            # Actual market return for this timestep
            actual_return = float(feature_df.iloc[step_idx]["returns"]) if step_idx > 0 else 0.0

            # Each alive agent makes a decision
            alive_pairs = self.population.get_alive()
            per_agent_returns = []

            for policy, agent_state in alive_pairs:
                if not agent_state.alive:
                    per_agent_returns.append(0.0)
                    continue

                # Get trading decision
                with torch.no_grad():
                    decision = policy(state_vec, self._brain_state)

                direction = decision["direction"]  # 0=Long, 1=Short, 2=Hold
                raw_size = decision["position_size"]
                uncertainty = decision["uncertainty"]

                # Position sizing with risk management
                volatility = float(feature_df.iloc[step_idx].get("volatility_20", 0.02))
                position_size = self.position_sizer.calculate_size(
                    raw_size, uncertainty, volatility
                )
                position_size = self.circuit_breakers.check_position_size(position_size)

                # Calculate agent return based on decision
                if direction == 0:    # Long
                    agent_return = actual_return * position_size
                elif direction == 1:  # Short
                    agent_return = -actual_return * position_size
                else:                 # Hold
                    agent_return = 0.0

                per_agent_returns.append(agent_return)
                epoch_returns[agent_state.agent_id] = agent_state.return_history

            # Survival step
            all_returns = []
            for agent_state in self.population.agents:
                if agent_state.alive:
                    idx = next(
                        (i for i, (_, s) in enumerate(alive_pairs) if s.agent_id == agent_state.agent_id),
                        None,
                    )
                    all_returns.append(per_agent_returns[idx] if idx is not None else 0.0)
                else:
                    all_returns.append(0.0)

            extinct = self.survival.step(self.population.agents, all_returns)

            # Handle extinctions
            if extinct:
                fitness = self.sharpe.get_fitness_scores(
                    [a.return_history for a in self.population.agents]
                )
                self.population.handle_extinctions(
                    extinct, self._brain_state, fitness, self.total_steps
                )

            # Check circuit breakers
            alive_count = self.population.alive_count()
            if self.circuit_breakers.check_population(alive_count):
                self.population.emergency_repopulate(self.total_steps)
                self.circuit_breakers.reset_trips()

            # Evolutionary step (every N steps)
            if self.total_steps % EVOLUTION_INTERVAL == 0:
                self._evolutionary_step()

            # Checkpoint (every M steps)
            if self.total_steps % CHECKPOINT_INTERVAL == 0:
                self._save_checkpoint()

        # Epoch summary
        elapsed = time.time() - epoch_start
        stats = self.survival.get_population_stats(self.population.agents)
        logger.info(
            f"📊 Epoch {epoch} complete | {elapsed:.1f}s | {name} | "
            f"alive={stats['alive_count']} | "
            f"avg_capital=₹{stats.get('avg_capital', 0):,.0f} | "
            f"avg_health={stats.get('avg_health', 0):.3f} | "
            f"avg_Σ={stats.get('avg_survival_score', 0):.4f}"
        )

    # ──────────────────────────────────────────────
    #  Evolutionary step
    # ──────────────────────────────────────────────

    def _evolutionary_step(self):
        """Run evolutionary selection and update shared brain."""
        logger.info(f"🧬 Evolutionary step at timestep {self.total_steps}")

        # Calculate Sharpe for all alive agents
        alive_pairs = self.population.get_alive()
        fitness = self.sharpe.get_fitness_scores(
            [s.return_history for _, s in alive_pairs]
        )

        # Update agent Sharpe values
        for (_, agent_state), sharpe_val in zip(alive_pairs, fitness):
            agent_state.sharpe = sharpe_val

        # Rank for logging
        self.sharpe.rank_by_sharpe([s.return_history for _, s in alive_pairs])

        # Update shared brain
        alive_embeds = []
        for policy, agent_state in alive_pairs:
            dummy_state = torch.zeros(STATE_DIM).to(DEVICE)
            embed = policy.get_embedding(dummy_state)
            alive_embeds.append(embed)

        dead_embeds = self.archive.get_dead_embeddings()
        self._brain_state = self.brain.update_from_population(alive_embeds, dead_embeds)

    # ──────────────────────────────────────────────
    #  Checkpointing
    # ──────────────────────────────────────────────

    def _save_checkpoint(self):
        """Save population state and brain."""
        os.makedirs(CHECKPOINT_DIR, exist_ok=True)
        path = os.path.join(CHECKPOINT_DIR, f"checkpoint_step_{self.total_steps}.pt")

        checkpoint = {
            "total_steps": self.total_steps,
            "current_epoch": self.current_epoch,
            "brain_state_dict": self.brain.state_dict(),
            "brain_state": self._brain_state,
            "population_stats": self.population.get_stats(),
        }

        torch.save(checkpoint, path)
        logger.info(f"💾 Checkpoint saved: {path}")

    def load_checkpoint(self, path: str):
        """Resume from a checkpoint."""
        checkpoint = torch.load(path, map_location=DEVICE)
        self.total_steps = checkpoint["total_steps"]
        self.current_epoch = checkpoint["current_epoch"]
        self.brain.load_state_dict(checkpoint["brain_state_dict"])
        self._brain_state = checkpoint["brain_state"]
        logger.info(
            f"📂 Checkpoint loaded: {path} | "
            f"step={self.total_steps} | epoch={self.current_epoch}"
        )

    # ──────────────────────────────────────────────
    #  Final evaluation
    # ──────────────────────────────────────────────

    def _final_evaluation(self):
        """Phase 4: Evaluate the population and identify best strategies."""
        logger.info("=" * 70)
        logger.info("📊 FINAL EVALUATION")
        logger.info("=" * 70)

        alive_pairs = self.population.get_alive()
        if not alive_pairs:
            logger.warning("⚠️  No alive agents at end of training!")
            return

        rankings = self.sharpe.rank_by_sharpe([s.return_history for _, s in alive_pairs])

        logger.info(f"🏆 Top 5 agents by Sharpe ratio:")
        for rank, (idx, sharpe_val) in enumerate(rankings[:5], 1):
            _, agent_state = alive_pairs[idx]
            logger.info(
                f"    #{rank} Agent-{agent_state.agent_id:03d} | "
                f"Sharpe={sharpe_val:.4f} | "
                f"Capital=₹{agent_state.capital:,.0f} | "
                f"Health={agent_state.health:.3f}"
            )

        self._save_checkpoint()
        logger.info("✅ Final checkpoint saved")

    # ──────────────────────────────────────────────
    #  Continuous Walk-Forward Training
    # ──────────────────────────────────────────────

    def start_walk_forward(
        self,
        start_date: str,
        end_date: str,
        symbols: List[str] = None,
        population_size: int = POPULATION_SIZE,
        initial_capital: float = INITIAL_CAPITAL,
        train_window_days: int = 60,
        test_window_days: int = 20,
    ):
        """
        Start infinite walk-forward training loop.
        """
        if self.is_training:
            logger.warning("⚠️ Training already in progress")
            return

        self.symbols = symbols or self.symbols
        self.is_training = True
        
        # Initialize components locally to avoid circular imports at top level if possible
        # or rely on imports already present
        from training.walk_forward import WalkForwardEngine
        from utils.metrics_store import MetricsStore

        if not hasattr(self, 'metrics_store'):
            self.metrics_store = MetricsStore()
            
        self.wf_engine = WalkForwardEngine(
            god_agent=self,
            metrics_store=self.metrics_store,
            train_window_days=train_window_days,
            test_window_days=test_window_days
        )

        import threading
        def _run_loop():
            try:
                asyncio.run(self.wf_engine.run_forever(
                    start_date=start_date,
                    end_date=end_date,
                    symbols=self.symbols,
                    population_size=population_size,
                    initial_capital=initial_capital
                ))
            except Exception as e:
                logger.error(f"❌ Walk-forward thread failed: {e}", exc_info=True)
            finally:
                self.is_training = False

        self.wf_thread = threading.Thread(target=_run_loop, daemon=True)
        self.wf_thread.start()
        
        return {"status": "started", "mode": "walk-forward"}

    def stop_walk_forward(self):
        """Stop the infinite loop."""
        if hasattr(self, 'wf_engine'):
            self.wf_engine.stop()
        self.is_training = False
        logger.info("⛔ Walk-forward stop signal sent")

    # ──────────────────────────────────────────────
    #  API endpoints support
    # ──────────────────────────────────────────────

    def get_best_agent(self) -> Optional[dict]:
        """Return the best agent's info for API response."""
        alive_pairs = self.population.get_alive()
        if not alive_pairs:
            return None

        rankings = self.sharpe.rank_by_sharpe([s.return_history for _, s in alive_pairs])
        if not rankings:
            return None

        best_idx, best_sharpe = rankings[0]
        _, best_state = alive_pairs[best_idx]

        return {
            "agent_id": best_state.agent_id,
            "sharpe": best_sharpe,
            "capital": round(best_state.capital, 2),
            "health": round(best_state.health, 4),
            "growth": round(best_state.growth, 6),
            "survival_score": round(best_state.survival_score, 4),
            "lifetime_steps": best_state.current_step - best_state.birth_step,
        }

    def get_training_status(self) -> dict:
        """Return current training status for API."""
        pop_stats = self.population.get_stats()
        survival_stats = self.survival.get_population_stats(self.population.agents)

        elapsed = 0
        if self._training_start_time:
            elapsed = round(time.time() - self._training_start_time, 1)
        
        # Check if MetricsStore exists (walk-forward mode)
        metrics = {}
        if hasattr(self, 'metrics_store'):
            metrics = {
                "history_len": len(self.metrics_store.history),
                "current_cycle": self.metrics_store.current_cycle
            }

        return {
            "is_training": self.is_training,
            "current_epoch": self.current_epoch,
            "total_steps": self.total_steps,
            "elapsed_seconds": elapsed,
            "population": pop_stats,
            "survival": survival_stats,
            "archive": self.archive.get_summary(),
            "circuit_breakers": self.circuit_breakers.get_status(),
            "brain": self.brain.get_state_summary(),
            "data_cache": self.data_pipeline.get_cache_stats(),
            "metrics": metrics
        }

    def get_all_agents(self) -> list[dict]:
        """Return info for all agents (alive and dead)."""
        agents = []
        for policy, state in zip(self.population.policies, self.population.agents):
            agents.append({
                "agent_id": state.agent_id,
                "alive": state.alive,
                "capital": round(state.capital, 2),
                "health": round(state.health, 4),
                "growth": round(state.growth, 6),
                "rank": round(state.rank, 4),
                "survival_score": round(state.survival_score, 4),
                "sharpe": round(state.sharpe, 4),
                "death_cause": state.death_cause,
                "lifetime": state.current_step - state.birth_step,
            })
        return agents
