import os
import logging
from typing import Dict, List
from fastapi import FastAPI, HTTPException
from .portfolio_engine.engine import PortfolioEngine
from .portfolio_engine.models import TradeApprovalRequest, TradeApprovalResponse, PortfolioState
from .signal_generator.scanner import UniverseScanner
from .signal_generator.strategies.momentum_continuation import MomentumContinuationStrategy
from .signal_generator.strategies.accumulation_breakout import AccumulationBreakoutStrategy
from .mechanism_classifier.classifier import MechanismClassifier
from .learning_loop.trade_recorder import TradeRecorder
from kira_shared.logging.setup import setup_logging
from kira_shared.models.market import FeatureVector, MarketContext
from kira_shared import timesync

setup_logging()
logger = logging.getLogger("KIRA-TIL")

app = FastAPI(title="KIRA Trading Intelligence Layer")

REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
INITIAL_CAPITAL = float(os.getenv("INITIAL_CAPITAL", "100000.0"))

# Initialize Components
portfolio_engine = PortfolioEngine(redis_host=REDIS_HOST, initial_capital=INITIAL_CAPITAL)
mechanism_classifier = MechanismClassifier()
trade_recorder = TradeRecorder()
scanner = UniverseScanner(strategies=[
    MomentumContinuationStrategy(),
    AccumulationBreakoutStrategy()
])

@app.get("/health")
async def health():
    return {
        "status": "healthy", 
        "service": "kira-til",
        "components": ["portfolio_engine", "mechanism_classifier", "signal_generator", "learning_loop"]
    }

# --- Signal Generator Endpoints ---

@app.post("/scan")
async def run_market_scan(features_batch: Dict[str, FeatureVector]):
    """Runs a full market scan and returns raw signals."""
    try:
        signals = await scanner.scan(features_batch)
        return {"signals_found": len(signals), "signals": [s.to_dict() for s in signals]}
    except Exception as e:
        logger.error(f"Error during scan: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# --- Integrated Pipeline Endpoint ---

@app.post("/process_features")
async def process_market_features(features_batch: Dict[str, FeatureVector], market_context: MarketContext):
    """
    Full TIL Pipeline: 
    1. Scan for signals
    2. Classify mechanisms for found signals
    3. Validate against portfolio risk
    4. Return actionable decisions
    """
    try:
        # 1. Scan
        raw_signals = await scanner.scan(features_batch)
        
        decisions = []
        for signal in raw_signals:
            # 2. Classify
            classified = await mechanism_classifier.classify(signal, features_batch[signal.symbol], market_context)
            
            if not classified.has_mechanism:
                decisions.append({"symbol": signal.symbol, "action": "DISCARD", "reason": "No clear mechanism"})
                continue
                
            # 3. Validate Portfolio
            approval_req = TradeApprovalRequest(
                symbol=signal.symbol,
                direction=signal.direction,
                qty=100, # Placeholder qty for risk check
                entry_price=signal.entry_price_estimate,
                stop_loss=signal.stop_price_estimate,
                sector="UNKNOWN" # Would be looked up in a real environment
            )
            portfolio_check = await portfolio_engine.validate_signal(approval_req)
            
            if not portfolio_check.approved:
                decisions.append({
                    "symbol": signal.symbol, 
                    "action": "REJECT_RISK", 
                    "reason": portfolio_check.reason,
                    "thesis": classified.thesis
                })
                continue
                
            decisions.append({
                "symbol": signal.symbol,
                "action": "EXECUTE",
                "thesis": classified.thesis,
                "confidence": classified.mechanism_confidence,
                "qty": 100
            })
            
        return {"processed": len(features_batch), "decisions_count": len(decisions), "decisions": decisions}
        
    except Exception as e:
        logger.error(f"Error in integrated pipeline: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# --- Portfolio Engine Endpoints ---
# (keeping existing ones)
