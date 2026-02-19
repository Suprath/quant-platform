"""
Metrics — Performance Tracking and Aggregation
"""

import time
import json
import os
from config import setup_logger, CHECKPOINT_DIR

logger = setup_logger("esti.utils.metrics")


class MetricsTracker:
    """
    Collects and persists training metrics for monitoring and analysis.
    """

    def __init__(self):
        self.metrics_log: list[dict] = []
        self._start_time = time.time()

    def record(self, step: int, epoch: int, data: dict):
        """Record a metrics snapshot."""
        entry = {
            "step": step,
            "epoch": epoch,
            "elapsed_seconds": round(time.time() - self._start_time, 1),
            **data,
        }
        self.metrics_log.append(entry)

        if len(self.metrics_log) % 100 == 0:
            logger.debug(f"📊 Metrics recorded: {len(self.metrics_log)} entries")

    def save(self, filename: str = "training_metrics.json"):
        """Save all metrics to disk."""
        os.makedirs(CHECKPOINT_DIR, exist_ok=True)
        path = os.path.join(CHECKPOINT_DIR, filename)

        with open(path, "w") as f:
            json.dump(self.metrics_log, f, indent=2, default=str)

        logger.info(f"💾 Metrics saved: {path} ({len(self.metrics_log)} entries)")

    def get_recent(self, n: int = 50) -> list[dict]:
        """Return the most recent N metrics entries."""
        return self.metrics_log[-n:]
