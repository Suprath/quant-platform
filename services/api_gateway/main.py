import os
import psycopg2
from fastapi import FastAPI
from dotenv import load_dotenv

load_dotenv()

app = FastAPI(title="Quant Trading API Gateway")

# Connection helper for Postgres (Trades)
def get_pg_conn():
    return psycopg2.connect(
        host="postgres_metadata",
        port=5432,
        user="admin",
        password="password123",
        database="quant_platform"
    )

# Connection helper for QuestDB (Market Data)
def get_qdb_conn():
    return psycopg2.connect(
        host="questdb_tsdb",
        port=8812,
        user="admin",
        password="quest",
        database="qdb"
    )

@app.get("/")
def read_root():
    return {"status": "Production-Grade Trading API Online"}

@app.get("/api/v1/trades")
def get_trades():
    """Fetch recent trades from Postgres (Page 20)"""
    conn = get_pg_conn()
    cur = conn.cursor()
    cur.execute("SELECT timestamp, symbol, transaction_type, price, status FROM executed_orders ORDER BY timestamp DESC LIMIT 20;")
    rows = cur.fetchall()
    cur.close()
    conn.close()
    
    return [
        {"time": r[0], "symbol": r[1], "side": r[2], "price": r[3], "status": r[4]} 
        for r in rows
    ]

@app.get("/api/v1/market/quote/{symbol}")
def get_quote(symbol: str):
    """Fetch latest price from QuestDB (Page 20)"""
    conn = get_qdb_conn()
    cur = conn.cursor()
    # QuestDB specific LATEST BY query
    cur.execute(f"SELECT timestamp, symbol, ltp FROM ticks WHERE symbol = '{symbol}' LATEST BY symbol;")
    row = cur.fetchone()
    cur.close()
    conn.close()
    
    if row:
        return {"timestamp": row[0], "symbol": row[1], "ltp": row[2]}
    return {"error": "Symbol not found"}
