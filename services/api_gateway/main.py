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

@app.get("/api/v1/config/env")
def get_env_config():
    """Fetch current environment variables from the mounted .env file"""
    env_vars = {}
    try:
        with open(".env", "r") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    if "=" in line:
                        key, val = line.split("=", 1)
                        env_vars[key.strip()] = val.strip()
        return {"env": env_vars}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

class EnvUpdateRequest(BaseModel):
    env: Dict[str, str]

@app.post("/api/v1/config/env")
def update_env_config(request: EnvUpdateRequest):
    """Update variables in the mounted .env file. Preserves comments and spacing."""
    try:
        updated_keys = set(request.env.keys())
        lines = []
        
        # Read existing file to preserve structure
        if os.path.exists(".env"):
            with open(".env", "r") as f:
                for line in f:
                    stripped = line.strip()
                    if stripped and not stripped.startswith("#") and "=" in stripped:
                        key, _ = line.split("=", 1)
                        key = key.strip()
                        if key in updated_keys:
                            lines.append(f"{key}={request.env[key]}\n")
                            updated_keys.remove(key)
                        else:
                            lines.append(line)
                    else:
                        lines.append(line)
        
        # Append any *new* keys that didn't already exist at the bottom
        for remaining_key in updated_keys:
            lines.append(f"{remaining_key}={request.env[remaining_key]}\n")
            
        with open(".env", "w") as f:
            f.writelines(lines)
            
        return {"status": "success", "message": "Environment variables updated successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

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

@app.get("/api/v1/market/ohlc")
def get_ohlc(
    symbol: str = Query(..., description="Instrument key e.g. NSE_EQ|INE002A01018"),
    start_date: str = Query(..., description="Start date YYYY-MM-DD"),
    end_date: str = Query(..., description="End date YYYY-MM-DD"),
    timeframe: str = Query("1m", description="Timeframe e.g. 1m, 5m, 1h, 1d"),
    limit: int = Query(10000, le=10000, description="Max rows (capped at 10000)")
):
    """Fetch historical OHLC candles from QuestDB for a given symbol and date range."""
    conn = None
    try:
        conn = get_qdb_conn()
        cur = conn.cursor()
        # QuestDB PG wire requires ISO timestamps for comparison
        ts_start = f"{start_date}T00:00:00.000000Z"
        ts_end = f"{end_date}T23:59:59.999999Z"
        query = """
            SELECT timestamp, symbol, open, high, low, close, volume 
            FROM ohlc 
            WHERE symbol = %s 
              AND timeframe = %s
              AND timestamp >= %s 
              AND timestamp <= %s 
            ORDER BY timestamp ASC
            LIMIT %s;
        """
        cur.execute(query, (symbol, timeframe, ts_start, ts_end, limit))
        rows = cur.fetchall()
        candles = [
            {
                "timestamp": str(r[0]),
                "symbol": r[1],
                "open": float(r[2]),
                "high": float(r[3]),
                "low": float(r[4]),
                "close": float(r[5]),
                "volume": int(r[6]) if r[6] else 0
            }
            for r in rows
        ]
        return {"symbol": symbol, "timeframe": timeframe, "count": len(candles), "candles": candles}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if conn: conn.close()

@app.get("/api/v1/market/top-performers")
def get_top_performers(limit: int = Query(10, le=50, description="Number of top stocks to return")):
    """Fetch yesterday's top performing stocks by % change from QuestDB"""
    conn = None
    try:
        conn = get_qdb_conn()
        cur = conn.cursor()
        
        # 1. First find the most recent trading date in the DB
        cur.execute("SELECT max(timestamp) FROM ohlc WHERE timeframe = '1m';")
        max_date_row = cur.fetchone()
        
        if not max_date_row or not max_date_row[0]:
            return []
            
        latest_date = max_date_row[0].date()
        latest_ts = f"{latest_date}T00:00:00.000000Z"
        
        # 2. Get OHLC for that date, join with postgres for stock names, compute % change
        cur.execute(f"""
            SELECT symbol, 
                   first(open) as daily_open, 
                   last(close) as daily_close, 
                   sum(volume) as daily_volume 
            FROM ohlc 
            WHERE timeframe = '1m'
              AND timestamp >= '{latest_ts}'
            SAMPLE BY 1d ALIGN TO CALENDAR
            ORDER BY ((last(close) - first(open)) / first(open)) DESC
            LIMIT {limit};
        """)
        qdb_rows = cur.fetchall()
        
        if not qdb_rows:
            return []
            
        # 3. Enhance with Postgres instrument metadata for human-readable names
        top_stocks = []
        try:
            pg_conn = get_pg_conn()
            pg_cur = pg_conn.cursor()
            
            for r in qdb_rows:
                symbol_key = r[0]
                open_p = float(r[1])
                close_p = float(r[2])
                volume = int(r[3])
                
                pct_change = ((close_p - open_p) / open_p) * 100 if open_p > 0 else 0
                
                # Try fetching symbol name
                pg_cur.execute("SELECT symbol FROM instruments WHERE instrument_token = %s", (symbol_key,))
                name_row = pg_cur.fetchone()
                stock_name = name_row[0] if name_row else symbol_key.split("|")[-1]
                
                top_stocks.append({
                    "symbol": symbol_key,
                    "name": stock_name,
                    "open": open_p,
                    "close": close_p,
                    "change_pct": round(pct_change, 2),
                    "volume": volume,
                    "date": str(latest_date)
                })
        except Exception as pg_err:
             print(f"Postgres name fetch failed: {pg_err}")
             # Return just symbols if Postgres fails
             for r in qdb_rows:
                 open_p = float(r[1])
                 close_p = float(r[2])
                 pct_change = ((close_p - open_p) / open_p) * 100 if open_p > 0 else 0
                 top_stocks.append({
                     "symbol": r[0],
                     "name": r[0],
                     "open": open_p,
                     "close": close_p,
                     "change_pct": round(pct_change, 2),
                     "volume": int(r[3]),
                     "date": str(latest_date)
                 })
        finally:
            if 'pg_conn' in locals() and pg_conn:
                pg_conn.close()

        # Re-sort just in case
        top_stocks.sort(key=lambda x: x['change_pct'], reverse=True)
        return top_stocks
        
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