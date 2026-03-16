import json
import logging
from typing import Optional, Dict
from datetime import datetime
from kira_shared.redis.client import RedisClient
from kira_shared import timesync
from .models import PortfolioState, Position, TradeApprovalRequest, TradeApprovalResponse
from .heat_manager import HeatManager
from .factor_exposure import FactorManager
import psycopg2
import os

logger = logging.getLogger("PortfolioEngine")

class PortfolioEngine:
    """
    Main Orchestrator for the KIRA Portfolio Engine.
    Exposes logic for real-time equity tracking and trade validation.
    """
    
    REDIS_KEY_STATE = "til:pe:portfolio_state"
    REDIS_KEY_HEAT = "til:pe:heat:current"
    REDIS_KEY_FACTORS = "til:pe:factor_exposure:current"

    def __init__(self, redis_host: str = "localhost", initial_capital: float = 100000.0):
        self.redis = RedisClient(host=redis_host, port=6379)
        self.pg_host = os.getenv("POSTGRES_HOST", "postgres_metadata")
        self.heat_manager = HeatManager()
        self.factor_manager = FactorManager()
        self.initial_capital = initial_capital
        self._state: Optional[PortfolioState] = None

    async def get_state(self) -> PortfolioState:
        """Fetch current state from Redis or return default."""
        cached = await self.redis.get(self.REDIS_KEY_STATE)
        if cached:
            try:
                self._state = PortfolioState.parse_raw(cached)
            except Exception as e:
                logger.error(f"Failed to parse portfolio state: {e}")
                
        if not self._state:
            self._state = PortfolioState(
                total_equity=self.initial_capital,
                cash=self.initial_capital,
                used_margin=0.0
            )
        return self._state

    async def save_state(self):
        """Persist state to Redis."""
        if self._state:
            # Update metrics before saving
            self.heat_manager.calculate_heat(self._state)
            self.factor_manager.calculate_exposures(self._state)
            
            state_json = self._state.json()
            await self.redis.set(self.REDIS_KEY_STATE, state_json)
            await self.redis.set(self.REDIS_KEY_HEAT, str(self._state.total_heat_pct))
            await self.redis.set(self.REDIS_KEY_FACTORS, json.dumps(self._state.factor_exposure))

    async def validate_signal(self, request: TradeApprovalRequest) -> TradeApprovalResponse:
        """
        Main entry point for Signal Generator to check if a trade is allowed.
        """
        state = await self.get_state()
        
        # 1. Calc Risk Amount
        risk_amount = (request.entry_price - request.stop_loss) * request.qty
        trade_value = request.qty * request.entry_price
        
        # 2. Check Heat
        heat_ok, heat_msg = self.heat_manager.validate_trade_risk(state, risk_amount)
        if not heat_ok:
            return TradeApprovalResponse(approved=False, reason=heat_msg, max_qty_allowed=0, adjusted_qty=0)
            
        # 3. Check Sector
        sector_ok, sector_msg = self.factor_manager.validate_sector_limit(state, request.sector, trade_value)
        if not sector_ok:
            return TradeApprovalResponse(approved=False, reason=sector_msg, max_qty_allowed=0, adjusted_qty=0)
            
        # 4. Check Margin
        if trade_value > state.cash:
            return TradeApprovalResponse(approved=False, reason="Insufficient Cash", max_qty_allowed=int(state.cash / request.entry_price), adjusted_qty=0)

        return TradeApprovalResponse(
            approved=True, 
            reason="Approved", 
            max_qty_allowed=request.qty, 
            adjusted_qty=request.qty,
            risk_metrics_post_trade={
                "projected_heat": state.total_heat_pct + (risk_amount / state.total_equity * 100)
            }
        )

    async def update_position(self, symbol: str, qty: int, price: float, sector: str, direction: str = "LONG"):
        """Update portfolio state after a trade execution (called by Execution Layer)."""
        state = await self.get_state()
        
        # Logic to add/update position
        existing = next((p for p in state.open_positions if p.symbol == symbol), None)
        
        if existing:
            # Simple handling for adding to position (average price logic can be added later)
            total_qty = existing.qty + qty
            if total_qty == 0:
                state.open_positions = [p for p in state.open_positions if p.symbol != symbol]
            else:
                existing.qty = total_qty
                existing.current_price = price
        else:
            if qty > 0:
                # Default risk_at_risk for existing positions (could be improved)
                state.open_positions.append(Position(
                    symbol=symbol,
                    direction=direction,
                    qty=qty,
                    entry_price=price,
                    current_price=price,
                    market_value=qty * price,
                    risk_at_risk=price * 0.02, # 2% default if not known
                    sector=sector
                ))
        
        # Update cash (simplified)
        state.cash -= (qty * price)
        await self.save_state()
        await self.take_snapshot()

    async def take_snapshot(self):
        """Save a historical snapshot of portfolio metrics to PostgreSQL."""
        state = await self.get_state()
        try:
            conn = psycopg2.connect(
                host=self.pg_host, 
                port=5432, 
                user="admin", 
                password="password123", 
                database="quant_platform"
            )
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO portfolio_snapshots (
                    snapshot_time, heat_pct, factor_banking, factor_it, 
                    factor_energy, factor_fmcg, open_positions_count, full_json
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                timesync.now_ist(),
                state.total_heat_pct,
                state.factor_exposure.get("BANKING", 0.0),
                state.factor_exposure.get("IT", 0.0),
                state.factor_exposure.get("ENERGY", 0.0),
                state.factor_exposure.get("FMCG", 0.0),
                len(state.open_positions),
                state.json()
            ))
            conn.commit()
            cur.close()
            conn.close()
            logger.info("📸 Portfolio snapshot saved to PostgreSQL")
        except Exception as e:
            logger.error(f"Failed to save portfolio snapshot: {e}")
