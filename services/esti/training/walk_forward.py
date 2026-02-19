"""
Walk-Forward Optimization Engine — Infinite Growth Seeker

Orchestrates the continuous train -> backtest -> evolve cycle.
Implements the "Push Until Plateau" philosophy by dynamically adjusting
evolutionary pressure based on backtest performance.
"""

import time
import asyncio
import numpy as np
from typing import List, Optional, Dict
from datetime import datetime, timedelta

from config import setup_logger, SYMBOL_NAMES
from agents.god_agent import GodAgent
from training.backtester import Backtester
from training.growth_pressure import GrowthPressure
from utils.metrics_store import MetricsStore

logger = setup_logger("esti.training.walk_forward")


class WalkForwardEngine:
    """
    Orchestrates infinite walk-forward training cycles.
    """

    def __init__(
        self,
        god_agent: GodAgent,
        metrics_store: MetricsStore,
        train_window_days: int = 60,
        test_window_days: int = 20,
        slide_days: int = 20,
    ):
        self.god = god_agent
        self.metrics = metrics_store
        self.backtester = Backtester()
        self.pressure = GrowthPressure()
        
        self.train_window = timedelta(days=train_window_days)
        self.test_window = timedelta(days=test_window_days)
        self.slide_window = timedelta(days=slide_days)
        
        self.is_running = False
        self.current_start_date: Optional[datetime] = None
        self.cycle_count = 0

    async def run_forever(
        self,
        start_date: str,
        end_date: str,
        symbols: List[str],
        population_size: int = 30,
        initial_capital: float = 100000.0,
        epochs_per_cycle: int = 5,
    ):
        """
        Main infinite loop: Train -> Backtest -> Slide -> Repeat.
        """
        self.is_running = True
        self.cycle_count = 0
        self.metrics.clear()
        
        # Initial setup
        dt_start = datetime.strptime(start_date, "%Y-%m-%d")
        dt_end_limit = datetime.strptime(end_date, "%Y-%m-%d")
        self.current_start_date = dt_start
        
        # Initialize population once
        logger.info("🌱 Initializing population for continuous evolution...")
        self.god.population.initialize_population()

        logger.info(f"🚀 Starting infinite walk-forward loop | Data: {start_date} -> {end_date}")

        # Validate configuration to prevent infinite loops
        min_required_duration = self.train_window + self.test_window
        total_available_duration = dt_end_limit - dt_start
        
        if min_required_duration > total_available_duration:
            logger.error(
                f"❌ Configuration Error: Train({self.train_window.days}d) + Test({self.test_window.days}d) "
                f"requires {min_required_duration.days} days, but only {total_available_duration.days} days available."
            )
            self.is_running = False
            return
        try:
            while self.is_running:
                self.cycle_count += 1
                
                # 1. Define Windows
                train_start = self.current_start_date
                train_end = train_start + self.train_window
                test_start = train_end
                test_end = test_start + self.test_window
                
                # Check data bounds
                if test_end > dt_end_limit:
                    logger.info("🔄 Reached end of data. Looping back to start...")
                    self.current_start_date = dt_start
                    self.pressure.reset()
                    await asyncio.sleep(5)  # Back off before restarting loop
                    continue

                ts_str = train_start.strftime("%Y-%m-%d")
                te_str = train_end.strftime("%Y-%m-%d")
                test_s_str = test_start.strftime("%Y-%m-%d")
                test_e_str = test_end.strftime("%Y-%m-%d")
                
                # 2. Fetch Data (with warmup buffer)
                # indicators like vol_regime need ~80 days (rolling 20 + rolling 60)
                warmup_period = timedelta(days=90)
                fetch_start = train_start - warmup_period
                fs_str = fetch_start.strftime("%Y-%m-%d")
                
                logger.info(f"🔄 Cycle {self.cycle_count} | Range: {fs_str} (warmup) -> {test_e_str}")
                self.god._prepare_training_data(fs_str, test_e_str, "1d")
                
                # 3. Apply Growth Pressure Params
                # Look at previous cycle's backtest result to set mutation rates
                if self.cycle_count > 1:
                    prev_best_sharpe = self.pressure.best_sharpe
                    pressure_state = self.pressure.update(prev_best_sharpe)
                    
                    # Apply to God Agent
                    # TODO: Add set_evolution_params method to GodAgent
                    logger.info(f"🔥 {pressure_state.message}")

                # 4. Train (In-Sample)
                # Run N epochs on training window
                # We need a modified train method that accepts data subset
                # For now, we'll rely on GodAgent's internal data handling
                # but we'll manually control the epoch loop here to allow streaming
                
                train_metrics = await self._run_training_phase(epochs_per_cycle)
                
                # 5. Backtest (Out-of-Sample)
                # Run best agents on unseen data (test_window)
                backtest_metrics = self._run_backtest_phase(test_s_str, test_e_str)
                
                # 6. Log & Stream
                cycle_data = {
                    "cycle": self.cycle_count,
                    "train_date": ts_str,
                    "test_date": test_s_str,
                    "train_sharpe": train_metrics["best_sharpe"],
                    "test_sharpe": backtest_metrics["sharpe"],
                    "pressure_level": self.pressure.pressure_level,
                    "status": self.pressure.update(backtest_metrics["sharpe"]).status
                }
                self.metrics.log("cycle", cycle_data)
                
                # 7. Slide Forward
                # If plateaued, maybe slide faster? For now fixed slide.
                self.current_start_date += self.slide_window
                
                # 8. Check Stop Signal
                if not self.is_running:
                    break
                
                # Small pause to let frontend catch up / not burn CPU
                await asyncio.sleep(0.5)

        except Exception as e:
            logger.error(f"❌ Walk-Forward Failed: {e}", exc_info=True)
            self.is_running = False
            raise

    async def _run_training_phase(self, epochs: int) -> Dict[str, float]:
        """Run training epochs and return metrics."""
        best_train_sharpe = -999.0
        
        for epoch in range(1, epochs + 1):
            if not self.is_running: break
            
            # Run one epoch in GodAgent
            # We use a specialized method to run just one step to keep control here
            # or rely on god.train() if we modify it to be non-blocking/yield
            # For this plan, we will assume GodAgent has a `train_epoch()` method
            
            # Since GodAgent.train is blocking loop, we invoke internal _run_epoch
            # We need to make sure GodAgent state is managed correctly
            self.god.current_epoch = epoch # Reset or accumulate?
            self.god._run_epoch(epoch, 50) # 50 steps per epoch
            
            # Evolution
            if epoch % 2 == 0:
                self.god._evolutionary_step()

            # Get stats
            alive = self.god.population.get_alive()
            if alive:
                sharpes = [s.sharpe for _, s in alive]
                best = max(sharpes) if sharpes else 0.0
                best_train_sharpe = max(best_train_sharpe, best)
            
            # Stream epoch metrics
            self.metrics.log("epoch", {
                "epoch": epoch,
                "cycle": self.cycle_count,
                "best_sharpe": best_train_sharpe,
                "alive": len(alive)
            })
            
            await asyncio.sleep(0.01) # Yield to event loop
            
        return {"best_sharpe": best_train_sharpe}

    def _run_backtest_phase(self, start_date: str, end_date: str) -> Dict[str, float]:
        """Run backtest on out-of-sample data."""
        # Select elite agents (top 5)
        alive = self.god.population.get_alive()
        # Sort by Sharpe
        alive.sort(key=lambda x: x[1].sharpe, reverse=True)
        elites = alive[:5]
        
        if not elites:
            return {"sharpe": 0.0, "return": 0.0}
            
        # Run Backtester
        # Need to ensure data is loaded in GodAgent
        # We can pass god._training_data directly if pre-loaded
        
        # Note: GodAgent prepares data in Step 2 of the cycle
        # We need to filter relevant data for backtester inside Backtester.run
        
        stats = self.backtester.run(
            population=elites,
            brain_state=self.god._brain_state,
            data=self.god._training_data,
            start_date=start_date,
            end_date=end_date
        )
        
        logger.info(f"🧪 Backtest Result: Sharpe={stats['sharpe']:.4f}")
        return stats

    def stop(self):
        self.is_running = False
