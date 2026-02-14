import os
import psycopg2
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
from typing import List, Optional
import requests
from pydantic import BaseModel

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

class BacktestRequest(BaseModel):
    strategy_code: str
    symbol: str
    start_date: str
    end_date: str
    initial_cash: float
    strategy_name: str = "CustomStrategy"

@app.post("/api/v1/backtest/run")
def run_backtest(request: BacktestRequest):
    """Trigger a backtest on the Strategy Runtime"""
    try:
        # Forward to Strategy Runtime Service
        # Assuming strategy_runtime is exposing port 8000
        # Check if code is provided to execute or if it's a pre-loaded strategy
        response = requests.post(
            "http://strategy_runtime:8000/backtest",
            json=request.dict(),
            timeout=10 
        )
        if response.status_code == 200:
             return response.json()
        else:
             raise HTTPException(status_code=response.status_code, detail=response.text)
    except requests.exceptions.RequestException as e:
        raise HTTPException(status_code=503, detail=f"Strategy Runtime Unavailable: {e}")

@app.post("/api/v1/backtest/stop/{run_id}")
def stop_backtest(run_id: str):
    """Stop a running backtest"""
    try:
        response = requests.post(f"http://strategy_runtime:8000/backtest/stop/{run_id}", timeout=5)
        if response.status_code == 200:
             return response.json()
        raise HTTPException(status_code=response.status_code, detail=response.text)
    except requests.exceptions.RequestException as e:
        raise HTTPException(status_code=503, detail=f"Strategy Runtime Unavailable: {e}")

@app.get("/api/v1/backtest/trades/{run_id}")
def get_backtest_trades(run_id: str):
    """Fetch executed trades for a specific backtest run"""
    conn = None
    try:
        conn = get_pg_conn()
        cur = conn.cursor()
        cur.execute("""
            SELECT timestamp, symbol, transaction_type, quantity, price, pnl 
            FROM backtest_orders 
            WHERE run_id = %s 
            ORDER BY timestamp ASC;
        """, (run_id,))
        rows = cur.fetchall()
        return [
            {
                "time": r[0].isoformat() if r[0] else None, 
                "symbol": r[1], 
                "side": r[2], 
                "quantity": r[3], 
                "price": float(r[4]), 
                "pnl": float(r[5]) if r[5] is not None else 0.0
            } 
            for r in rows
        ]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if conn: conn.close()

@app.get("/api/v1/backtest/logs/{run_id}")
def get_backtest_logs(run_id: str):
    """Fetch logs from Strategy Runtime"""
    try:
        response = requests.get(
            f"http://strategy_runtime:8000/backtest/logs/{run_id}",
            timeout=5
        )
        if response.status_code == 200:
             return response.json()
        raise HTTPException(status_code=response.status_code, detail=response.text)
    except requests.exceptions.RequestException as e:
        raise HTTPException(status_code=503, detail=f"Strategy Runtime Unavailable: {e}")