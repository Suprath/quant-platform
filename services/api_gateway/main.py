import os
import psycopg2
from fastapi import FastAPI, HTTPException
from dotenv import load_dotenv

load_dotenv()

app = FastAPI(
    title="Quant Trading Platform API",
    description="Production-grade API Gateway for Market Data and Trade Execution",
    version="1.0.0"
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
        password="quest", # Standard QuestDB default
        database="qdb"
    )

# --- ENDPOINTS ---

@app.get("/")
def health_check():
    """Check if the API and its data connections are alive"""
    return {
        "status": "online",
        "gateway": "ready",
        "version": "1.0.0"
    }

@app.get("/api/v1/trades")
def get_trades():
    """Fetch recent executed trades from Postgres (Ref: PDF Page 20)"""
    conn = None
    try:
        conn = get_pg_conn()
        cur = conn.cursor()
        # Querying the table we created in the previous steps
        cur.execute("""
            SELECT timestamp, symbol, transaction_type, price, status, strategy_id 
            FROM executed_orders 
            ORDER BY timestamp DESC 
            LIMIT 50;
        """)
        rows = cur.fetchall()
        return [
            {
                "time": r[0],
                "symbol": r[1],
                "side": r[2],
                "price": r[3],
                "status": r[4],
                "strategy": r[5]
            } for r in rows
        ]
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Postgres Error: {str(e)}")
    finally:
        if conn:
            conn.close()

@app.get("/api/v1/market/quote/{symbol}")
def get_quote(symbol: str):
    """Fetch the latest price for a symbol from QuestDB (Ref: PDF Page 20)"""
    conn = None
    try:
        conn = get_qdb_conn()
        cur = conn.cursor()
        
        # FIXED QUERY: Using standard SQL that QuestDB PG-Wire understands 
        # specifically optimized for QuestDB's designated timestamp
        query = "SELECT timestamp, symbol, ltp FROM ticks WHERE symbol = %s ORDER BY timestamp DESC LIMIT 1;"
        
        cur.execute(query, (symbol,))
        row = cur.fetchone()
        
        if row:
            return {
                "timestamp": row[0],
                "symbol": row[1],
                "ltp": row[2],
                "source": "QuestDB"
            }
        raise HTTPException(status_code=404, detail="Symbol not found in market data")
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"QuestDB Error: {str(e)}")
    finally:
        if conn:
            conn.close()

# Start the server with: uvicorn main:app --host 0.0.0.0 --port 8000