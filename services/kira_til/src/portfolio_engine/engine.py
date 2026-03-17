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
        try:
            cached = await self.redis.client.get(self.REDIS_KEY_STATE)
        except Exception as e:
            logger.error(f"Redis get error: {e}")
            cached = None
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

    async def clear_state(self, timestamp: Optional[datetime] = None, initial_capital: Optional[float] = None, run_id: Optional[str] = None):
        """Reset portfolio state in Redis and memory, and initialize backtest_portfolios in Postgres."""
        cap = initial_capital if initial_capital is not None else self.initial_capital
        self._state = PortfolioState(
            total_equity=cap,
            cash=cap,
            used_margin=0.0
        )
        await self.redis.client.delete(self.REDIS_KEY_STATE)
        await self.redis.client.delete(self.REDIS_KEY_HEAT)
        await self.redis.client.delete(self.REDIS_KEY_FACTORS)
        logger.info("🧹 Portfolio state cleared in Redis")
        
        # Initialize standard backtest_portfolios table for frontend visibility
        if run_id:
            try:
                conn = psycopg2.connect(
                    host=self.pg_host, port=5432, user="admin", password="password123", database="quant_platform"
                )
                cur = conn.cursor()
                cur.execute("""
                    INSERT INTO backtest_portfolios (user_id, run_id, balance, equity, last_updated)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (user_id, run_id) DO UPDATE SET
                    balance = EXCLUDED.balance,
                    equity = EXCLUDED.equity,
                    last_updated = EXCLUDED.last_updated;
                """, ("default_user", run_id, cap, cap, timestamp or timesync.now_ist()))
                conn.commit()
                cur.close()
                conn.close()
            except Exception as e:
                logger.error(f"Failed to initialize backtest_portfolios: {e}")

        # Take initial snapshot to mark the start of the equity curve at initial_capital
        await self.take_snapshot(timestamp, run_id=run_id)

    async def save_state(self):
        """Persist state to Redis."""
        if self._state:
            # Update metrics before saving
            self.heat_manager.calculate_heat(self._state)
            self.factor_manager.calculate_exposures(self._state)
            
            # Ensure timestamp in model is updated if needed, but snapshots handle temporal logging
            state_json = self._state.json()
            await self.redis.client.set(self.REDIS_KEY_STATE, state_json)
            await self.redis.client.set(self.REDIS_KEY_HEAT, str(self._state.total_heat_pct))
            await self.redis.client.set(self.REDIS_KEY_FACTORS, json.dumps(self._state.factor_exposure))

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

    async def update_position(self, symbol: str, qty: int, price: float, sector: str, direction: str = "LONG", timestamp: Optional[datetime] = None):
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
        await self.take_snapshot(timestamp, db_conn=None)

    async def update_position_v2(self, symbol: str, qty: int, price: float, sector: str, direction: str = "LONG", timestamp: Optional[datetime] = None, run_id: Optional[str] = None):
        """Update portfolio state and record trade in backtest_orders for frontend."""
        state = await self.get_state()
        
        # 1. Logic to add/update position
        existing = next((p for p in state.open_positions if p.symbol == symbol), None)
        pnl = 0.0
        
        if existing:
            # Simple handling for adding to position (average price logic can be added later)
            if (existing.direction == "LONG" and qty < 0) or (existing.direction == "SHORT" and qty > 0):
                # Closing or reducing: calc PnL
                closed_qty = min(abs(existing.qty), abs(qty))
                mult = 1 if existing.direction == "LONG" else -1
                pnl = closed_qty * (price - existing.entry_price) * mult
            
            total_qty = existing.qty + qty
            if total_qty == 0:
                state.open_positions = [p for p in state.open_positions if p.symbol != symbol]
            else:
                # Update entry price if adding to position (moving average)
                if (existing.qty > 0 and qty > 0) or (existing.qty < 0 and qty < 0):
                    total_cost = (existing.qty * existing.entry_price) + (qty * price)
                    existing.entry_price = total_cost / total_qty
                existing.qty = total_qty
                existing.current_price = price
        else:
            if qty != 0:
                state.open_positions.append(Position(
                    symbol=symbol,
                    direction=direction,
                    qty=qty,
                    entry_price=price,
                    current_price=price,
                    market_value=qty * price,
                    risk_at_risk=price * 0.02,
                    sector=sector
                ))
        
        # 2. Update cash
        state.cash -= (qty * price)
        
        # 3. Persist to standard backtest_orders table for frontend
        if run_id:
            try:
                conn = psycopg2.connect(
                    host=self.pg_host, port=5432, user="admin", password="password123", database="quant_platform"
                )
                cur = conn.cursor()
                cur.execute("""
                    INSERT INTO backtest_orders (run_id, timestamp, symbol, transaction_type, quantity, price, pnl, status)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """, (
                    run_id, timestamp or timesync.now_ist(), symbol, 
                    "BUY" if qty > 0 else "SELL", abs(qty), price, pnl, 'filled'
                ))
                conn.commit()
                cur.close()
                conn.close()
            except Exception as e:
                logger.error(f"Failed to record backtest_order: {e}")

        await self.save_state()
        await self.take_snapshot(timestamp, run_id=run_id)

    async def mark_to_market(self, price_map: Dict[str, float], timestamp: Optional[datetime] = None, db_conn = None, run_id: Optional[str] = None):
        """
        Updates the current prices of all open positions and recalculates total equity.
        Syncs with backtest_portfolios for frontend visibility.
        """
        state = await self.get_state()
        if not state.open_positions:
            state.total_equity = state.cash
        else:
            total_market_value = 0.0
            for pos in state.open_positions:
                if pos.symbol in price_map:
                    pos.current_price = price_map[pos.symbol]
                    pos.market_value = pos.qty * pos.current_price
                total_market_value += pos.market_value
            state.total_equity = state.cash + total_market_value
            
        # Update standard portfolio table for frontend
        if run_id:
            try:
                # We use the passed db_conn if available to avoid opening many connections
                conn = db_conn
                close_after = False
                if conn is None:
                    conn = psycopg2.connect(
                        host=self.pg_host, port=5432, user="admin", password="password123", database="quant_platform"
                    )
                    close_after = True
                
                cur = conn.cursor()
                cur.execute("""
                    UPDATE backtest_portfolios 
                    SET balance = %s, equity = %s, last_updated = %s
                    WHERE run_id = %s;
                """, (state.cash, state.total_equity, timestamp or timesync.now_ist(), run_id))
                conn.commit()
                cur.close()
                if close_after:
                    conn.close()
            except Exception as e:
                logger.error(f"Failed to update backtest_portfolios during MtM: {e}")

        await self.save_state()
        await self.take_snapshot(timestamp, db_conn=db_conn, run_id=run_id)

    async def take_snapshot(self, timestamp: Optional[datetime] = None, db_conn = None, run_id: Optional[str] = None):
        """
        Saves a point-in-time snapshot to the PostgreSQL metadata DB.
        Useful for building historical equity curves and sector heatmaps.
        """
        state = await self.get_state()
        snapshot_time = timestamp or timesync.now_ist()
        conn = db_conn
        should_close = False
        try:
            if conn is None:
                conn = psycopg2.connect(
                    host=self.pg_host, 
                    port=5432, 
                    user="admin", 
                    password="password123", 
                    database="quant_platform"
                )
                should_close = True
            cur = conn.cursor()
            # Ensure table exists (idempotent)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS portfolio_snapshots (
                    id SERIAL PRIMARY KEY,
                    snapshot_time TIMESTAMP WITH TIME ZONE,
                    heat_pct DOUBLE PRECISION,
                    factor_banking DOUBLE PRECISION,
                    factor_it DOUBLE PRECISION,
                    factor_energy DOUBLE PRECISION,
                    factor_fmcg DOUBLE PRECISION,
                    open_positions_count INTEGER,
                    full_json JSONB,
                    run_id VARCHAR(100)
                );
            """)
            cur.execute("""
                INSERT INTO portfolio_snapshots (
                    snapshot_time, heat_pct, factor_banking, factor_it, 
                    factor_energy, factor_fmcg, open_positions_count, full_json, run_id
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                snapshot_time,
                state.total_heat_pct,
                state.factor_exposure.get("BANKING", 0.0),
                state.factor_exposure.get("IT", 0.0),
                state.factor_exposure.get("ENERGY", 0.0),
                state.factor_exposure.get("FMCG", 0.0),
                len(state.open_positions),
                state.json(),
                run_id
            ))
            conn.commit()
            cur.close()
            if should_close:
                conn.close()
            logger.info(f"📸 Portfolio snapshot saved to PostgreSQL (run_id={run_id})")
        except Exception as e:
            logger.error(f"Failed to save portfolio snapshot: {e}")
