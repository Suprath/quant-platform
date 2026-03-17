import os
import aiohttp
import logging
from typing import Dict, Optional
from kira_shared.models.market import FeatureVector

logger = logging.getLogger("TILClients")

class NoiseFilterClient:
    def __init__(self):
        self.base_url = os.getenv("NOISE_FILTER_URL", "http://noise_filter:8000")
        self.backtest_mode = os.getenv("TIL_BACKTEST_MODE", "false").lower() == "true"

    async def get_confidence(self, symbol: str) -> float:
        if self.backtest_mode:
            # Consistent mock confidence for backtest validation
            return 0.85
            
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(f"{self.base_url}/confidence/{symbol}") as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        return data.get("confidence", 0.0)
                    return 0.0
        except Exception as e:
            logger.error(f"Error fetching confidence from Noise Filter for {symbol}: {e}")
            return 0.0

class PositionSizerClient:
    def __init__(self):
        self.base_url = os.getenv("POSITION_SIZER_URL", "http://position_sizer:8000")
        self.backtest_mode = os.getenv("TIL_BACKTEST_MODE", "false").lower() == "true"

    async def get_size(self, symbol: str, entry_price: float, confidence: float, current_equity: float, 
                      strategy_id: str = "default", signal_type: str = "long", direction: str = "BUY",
                      timestamp: Optional[str] = None) -> Dict:
        if self.backtest_mode:
            # Returns a realistic position size based on current equity for testing
            risk_per_trade = current_equity * 0.02 # 2% risk
            shares = int(risk_per_trade / entry_price) if entry_price > 0 else 0
            return {
                "shares": max(1, shares), 
                "approved": True, 
                "reason": "Backtest Mock Approval",
                "risk_amount": risk_per_trade
            }

        payload = {
            "request_id": f"til_{symbol}_{int(os.getpid())}",
            "symbol": symbol,
            "strategy_id": strategy_id,
            "signal_type": signal_type,
            "direction": direction,
            "entry_price": entry_price,
            "confidence_score": confidence,
            "current_equity": current_equity,
            "timestamp": timestamp
        }
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(f"{self.base_url}/size", json=payload) as resp:
                    if resp.status == 200:
                        return await resp.json()
                    return {"shares": 0, "approved": False, "reason": "Sizer Request Failed"}
        except Exception as e:
            logger.error(f"Error fetching position size for {symbol}: {e}")
            return {"shares": 0, "approved": False, "reason": str(e)}
