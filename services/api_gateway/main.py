import os
import psycopg2
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
from typing import List, Optional

load_dotenv()

app = FastAPI(
    title="Quant Platform API Gateway",
    description="Unified API for Market Data, Option Greeks, and Trade Execution",
    version="1.1.0"
)

# Enable CORS so you can eventually connect a React/Next.js frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- DATABASE CONNECTION HELPERS ---

def get_pg_conn():
    """Connect to PostgreSQL (Relational Metadata & Trades)"""
    return psycopg2.connect(
        host=os.getenv("POSTGRES_HOST", "postgres_metadata"),
        port=5432,
        user="admin",
        password="password123",
        database="quant_platform"
    )

def get_qdb_conn():
    """Connect to QuestDB (Time-Series Market Data)"""
    return psycopg2.connect(
        host=os.getenv("QUESTDB_HOST", "questdb_tsdb"),
        port=8812,
        user="admin",
        password="quest",
        database="qdb"
    )

# --- ENDPOINTS ---

@app.get("/")
def health_check():
    return {"status": "online", "modules": ["Equity", "Greeks", "Instruments", "Execution"]}

@app.get("/api/v1/market/quote/{symbol}")
def get_quote(symbol: str):
    """Fetch latest price and volume from QuestDB"""
    conn = None
    try:
        conn = get_qdb_conn()
        cur = conn.cursor()
        # Optimized for QuestDB's designated timestamp
        query = "SELECT timestamp, symbol, ltp, volume, oi FROM ticks WHERE symbol = %s ORDER BY timestamp DESC LIMIT 1;"
        cur.execute(query, (symbol,))
        r = cur.fetchone()
        if r:
            return {"timestamp": r[0], "symbol": r[1], "ltp": r[2], "volume": r[3], "oi": r[4]}
        raise HTTPException(status_code=404, detail="Quote not found")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if conn: conn.close()

@app.get("/api/v1/market/greeks/{symbol}")
def get_greeks(symbol: str):
    """Fetch latest Option Greeks from QuestDB"""
    conn = None
    try:
        conn = get_qdb_conn()
        cur = conn.cursor()
        query = "SELECT timestamp, symbol, iv, delta, gamma, theta, vega FROM option_greeks WHERE symbol = %s ORDER BY timestamp DESC LIMIT 1;"
        cur.execute(query, (symbol,))
        r = cur.fetchone()
        if r:
            return {
                "timestamp": r[0], "symbol": r[1], "iv": r[2], 
                "delta": r[3], "gamma": r[4], "theta": r[5], "vega": r[6]
            }
        raise HTTPException(status_code=404, detail="Greeks not found for this symbol")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if conn: conn.close()

@app.get("/api/v1/trades")
def get_trades(limit: int = 50):
    """Fetch recent trade history from Postgres"""
    conn = None
    try:
        conn = get_pg_conn()
        cur = conn.cursor()
        cur.execute("""
            SELECT timestamp, symbol, transaction_type, price, status, strategy_id 
            FROM executed_orders 
            ORDER BY timestamp DESC LIMIT %s;
        """, (limit,))
        rows = cur.fetchall()
        return [
            {"time": r[0], "symbol": r[1], "side": r[2], "price": r[3], "status": r[4], "strategy": r[5]} 
            for r in rows
        ]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if conn: conn.close()

@app.get("/api/v1/instruments/search")
def search_instruments(query: str = Query(..., min_length=3)):
    """Search for symbols in the Instrument Master (Handy for finding Option Keys)"""
    conn = None
    try:
        conn = get_pg_conn()
        cur = conn.cursor()
        # Search by trading symbol or name (case-insensitive)
        search_param = f"%{query}%"
        cur.execute("""
            SELECT instrument_token, tradingsymbol, name, exchange, lot_size 
            FROM instruments 
            WHERE tradingsymbol ILIKE %s OR name ILIKE %s 
            LIMIT 10;
        """, (search_param, search_param))
        rows = cur.fetchall()
        return [
            {"key": r[0], "symbol": r[1], "name": r[2], "exchange": r[3], "lot_size": r[4]} 
            for r in rows
        ]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if conn: conn.close()