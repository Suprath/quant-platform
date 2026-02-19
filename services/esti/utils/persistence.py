"""
Persistence — Checkpoint Save/Load Utilities
"""

import os
import torch
from config import setup_logger, CHECKPOINT_DIR

logger = setup_logger("esti.utils.persistence")


def list_checkpoints() -> list[dict]:
    """List available checkpoints."""
    if not os.path.exists(CHECKPOINT_DIR):
        return []

    checkpoints = []
    for f in sorted(os.listdir(CHECKPOINT_DIR)):
        if f.endswith(".pt"):
            path = os.path.join(CHECKPOINT_DIR, f)
            size_mb = os.path.getsize(path) / (1024 * 1024)
            checkpoints.append({
                "filename": f,
                "path": path,
                "size_mb": round(size_mb, 2),
                "modified": os.path.getmtime(path),
            })
            logger.debug(f"Found checkpoint: {f} ({size_mb:.1f} MB)")

    return checkpoints


def get_latest_checkpoint() -> str | None:
    """Return path to the most recent checkpoint."""
    checkpoints = list_checkpoints()
    if not checkpoints:
        return None
    latest = max(checkpoints, key=lambda c: c["modified"])
    return latest["path"]
