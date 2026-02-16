import os
import psycopg2
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
from typing import List, Optional
import requests
from pydantic import BaseModel
from typing import Optional, Dict

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

class LiveStartRequest(BaseModel):
    strategy_name: str
    capital: float

class StrategySaveRequest(BaseModel):
    name: str
    code: str

@app.get("/api/v1/strategies")
def list_strategies():
    """Proxy to Strategy Runtime"""
    try:
        response = requests.get("http://strategy_runtime:8000/strategies", timeout=5)
        if response.status_code == 200:
             return response.json()
        raise HTTPException(status_code=response.status_code, detail=response.text)
    except requests.exceptions.RequestException as e:
        raise HTTPException(status_code=503, detail=f"Strategy Runtime Unavailable: {e}")

@app.post("/api/v1/live/start")
def start_live(request: LiveStartRequest):
    """Proxy to Strategy Runtime"""
    try:
        response = requests.post(
            "http://strategy_runtime:8000/live/start",
            json=request.dict(),
            timeout=5
        )
        if response.status_code == 200:
             return response.json()
        raise HTTPException(status_code=response.status_code, detail=response.text)
    except requests.exceptions.RequestException as e:
        raise HTTPException(status_code=503, detail=f"Strategy Runtime Unavailable: {e}")

@app.post("/api/v1/live/stop")
def stop_live():
    """Proxy to Strategy Runtime"""
    try:
        response = requests.post("http://strategy_runtime:8000/live/stop", timeout=5)
        if response.status_code == 200:
             return response.json()
        raise HTTPException(status_code=response.status_code, detail=response.text)
    except requests.exceptions.RequestException as e:
        raise HTTPException(status_code=503, detail=f"Strategy Runtime Unavailable: {e}")

@app.get("/api/v1/live/status")
def get_live_status():
    """Proxy to Strategy Runtime"""
    try:
        response = requests.get("http://strategy_runtime:8000/live/status", timeout=5)
        if response.status_code == 200:
             return response.json()
        # Fallback if 404/etc
        return {"status": "stopped", "message": "Runtime unreachable or error"}
    except requests.exceptions.RequestException as e:
        return {"status": "stopped", "message": f"Runtime Unavailable: {e}"}

@app.post("/api/v1/strategies/save")
def save_strategy(request: StrategySaveRequest):
    """Save Strategy Proxy"""
    try:
        response = requests.post(
            "http://strategy_runtime:8000/strategies/save",
            json=request.dict(),
            timeout=5
        )
        if response.status_code == 200:
             return response.json()
        raise HTTPException(status_code=response.status_code, detail=response.text)
    except requests.exceptions.RequestException as e:
        raise HTTPException(status_code=503, detail=f"Strategy Runtime Unavailable: {e}")

class ProjectSaveRequest(BaseModel):
    project_name: str
    files: Dict[str, str]

@app.post("/api/v1/strategies/save-project")
def save_project(request: ProjectSaveRequest):
    """Save Multi-File Project Proxy"""
    try:
        response = requests.post(
            "http://strategy_runtime:8000/strategies/save-project",
            json=request.dict(),
            timeout=10
        )
        if response.status_code == 200:
             return response.json()
        raise HTTPException(status_code=response.status_code, detail=response.text)
    except requests.exceptions.RequestException as e:
        raise HTTPException(status_code=503, detail=f"Strategy Runtime Unavailable: {e}")

@app.get("/api/v1/strategies/project/{project_name}")
def get_project(project_name: str):
    """Get Project Files Proxy"""
    try:
        response = requests.get(
            f"http://strategy_runtime:8000/strategies/project/{project_name}",
            timeout=5
        )
        if response.status_code == 200:
             return response.json()
        raise HTTPException(status_code=response.status_code, detail=response.text)
    except requests.exceptions.RequestException as e:
        raise HTTPException(status_code=503, detail=f"Strategy Runtime Unavailable: {e}")

class BacktestRequest(BaseModel):
    strategy_code: str
    symbol: str
    start_date: str
    end_date: str
    initial_cash: float
    strategy_name: str = "CustomStrategy"
    project_files: Optional[Dict[str, str]] = None
    speed: Optional[str] = "fast"

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
            SELECT bo.timestamp, bo.symbol, bo.transaction_type, bo.quantity, bo.price, bo.pnl, bo.symbol as stock_name
            FROM backtest_orders bo
            WHERE bo.run_id = %s 
            ORDER BY bo.timestamp ASC;
        """, (run_id,))
        rows = cur.fetchall()
        return [
            {"time": r[0], "symbol": r[1], "side": r[2], "quantity": r[3], "price": r[4], "pnl": r[5], "stock_name": r[6]} 
            for r in rows
        ]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if conn: conn.close()

@app.get("/api/v1/backtest/stats/{run_id}")
def get_backtest_stats(run_id: str):
    """Fetch computed backtest statistics"""
    conn = None
    try:
        conn = get_pg_conn()
        cur = conn.cursor()
        cur.execute("""
            SELECT stats_json FROM backtest_results WHERE run_id = %s;
        """, (run_id,))
        row = cur.fetchone()
        if row:
            return row[0] # Return the JSON directly
        return {} # Empty if not ready
    except Exception as e:
        # Table might not exist yet if no backtest ran since update
        # logger.warning(f"Stats fetch error: {e}")
        return {}
    finally:
        if conn: conn.close()

@app.get("/api/v1/backtest/universe/{run_id}")
def get_backtest_universe(run_id: str):
    """Fetch scanner/universe results for a specific backtest run"""
    conn = None
    try:
        conn = get_pg_conn()
        cur = conn.cursor()
        cur.execute("""
            SELECT bu.date, bu.symbol, bu.score, i.symbol AS stock_name
            FROM backtest_universe bu
            LEFT JOIN instruments i ON bu.symbol = i.instrument_token
            WHERE bu.run_id = %s
            ORDER BY bu.date ASC, bu.score DESC;
        """, (run_id,))
        rows = cur.fetchall()
        return [
            {
                "date": r[0].isoformat() if r[0] else None,
                "symbol": r[1],
                "score": float(r[2]) if r[2] is not None else 0.0,
                "name": r[3] if r[3] else r[1]
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

# --- BACKTEST HISTORY ---

@app.get("/api/v1/backtest/history")
def get_backtest_history():
    """List all backtest runs with summary stats"""
    conn = None
    try:
        conn = get_pg_conn()
        cur = conn.cursor()
        cur.execute("""
            SELECT 
                bp.run_id,
                bp.balance,
                bp.equity,
                bp.last_updated,
                COALESCE(t.trade_count, 0) as trade_count,
                COALESCE(t.total_pnl, 0) as total_pnl,
                t.first_trade,
                t.last_trade
            FROM backtest_portfolios bp
            LEFT JOIN (
                SELECT 
                    run_id,
                    COUNT(*) as trade_count,
                    SUM(pnl) as total_pnl,
                    MIN(timestamp) as first_trade,
                    MAX(timestamp) as last_trade
                FROM backtest_orders
                GROUP BY run_id
            ) t ON bp.run_id = t.run_id
            ORDER BY bp.last_updated DESC;
        """)
        rows = cur.fetchall()
        return [
            {
                "run_id": r[0],
                "final_balance": float(r[1]) if r[1] else 0,
                "initial_equity": float(r[2]) if r[2] else 100000,
                "created_at": r[3].isoformat() if r[3] else None,
                "trade_count": r[4],
                "total_pnl": float(r[5]) if r[5] else 0,
                "start_date": r[6].isoformat() if r[6] else None,
                "end_date": r[7].isoformat() if r[7] else None,
            }
            for r in rows
        ]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if conn: conn.close()

@app.delete("/api/v1/backtest/{run_id}")
def delete_backtest(run_id: str):
    """Delete a specific backtest run and all associated data"""
    conn = None
    try:
        conn = get_pg_conn()
        cur = conn.cursor()
        
        # Delete from all backtest tables (positions cascade from portfolios)
        cur.execute("DELETE FROM backtest_orders WHERE run_id = %s;", (run_id,))
        orders_deleted = cur.rowcount
        
        cur.execute("DELETE FROM backtest_universe WHERE run_id = %s;", (run_id,))
        
        # Delete positions first (FK constraint), then portfolio
        cur.execute("""
            DELETE FROM backtest_positions WHERE portfolio_id IN (
                SELECT id FROM backtest_portfolios WHERE run_id = %s
            );
        """, (run_id,))

        cur.execute("DELETE FROM backtest_portfolios WHERE run_id = %s;", (run_id,))
        
        conn.commit()
        cur.close()
        return {"status": "deleted", "run_id": run_id, "orders_deleted": orders_deleted}
    except Exception as e:
        if conn: conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if conn: conn.close()

@app.delete("/api/v1/backtest/history")
def clear_backtest_history():
    """Clear ALL backtest data"""
    conn = None
    try:
        conn = get_pg_conn()
        cur = conn.cursor()
        
        cur.execute("DELETE FROM backtest_positions;")
        cur.execute("DELETE FROM backtest_orders;")
        cur.execute("DELETE FROM backtest_universe;")
        cur.execute("DELETE FROM backtest_portfolios;")
        total = cur.rowcount
        
        conn.commit()
        cur.close()
        return {"status": "cleared", "message": "All backtest history deleted"}
    except Exception as e:
        if conn: conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if conn: conn.close()



class BackfillStartRequest(BaseModel):
    start_date: str
    end_date: str
    stocks: Optional[List[str]] = None
    interval: str = "1"
    unit: str = "minutes"

@app.post("/api/v1/backfill/start")
def start_backfill(request: BackfillStartRequest):
    """Trigger multi-stock data backfill"""
    try:
        response = requests.post("http://data_backfiller:8001/backfill/start", json=request.dict(), timeout=10)
        if response.status_code == 200:
            return response.json()
        raise HTTPException(status_code=response.status_code, detail=response.text)
    except requests.exceptions.RequestException as e:
        raise HTTPException(status_code=503, detail=f"Backfiller Unavailable: {e}")

@app.get("/api/v1/backfill/status")
def get_backfill_status():
    """Get backfill progress"""
    try:
        response = requests.get("http://data_backfiller:8001/backfill/status", timeout=5)
        if response.status_code == 200:
            return response.json()
        raise HTTPException(status_code=response.status_code, detail=response.text)
    except requests.exceptions.RequestException as e:
        raise HTTPException(status_code=503, detail=f"Backfiller Unavailable: {e}")

@app.get("/api/v1/backfill/stocks")
def get_backfill_stocks():
    """List available stocks for backfill"""
    try:
        response = requests.get("http://data_backfiller:8001/backfill/stocks", timeout=5)
        if response.status_code == 200:
            return response.json()
        raise HTTPException(status_code=response.status_code, detail=response.text)
    except requests.exceptions.RequestException as e:
        raise HTTPException(status_code=503, detail=f"Backfiller Unavailable: {e}")