"""
Trainer — Training Loop Wrapper

Provides a clean interface for starting/stopping training from the API.
Runs the GodAgent training in a background thread.
"""

import threading
import time
from typing import Optional
from agents.god_agent import GodAgent
from config import setup_logger

logger = setup_logger("esti.training.trainer")


class Trainer:
    """
    Wraps GodAgent training in a background thread for non-blocking API control.
    """

    def __init__(self):
        self.god_agent: Optional[GodAgent] = None
        self._thread: Optional[threading.Thread] = None
        self._error: Optional[str] = None

        logger.info("🎓 Trainer initialised")

    def _get_god_agent(self, population_size: int = 30, initial_capital: float = 100000.0) -> GodAgent:
        """Helper to get or create a GodAgent instance."""
        if not self.god_agent:
            self.god_agent = GodAgent(
                population_size=population_size,
                initial_capital=initial_capital,
            )
        return self.god_agent

    def start(
        self,
        population_size: int = 30,
        initial_capital: float = 100000.0,
        symbols: list[str] = None,
        epochs: int = 100,
        steps_per_epoch: int = 252,
        start_date: str = "2024-01-01",
        end_date: str = "2025-01-01",
        timeframe: str = "1d",
    ) -> dict:
        """
        Start training in a background thread.

        Returns:
            Status dict
        """
        if self._thread and self._thread.is_alive():
            logger.warning("⚠️  Training already in progress")
            return {"status": "already_running", "message": "Training is already in progress"}

        # Create a fresh GodAgent
        self.god_agent = GodAgent(
            population_size=population_size,
            initial_capital=initial_capital,
            symbols=symbols,
        )
        self._error = None

        # Run in background thread
        def _train():
            try:
                self.god_agent.train(
                    epochs=epochs,
                    steps_per_epoch=steps_per_epoch,
                    start_date=start_date,
                    end_date=end_date,
                    timeframe=timeframe,
                )
            except Exception as e:
                self._error = f"{type(e).__name__}: {e}"
                logger.error(f"❌ Training thread failed: {self._error}", exc_info=True)

        self._thread = threading.Thread(target=_train, name="esti-training", daemon=True)
        self._thread.start()

        logger.info(
            f"🚀 Training started in background | epochs={epochs} "
            f"| pop={population_size} | {start_date}→{end_date}"
        )
        return {
            "status": "started",
            "epochs": epochs,
            "population_size": population_size,
            "start_date": start_date,
            "end_date": end_date,
        }

    def stop(self) -> dict:
        """Stop training gracefully."""
        if self.god_agent:
            self.god_agent.stop()
            logger.info("⛔ Stop signal sent to GodAgent")
            return {"status": "stopping", "message": "Stop signal sent"}
        return {"status": "not_running", "message": "No training in progress"}

    def is_running(self) -> bool:
        """Check if any training thread is active."""
        # Check standard trainer thread
        if self._thread and self._thread.is_alive():
            return True
            
        # Check GodAgent's walk-forward thread
        if self.god_agent and hasattr(self.god_agent, 'wf_thread'):
            if self.god_agent.wf_thread and self.god_agent.wf_thread.is_alive():
                return True
                
        return False

    def get_status(self) -> dict:
        """Get current training status."""
        if self.god_agent:
            status = self.god_agent.get_training_status()
            status["thread_alive"] = self.is_running()
            status["error"] = self._error
            return status
        return {
            "is_training": False,
            "thread_alive": False,
            "error": self._error,
            "message": "No training session initialised",
        }

    def get_agents(self) -> list[dict]:
        if self.god_agent:
            return self.god_agent.get_all_agents()
        return []

    def get_best_agent(self) -> Optional[dict]:
        if self.god_agent:
            return self.god_agent.get_best_agent()
        return None
