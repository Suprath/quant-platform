import logging
import json
import psycopg2
import os
from datetime import datetime, date
from kira_shared import timesync
from .models import TradeRecord
from ..mechanism_classifier.models import ClassifiedSignal
from ..portfolio_engine.models import PortfolioState

logger = logging.getLogger("LearningLoop")

class TradeRecorder:
    """
    Records complete context at entry and exit for performance learning.
    """
    
    def __init__(self):
        self.pg_host = os.getenv("POSTGRES_HOST", "postgres_metadata")
    
    def _get_conn(self):
        return psycopg2.connect(
            host=self.pg_host,
            user="admin",
            password="password123",
            database="quant_platform"
        )

    async def record_entry(
        self,
        signal: ClassifiedSignal,
        shares: int,
        entry_price: float,
        portfolio_state: PortfolioState
    ) -> str:
        
        now = timesync.now_ist()
        trade_id = f"trade_{signal.symbol}_{now:%Y%m%d_%H%M%S}"
        
        record = TradeRecord(
            trade_id=trade_id,
            signal_id=signal.signal_id,
            symbol=signal.symbol,
            direction=signal.direction,
            entry_date=now.date(),
            entry_time=now.time(),
            entry_price=entry_price,
            shares=shares,
            position_value=shares * entry_price,
            primary_mechanism=signal.primary_mechanism,
            mechanism_confidence=signal.mechanism_confidence,
            pattern_score=signal.pattern_score,
            result="OPEN"
        )
        
        try:
            conn = self._get_conn()
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO trade_records (
                    trade_id, signal_id, symbol, direction, entry_date, 
                    entry_price, shares, primary_mechanism, mechanism_confidence, 
                    pattern_score, result
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                record.trade_id, record.signal_id, record.symbol, record.direction,
                record.entry_date, record.entry_price, record.shares, 
                record.primary_mechanism, record.mechanism_confidence, 
                record.pattern_score, record.result
            ))
            conn.commit()
            cur.close()
            conn.close()
            logger.info(f"📝 Trade entry recorded: {trade_id}")
        except Exception as e:
            logger.error(f"Failed to record trade entry: {e}")
            
        return trade_id

    async def record_exit(
        self,
        trade_id: str,
        exit_price: float,
        exit_reason: str,
        min_price: float = 0.0,
        max_price: float = 0.0
    ):
        """Records trade exit and final metrics using C++ excursion kernels."""
        
        try:
            conn = self._get_conn()
            cur = conn.cursor()
            
            # 1. Fetch entry price to calc PnL (Simplified)
            cur.execute("SELECT entry_price, shares, direction FROM trade_records WHERE trade_id = %s", (trade_id,))
            row = cur.fetchone()
            if not row: return
            
            entry_price, shares, direction = row
            
            # 2. Calculate Excursion Metrics via C++
            mae, mfe = 0.0, 0.0
            try:
                import til_core
                # We normalize min/max for the C++ kernel
                res = til_core.calculate_excursion_metrics(
                    entry_price, 
                    min_price if min_price > 0 else exit_price, 
                    max_price if max_price > 0 else exit_price
                )
                mae, mfe = res.mae, res.mfe
            except ImportError:
                mae = (abs(min_price - entry_price) / entry_price) * 100.0 if entry_price > 0 else 0
                mfe = (abs(max_price - entry_price) / entry_price) * 100.0 if entry_price > 0 else 0

            pnl = (exit_price - entry_price) * shares * (1 if direction == "LONG" else -1)
            result = "WIN" if pnl > 0 else "LOSS"
            
            cur.execute("""
                UPDATE trade_records SET 
                    exit_date = %s, exit_price = %s, exit_reason = %s, 
                    net_pnl = %s, result = %s, 
                    max_adverse_excursion = %s, max_favorable_excursion = %s
                WHERE trade_id = %s
            """, (
                date.today(), exit_price, exit_reason, pnl, result, mae, mfe, trade_id
            ))
            conn.commit()
            cur.close()
            conn.close()
            logger.info(f"📊 Trade exit recorded: {trade_id} | PnL: {pnl:.2f}")
        except Exception as e:
            logger.error(f"Failed to record trade exit: {e}")
