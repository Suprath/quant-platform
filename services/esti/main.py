"""
ESTI Hedge Fund — FastAPI Entry Point

Exposes REST API for controlling and monitoring the ESTI training system.
Consumes data exclusively via the existing API gateway.
"""

import os
import sys

# Ensure the esti package root is on the path
sys.path.insert(0, os.path.dirname(__file__))

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List

from training.trainer import Trainer
from utils.persistence import list_checkpoints, get_latest_checkpoint
from config import setup_logger, DEFAULT_SYMBOLS, SYMBOL_NAMES

logger = setup_logger("esti.main")

# ──────────────────────────────────────────────────
#  FastAPI App
# ──────────────────────────────────────────────────

app = FastAPI(
    title="ESTI Hedge Fund",
    description="Evolutionary Survival Trading Intelligence — AI Trading System",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global trainer instance
trainer = Trainer()

logger.info("=" * 70)
logger.info("🌌 ESTI Hedge Fund Service Starting")
logger.info("=" * 70)


# ──────────────────────────────────────────────────
#  Request Models
# ──────────────────────────────────────────────────

class TrainRequest(BaseModel):
    population_size: int = 30
    initial_capital: float = 100000.0
    symbols: Optional[List[str]] = None
    epochs: int = 100
    steps_per_epoch: int = 252
    start_date: str = "2024-01-01"
    end_date: str = "2025-01-01"
    timeframe: str = "1d"


# ──────────────────────────────────────────────────
#  Health & Info
# ──────────────────────────────────────────────────

@app.get("/")
def health():
    return {
        "service": "esti-hedge-fund",
        "status": "online",
        "training": trainer.is_running(),
        "version": "1.0.0",
    }


@app.get("/info")
def info():
    return {
        "service": "ESTI Hedge Fund",
        "theory": "Evolutionary Survival Trading Intelligence",
        "components": [
            "GodAgent (orchestrator)",
            "SharedBrain (collective intelligence)",
            "ESTIPolicy (individual agents)",
            "KnowledgeArchive (learning from dead)",
            "SurvivalEngine (capital/health/growth)",
            "SharpeOptimizer (fitness metric)",
            "CircuitBreakers (risk management)",
        ],
        "data_source": "API Gateway (http://api_gateway:8000)",
        "available_symbols": {k: v for k, v in SYMBOL_NAMES.items()},
    }


# ──────────────────────────────────────────────────
#  Training Control
# ──────────────────────────────────────────────────

@app.post("/train/start")
def start_training(request: TrainRequest):
    """Start ESTI training with the given configuration."""
    logger.info(
        f"📨 POST /train/start | epochs={request.epochs} "
        f"| pop={request.population_size} | {request.start_date}→{request.end_date}"
    )
    result = trainer.start(
        population_size=request.population_size,
        initial_capital=request.initial_capital,
        symbols=request.symbols,
        epochs=request.epochs,
        steps_per_epoch=request.steps_per_epoch,
        start_date=request.start_date,
        end_date=request.end_date,
        timeframe=request.timeframe,
    )
    return result


@app.post("/train/stop")
def stop_training():
    """Stop training gracefully."""
    logger.info("📨 POST /train/stop")
    return trainer.stop()


@app.get("/train/status")
def training_status():
    """Get detailed training status including population, survival, and brain metrics."""
    return trainer.get_status()


# ──────────────────────────────────────────────────
#  Agent Monitoring
# ──────────────────────────────────────────────────

@app.get("/agents")
def list_agents():
    """List all agents with their current state."""
    agents = trainer.get_agents()
    alive = sum(1 for a in agents if a["alive"])
    return {
        "total": len(agents),
        "alive": alive,
        "dead": len(agents) - alive,
        "agents": agents,
    }


@app.get("/agents/best")
def best_agent():
    """Get the best performing agent by Sharpe ratio."""
    best = trainer.get_best_agent()
    if not best:
        raise HTTPException(status_code=404, detail="No agents available")
    return best


# ──────────────────────────────────────────────────
#  Knowledge Archive
# ──────────────────────────────────────────────────

@app.get("/archive")
def archive_stats():
    """Get knowledge archive statistics."""
    if trainer.god_agent:
        return trainer.god_agent.archive.get_summary()
    return {"total_extinct": 0, "message": "No training session active"}


# ──────────────────────────────────────────────────
#  Checkpoints
# ──────────────────────────────────────────────────

@app.get("/checkpoints")
def get_checkpoints():
    """List available checkpoints."""
    return {
        "checkpoints": list_checkpoints(),
        "latest": get_latest_checkpoint(),
    }


from fastapi.responses import StreamingResponse
import asyncio

# ──────────────────────────────────────────────────
#  Walk-Forward Control
# ──────────────────────────────────────────────────

class WalkForwardRequest(BaseModel):
    start_date: str = "2024-01-01"
    end_date: str = "2025-01-01"
    symbols: Optional[List[str]] = None
    population_size: int = 30
    initial_capital: float = 100000.0
    train_window_days: int = 60
    test_window_days: int = 20

@app.post("/train/walk-forward")
def start_walk_forward(request: WalkForwardRequest):
    """Start infinite walk-forward training."""
    if not trainer.god_agent:
        trainer.god_agent = trainer._get_god_agent()
        
    logger.info(f"📨 POST /train/walk-forward | {request.start_date}→{request.end_date}")
    
    return trainer.god_agent.start_walk_forward(
        start_date=request.start_date,
        end_date=request.end_date,
        symbols=request.symbols,
        population_size=request.population_size,
        initial_capital=request.initial_capital,
        train_window_days=request.train_window_days,
        test_window_days=request.test_window_days
    )

@app.get("/metrics/history")
def get_metrics_history(limit: int = 1000):
    """Get historical metrics for charting."""
    if trainer.god_agent and hasattr(trainer.god_agent, 'metrics_store'):
        return {
            "history": trainer.god_agent.metrics_store.get_history(limit),
            "cycles": trainer.god_agent.metrics_store.get_cycles()
        }
    return {"history": [], "cycles": []}

@app.get("/metrics/stream")
async def stream_metrics():
    """SSE endpoint for live metrics."""
    if not trainer.god_agent or not hasattr(trainer.god_agent, 'metrics_store'):
        # Return empty stream if not ready
        async def empty():
             yield ": ping\n\n"
        return StreamingResponse(empty(), media_type="text/event-stream")

    return StreamingResponse(
        trainer.god_agent.metrics_store.stream(),
        media_type="text/event-stream"
    )

@app.on_event("shutdown")
def shutdown_event():
    logger.info("🛑 Received shutdown signal. Cleaning up...")
    trainer.stop()
    if trainer.god_agent and hasattr(trainer.god_agent, 'metrics_store'):
        # Push a sentinel/cancel to all subscribers to break the SSE generator
        store = trainer.god_agent.metrics_store
        with store._lock:
            for q in store._subscribers:
                q.put_nowait({"type": "shutdown"})

# ──────────────────────────────────────────────────
#  Entry Point
# ──────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    logger.info("🚀 Starting ESTI service on port 8002")
    uvicorn.run(app, host="0.0.0.0", port=8002)
