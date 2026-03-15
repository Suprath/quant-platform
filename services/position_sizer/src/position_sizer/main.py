import os
import asyncio
import logging
from fastapi import FastAPI
from kira_shared.logging.setup import setup_logging
from kira_shared.redis.client import RedisClient

setup_logging()
app = FastAPI(title="KIRA Position Sizer")

from .producer import SizingProducer
from .consumer import SizingConsumer

setup_logging()
app = FastAPI(title="KIRA Position Sizer")

KAFKA_BOOTSTRAP = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
REDIS_HOST = os.getenv("REDIS_HOST", "localhost")

redis_client = RedisClient(host=REDIS_HOST, port=6379)
sizing_producer = SizingProducer(KAFKA_BOOTSTRAP)
sizing_consumer = SizingConsumer(KAFKA_BOOTSTRAP, sizing_producer)

logger = logging.getLogger("PositionSizer")

import math
import psycopg2
from psycopg2 import pool
from kira_shared.models.sizing import SizingRequest, SizingResult

# C++ Core Integration
try:
    from position_sizer_core import PositionSizerCore
    cpp_core = PositionSizerCore()
    logger.info("🚀 C++ Position Sizer Core loaded successfully.")
except ImportError:
    logger.warning("⚠️ C/C++ Position Sizer Core not found. Falling back to Python.")
    cpp_core = None

# QuestDB connection for ATR calculation
QDB_HOST = os.getenv("QUESTDB_HOST", "questdb_tsdb")

_QDB_POOL = None

def get_qdb_conn():
    global _QDB_POOL
    if _QDB_POOL is None:
        try:
            _QDB_POOL = pool.ThreadedConnectionPool(1, 10,
                host=QDB_HOST, port=8812, user="admin", password="quest", database="qdb")
            logger.info("✅ Position Sizer QuestDB Pool Initialized")
        except Exception as e:
            logger.error(f"Failed to init QuestDB Pool: {e}")
            return psycopg2.connect(host=QDB_HOST, port=8812, user="admin", password="quest", database="qdb")
    return _QDB_POOL.getconn()

def release_qdb_conn(conn):
    if _QDB_POOL: _QDB_POOL.putconn(conn)
    else: conn.close()

def fetch_daily_ranges(symbol, timestamp):
    """Fetch last 14 days of high-low ranges from QuestDB."""
    conn = get_qdb_conn()
    if not conn: return []
    try:
        cur = conn.cursor()
        query = f"""
        SELECT max(high) - min(low) as tr
        FROM ohlc 
        WHERE symbol = '{symbol}' AND timestamp < '{timestamp}'
        SAMPLE BY 1d ALIGN TO CALENDAR
        LIMIT 14;
        """
        cur.execute(query)
        rows = cur.fetchall()
        return [float(r[0]) for r in rows if r[0]]
    except Exception as e:
        logger.error(f"Error fetching daily ranges for {symbol}: {e}")
        return []
    finally:
        if conn:
            release_qdb_conn(conn)

@app.get("/health")
async def health():
    return {"status": "healthy", "cpp_core_active": cpp_core is not None}

@app.post("/size", response_model=SizingResult)
async def get_position_size(request: SizingRequest):
    """
    Calculate risk-adjusted position size based on Volatility (ATR) and AI Confidence.
    Now optimized with C++ core.
    """
    logger.info(f"📏 Calculating Smart Size for {request.symbol} (C++: {cpp_core is not None})")
    
    # 1. Fetch historical volatility context
    daily_ranges = []
    if request.timestamp:
        daily_ranges = fetch_daily_ranges(request.symbol, request.timestamp)
    
    # 2. Use C++ Core if available for high-speed computation
    if cpp_core:
        atr = cpp_core.calculate_atr(daily_ranges)
        shares = cpp_core.compute_shares(
            request.entry_price,
            request.confidence_score,
            request.current_equity,
            atr
        )
        # Re-derive stop distance for exit plan
        stop_dist = (atr * 2.0) if atr > 0 else (request.entry_price * 0.02)
        source = f"cpp_atr({atr:.2f})" if atr > 0 else "cpp_fixed_2%"
    else:
        # Python Fallback (Original Logic)
        atr = sum(daily_ranges) / len(daily_ranges) if daily_ranges else 0
        risk_pct = 0.015 if request.confidence_score >= 80 else (0.01 if request.confidence_score >= 60 else 0.005)
        stop_dist = (atr * 2.0) if atr > 0 else (request.entry_price * 0.02)
        shares = int((request.current_equity * risk_pct) / stop_dist) if stop_dist > 0 else 0
        source = f"py_atr({atr:.2f})" if atr > 0 else "py_fixed_2%"

    # 3. Apply Safety Cap
    max_shares = int(request.current_equity / request.entry_price)
    shares = min(shares, max_shares)

    result = SizingResult(
        request_id=request.request_id,
        symbol=request.symbol,
        approved=True,
        shares=shares,
        position_value=shares * request.entry_price,
        risk_pct_nav=(0.015 if request.confidence_score >= 80 else (0.01 if request.confidence_score >= 60 else 0.005)) * 100,
        net_ev=0.0,
        exit_plan={"stop_loss": request.entry_price - stop_dist, "sl_source": source}
    )
    
    logger.info(f"✅ Calculated: {shares} shares | SL Source: {source}")
    return result

@app.on_event("startup")
async def startup_event():
    await sizing_producer.start()
    await sizing_consumer.start()

@app.on_event("shutdown")
async def shutdown_event():
    await sizing_consumer.stop()
    await sizing_producer.stop()
    await redis_client.close()
