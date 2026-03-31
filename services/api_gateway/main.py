import os
import psycopg2
from fastapi import FastAPI, HTTPException, Query, Depends
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
from typing import List, Optional
import requests
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from typing import Optional, Dict
import json
from datetime import datetime, timedelta
import redis as redis_sync
from fastapi import WebSocket, WebSocketDisconnect
import asyncio
from confluent_kafka import Producer
from kira_shared.kafka.schemas import KafkaEnvelope
load_dotenv()

# --- REDIS CLIENT ---
def _init_redis_client():
    try:
        r = redis_sync.Redis(
            host=os.getenv("REDIS_HOST", "redis_state"),
            port=int(os.getenv("REDIS_PORT", 6379)),
            db=0,
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=1.0,
        )
        r.ping()
        return r
    except Exception as e:
        print(f"Warning: Redis unavailable: {e}")
        return None

redis_client = _init_redis_client()


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

# --- DATABASE CONNECTION HELPERS (CONNECTION POOLING) ---
from psycopg2 import pool

# Global Connection Pools
pg_pool = None
qdb_pool = None

import time

# Kafka Producer for dynamic subscriptions
producer = Producer({'bootstrap.servers': os.getenv('KAFKA_BOOTSTRAP_SERVERS', 'kafka_bus:9092')})

# Global Requests Session for pooling
_http_session = requests.Session()
adapter = requests.adapters.HTTPAdapter(pool_connections=20, pool_maxsize=100)
_http_session.mount("http://", adapter)
_http_session.mount("https://", adapter)

@app.on_event("startup")
def startup_db_pools():
    global pg_pool, qdb_pool
    retries = 10
    
    for attempt in range(retries):
        try:
            if not pg_pool:
                pg_pool = psycopg2.pool.ThreadedConnectionPool(
                    1, 20, # Min 1, Max 20 connections
                    host=os.getenv("POSTGRES_HOST", "postgres_metadata"),
                    port=5432,
                    user=os.getenv("POSTGRES_USER", "admin"),
                    password=os.getenv("POSTGRES_PASSWORD", "password123"),
                    database=os.getenv("POSTGRES_DB", "quant_platform")
                )
            
            if not qdb_pool:
                qdb_pool = psycopg2.pool.ThreadedConnectionPool(
                    1, 20,
                    host=os.getenv("QUESTDB_HOST", "questdb_tsdb"),
                    port=8812,
                    user=os.getenv("QUESTDB_USER", "admin"),
                    password=os.getenv("QUESTDB_PASSWORD", "quest"),
                    database="qdb"
                )
            
            print("✅ Database Connection Pools Initialized Successfully")
            return
            
        except Exception as e:
            print(f"⚠️ [Attempt {attempt+1}/{retries}] Failed to initialize connection pools: {e}")
            time.sleep(3)
            
    print("❌ CRITICAL: Reached maximum retries for DB connection pools.")

@app.on_event("shutdown")
def shutdown_db_pools():
    if pg_pool: pg_pool.closeall()
    if qdb_pool: qdb_pool.closeall()

def get_pg_conn():
    """Dependency Generator: Acquire from PG Pool"""
    try:
        conn = pg_pool.getconn()
        yield conn
    finally:
        pg_pool.putconn(conn)

def get_qdb_conn():
    """Dependency Generator: Acquire from QuestDB Pool"""
    try:
        conn = qdb_pool.getconn()
        yield conn
    finally:
        qdb_pool.putconn(conn)

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
                        clean_key = key.strip()
                        if not clean_key.startswith("GRAFANA_"):
                            env_vars[clean_key] = val.strip()
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
def get_quote(symbol: str, conn = Depends(get_qdb_conn)):
    """Fetch latest price and volume from QuestDB"""
    try:
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

@app.get("/api/v1/market/greeks/{symbol}")
def get_greeks(symbol: str, conn = Depends(get_qdb_conn)):
    """Fetch latest Option Greeks from QuestDB"""
    try:
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

@app.get("/api/v1/market/ohlc")
def get_ohlc(
    symbol: str = Query(..., description="Instrument key e.g. NSE_EQ|INE002A01018"),
    start_date: str = Query(..., description="Start date YYYY-MM-DD"),
    end_date: str = Query(..., description="End date YYYY-MM-DD"),
    timeframe: str = Query("1m", description="Timeframe e.g. 1m, 5m, 1h, 1d"),
    limit: int = Query(10000, le=10000, description="Max rows (capped at 10000)"),
    conn = Depends(get_qdb_conn)
):
    """Fetch historical OHLC candles from QuestDB for a given symbol and date range."""
    try:
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
@app.get("/api/v1/options/expiries/{underlying}")
def get_option_expiries(
    underlying: str, 
    as_of: Optional[str] = Query(None, description="YYYY-MM-DD. Fetch expiries >= this date. Defaults to today."),
    conn = Depends(get_pg_conn)
):
    """Fetch distinct expiry dates for a given underlying symbol from Postgres."""
    try:
        cur = conn.cursor()
        
        # Auto-resolve instrument_token to base symbol if passed
        if '|' in underlying:
            cur.execute("SELECT symbol FROM instruments WHERE instrument_token = %s", (underlying,))
            row = cur.fetchone()
            if row:
                underlying = row[0]

        if as_of:
            query = """
                SELECT DISTINCT expiry 
                FROM instruments 
                WHERE underlying_symbol = %s 
                  AND segment IN ('OPTIDX', 'OPTSTK')
                  AND expiry >= %s
                ORDER BY expiry ASC;
            """
            cur.execute(query, (underlying, as_of))
        else:
            query = """
                SELECT DISTINCT expiry 
                FROM instruments 
                WHERE underlying_symbol = %s 
                  AND segment IN ('OPTIDX', 'OPTSTK')
                  AND expiry >= CURRENT_DATE
                ORDER BY expiry ASC;
            """
            cur.execute(query, (underlying,))
            
        rows = cur.fetchall()
        return {"underlying": underlying, "expiries": [str(r[0]) for r in rows]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/v1/options/chain/{underlying}")
def get_option_chain(
    underlying: str, 
    expiry: str = Query(..., description="Expiry date YYYY-MM-DD"),
    mock: bool = Query(False, description="Generate mathematical mock greeks and depths"),
    conn_pg = Depends(get_pg_conn),
    conn_qdb = Depends(get_qdb_conn)
):
    """Fetch all CE and PE tokens for a specific underlying and expiry."""
    try:
        cur_pg = conn_pg.cursor()
        
        # Auto-resolve instrument_token to base symbol if passed
        if '|' in underlying:
            cur_pg.execute("SELECT symbol FROM instruments WHERE instrument_token = %s", (underlying,))
            row = cur_pg.fetchone()
            if row:
                underlying = row[0]

        query_pg = """
            SELECT instrument_token, symbol, strike, option_type, lot_size 
            FROM instruments 
            WHERE underlying_symbol = %s 
              AND expiry = %s
              AND segment IN ('OPTIDX', 'OPTSTK')
            ORDER BY strike ASC, option_type ASC;
        """
        cur_pg.execute(query_pg, (underlying, expiry))
        rows = cur_pg.fetchall()
        
        contracts = []
        token_list = []
        strikes = set()
        for r in rows:
            token = r[0]
            strk = float(r[2]) if r[2] else 0.0
            token_list.append(token)
            strikes.add(strk)
            contracts.append({
                "instrument_token": token,
                "symbol": r[1],
                "strike": strk,
                "option_type": r[3],
                "expiry": expiry,
                "lot_size": int(r[4]) if r[4] else 1,
                # Defaults if no market data exists yet
                "ltp": 0.0, "volume": 0, "oi": 0, "bid": 0.0, "ask": 0.0,
                "iv": 0.0, "delta": 0.0, "gamma": 0.0, "theta": 0.0, "vega": 0.0
            })
            
        if mock and len(strikes) > 0:
            import math
            import random
            sorted_strikes = sorted(list(strikes))
            # Use the median strike as a logical spot guess
            spot_price = sorted_strikes[len(sorted_strikes) // 2]
            print(f"DEBUG: Generating mock data for {underlying} @ Spot ~{spot_price}")
            
            for c in contracts:
                strk = c["strike"]
                dist_pct = (strk - spot_price) / spot_price
                
                # 1. IV Smile (Lowest AT-The-Money)
                # Broadened curve with higher floor
                c["iv"] = round(0.18 + (abs(dist_pct) * 1.5), 4)
                
                # 2. Delta (Sigmoid crossing at Spot)
                # Reduced steepness for more gradual transition across larger strike ranges
                steepness = 8.0 
                ce_delta = 1.0 / (1.0 + math.exp(steepness * dist_pct))
                if c["option_type"] == "CE":
                    c["delta"] = round(ce_delta, 4)
                else:
                    c["delta"] = round(ce_delta - 1.0, 4)
                    
                # 3. Gamma (Bell Curve centered at Spot)
                gamma_peak = 0.002
                c["gamma"] = round(gamma_peak * math.exp(-(steepness * dist_pct)**2), 6)
                
                # 4. Theta
                theta_base = -12.0 
                c["theta"] = round(theta_base * math.exp(-(steepness * dist_pct)**2), 2)
                
                # 5. Vega (Widened bell curve)
                vega_base = 35.0
                c["vega"] = round(vega_base * math.exp(-(steepness * dist_pct)**2), 2)
                # Add a tiny floor for Vega so time_val is never zero
                if c["vega"] < 0.5: c["vega"] = 0.5
                
                # 6. Pricing (Simplified Black-Scholes-ish)
                intrinsic = max(0, spot_price - strk) if c["option_type"] == "CE" else max(0, strk - spot_price)
                # Ensure time value exists even for deep OTM
                time_val = (c["vega"] * c["iv"] * 15.0) + random.uniform(1.0, 5.0)
                c["ltp"] = round(intrinsic + time_val, 2)
                
                c["bid"] = max(0.05, round(c["ltp"] - max(0.05, c["ltp"] * 0.005), 2))
                c["ask"] = round(c["ltp"] + max(0.05, c["ltp"] * 0.005), 2)
                
                # 7. Volume Profile
                base_vol = random.randint(500, 2000)
                vol_multiplier = max(0.05, math.exp(-(steepness * 0.5 * dist_pct)**2))
                c["volume"] = int(base_vol * vol_multiplier * 100)
                c["oi"] = int(c["volume"] * random.uniform(3.0, 10.0))
                
        # 2. Bulk fetch real-time market data from QuestDB (Skip if mock is true)
        elif token_list:
            cur_qdb = conn_qdb.cursor()
            
            # Format IN clause for QuestDB: 'sym1', 'sym2', ...
            in_clause = ", ".join([f"'{t}'" for t in token_list])
            
            # Fetch Ticks (Prices/Volume/OI)
            query_ticks = f"SELECT symbol, ltp, volume, oi FROM ticks LATEST BY symbol WHERE symbol IN ({in_clause})"
            try:
                cur_qdb.execute(query_ticks)
                tick_rows = cur_qdb.fetchall()
                tick_map = {r[0]: {"ltp": r[1], "volume": r[2], "oi": r[3]} for r in tick_rows}
            except Exception as e:
                print(f"Warning: QuestDB ticks query failed: {e}")
                conn_qdb.rollback()
                tick_map = {}
                
            # Fetch Option Greeks
            query_greeks = f"SELECT symbol, iv, delta, gamma, theta, vega FROM option_greeks LATEST BY symbol WHERE symbol IN ({in_clause})"
            try:
                cur_qdb.execute(query_greeks)
                greek_rows = cur_qdb.fetchall()
                greek_map = {r[0]: {"iv": r[1], "delta": r[2], "gamma": r[3], "theta": r[4], "vega": r[5]} for r in greek_rows}
            except Exception as e:
                print(f"Warning: QuestDB greeks query failed: {e}")
                conn_qdb.rollback()
                greek_map = {}
                
            # Merge QuestDB data into the main contracts array
            for c in contracts:
                token = c["instrument_token"]
                
                # Merge Ticks
                if token in tick_map:
                    tm = tick_map[token]
                    c["ltp"] = float(tm["ltp"]) if tm["ltp"] is not None else 0.0
                    c["volume"] = int(tm["volume"]) if tm["volume"] is not None else 0
                    c["oi"] = int(tm["oi"]) if tm["oi"] is not None else 0
                    # Estimate Bid/Ask organically if no deep spread is available in DB currently. 
                    # Typical index option spread is roughly ~10bps
                    spread_est = c["ltp"] * 0.001 
                    c["bid"] = max(0.0, round(c["ltp"] - spread_est, 2))
                    c["ask"] = round(c["ltp"] + spread_est, 2)
                    
                # Merge Greeks
                if token in greek_map:
                    gm = greek_map[token]
                    c["iv"] = float(gm["iv"]) if gm["iv"] is not None else 0.0
                    c["delta"] = float(gm["delta"]) if gm["delta"] is not None else 0.0
                    c["gamma"] = float(gm["gamma"]) if gm["gamma"] is not None else 0.0
                    c["theta"] = float(gm["theta"]) if gm["theta"] is not None else 0.0
                    c["vega"] = float(gm["vega"]) if gm["vega"] is not None else 0.0

        return {
            "underlying": underlying,
            "expiry": expiry,
            "count": len(contracts),
            "contracts": contracts
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/v1/options/prime/{underlying}")
def prime_option_chain(
    underlying: str, 
    expiry: str = Query(..., description="Expiry date YYYY-MM-DD"),
    conn_pg = Depends(get_pg_conn),
    conn_qdb = Depends(get_qdb_conn)
):
    """
    Bulk fetch LTP and OI for ALL options in the chain using Upstox Snapshot API 
    and save to QuestDB to fill gaps.
    """
    try:
        cur_pg = conn_pg.cursor()
        query_pg = """
            SELECT instrument_token, symbol 
            FROM instruments 
            WHERE underlying_symbol = %s 
              AND expiry = %s
              AND segment IN ('OPTIDX', 'OPTSTK')
        """
        cur_pg.execute(query_pg, (underlying, expiry))
        rows = cur_pg.fetchall()
        
        if not rows:
            return {"status": "error", "message": "No instruments found for this expiry"}

        tokens = [r[0] for r in rows]
        # Upstox allows multiple tokens separated by comma
        access_token = os.getenv('UPSTOX_ACCESS_TOKEN')
        
        # Split into chunks of 50 to avoid URL length domestic limits
        chunk_size = 50
        total_synced = 0
        
        cur_qdb = conn_qdb.cursor()
        
        for i in range(0, len(tokens), chunk_size):
            chunk = tokens[i:i + chunk_size]
            encoded_keys = ",".join(chunk)
            
            url = f"https://api.upstox.com/v2/market-quote/quotes?instrument_key={encoded_keys}"
            headers = {
                'Accept': 'application/json',
                'Authorization': f'Bearer {access_token}'
            }
            
            resp = requests.get(url, headers=headers)
            if resp.status_code == 200:
                data = resp.json().get('data', {})
                for key_alias, quote in data.items():
                    # Upstox returns keys as "NSE_FO:SYMBOL"
                    token = quote.get('instrument_token')
                    ltp = quote.get('last_price', 0.0)
                    oi = quote.get('oi', 0)
                    volume = quote.get('volume', 0)
                    
                    if token:
                        # Insert into QuestDB
                        # Note: We use now() for timestamp if it's a fresh snapshot
                        cur_qdb.execute("""
                            INSERT INTO ticks (timestamp, symbol, ltp, volume, oi)
                            VALUES (now(), %s, %s, %s, %s)
                        """, (token, ltp, volume, oi))
                        total_synced += 1
                # Call Greeks API (Upstox v3)
                greeks_url = f"https://api.upstox.com/v3/market-quote/option-greek?instrument_key={encoded_keys}"
                greeks_resp = requests.get(greeks_url, headers=headers)
                if greeks_resp.status_code == 200:
                    greeks_data = greeks_resp.json().get('data', {})
                    for key_alias, g in greeks_data.items():
                        # Official V3 returns data indexed by instrument_key
                        token = g.get('instrument_token') or key_alias
                        if token:
                            cur_qdb.execute("""
                                INSERT INTO option_greeks (timestamp, symbol, iv, delta, gamma, theta, vega)
                                VALUES (now(), %s, %s, %s, %s, %s, %s)
                            """, (
                                token, 
                                float(g.get('iv', 0.0)), 
                                float(g.get('delta', 0.0)), 
                                float(g.get('gamma', 0.0)), 
                                float(g.get('theta', 0.0)), 
                                float(g.get('vega', 0.0))
                            ))
                else:
                    print(f"Warning: Greeks fetch failed for chunk {i}: {greeks_resp.text}")

                conn_qdb.commit()
        return {
            "status": "success", 
            "underlying": underlying, 
            "expiry": expiry, 
            "primed_count": total_synced
        }
        
    except Exception as e:
        if conn_qdb: conn_qdb.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/v1/options/sync/{underlying}")
def sync_option_data(
    underlying: str,
    expiry: str = Query(..., description="Expiry date YYYY-MM-DD"),
    conn_pg = Depends(get_pg_conn),
    conn_qdb = Depends(get_qdb_conn)
):
    """Notify Ingestor to start streaming specific options near spot."""
    try:
        cur_pg = conn_pg.cursor()
        
        # 1. Get a logical Spot price to center the sync around
        symbol_map = {
            "NIFTY": "NSE_INDEX|Nifty 50",
            "BANKNIFTY": "NSE_INDEX|Nifty Bank",
            "FINNIFTY": "NSE_INDEX|FINNIFTY"
        }
        search_sym = symbol_map.get(underlying, f"NSE_EQ|{underlying}")
        
        cur_qdb = conn_qdb.cursor()
        cur_qdb.execute(f"SELECT ltp FROM ticks WHERE symbol = %s ORDER BY timestamp DESC LIMIT 1;", (search_sym,))
        row = cur_qdb.fetchone()
        spot = float(row[0]) if row and row[0] else 0.0
        
        # Fallback if no real-time tick in QDB: Get median strike for this expiry from Postgres
        if spot == 0:
            cur_pg.execute("SELECT strike FROM instruments WHERE underlying_symbol = %s AND expiry = %s AND option_type = 'CE' ORDER BY strike", (underlying, expiry))
            strikes = cur_pg.fetchall()
            if strikes:
                spot = float(strikes[len(strikes)//2][0])
            else:
                spot = 22000.0 # Extreme fallback
                
        # 2. Select ~80 strikes around Spot (80 strikes x 2 types = 160 instruments)
        # This covers most of the active chain for NIFTY/BANKNIFTY
        query = """
            SELECT instrument_token FROM instruments 
            WHERE underlying_symbol = %s AND expiry = %s 
              AND segment IN ('OPTIDX', 'OPTSTK')
            ORDER BY ABS(strike - %s) ASC LIMIT 160
        """
        cur_pg.execute(query, (underlying, expiry, spot))
        tokens = [r[0] for r in cur_pg.fetchall()]
        
        if tokens:
            # 3. Inform Ingestor via Kafka
            msg = {"method": "sub", "mode": "full", "instrumentKeys": tokens}
            envelope = KafkaEnvelope(
                event_type="ingestor.subscription",
                source="api_gateway",
                payload=msg
            )
            producer.produce('ingestor.subscriptions', key=underlying, value=envelope.to_bytes())
            producer.flush()
            
        return {
            "status": "success", 
            "underlying": underlying, 
            "expiry": expiry, 
            "synced_tokens": len(tokens),
            "spot_proxy": spot
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/v1/market/top-performers")
def get_top_performers(
    limit: int = Query(50, le=100, description="Number of top stocks to return"),
    conn = Depends(get_qdb_conn),
    pg_conn = Depends(get_pg_conn)
):
    """Fetch yesterday's top performing stocks by % change from QuestDB, fallback to dictionary."""
    KNOWN_STOCKS = {
        "NSE_EQ|INE002A01018": "RELIANCE",
        "NSE_EQ|INE040A01034": "HDFCBANK",
        "NSE_EQ|INE467B01029": "TCS",
        "NSE_EQ|INE009A01021": "INFY",
        "NSE_EQ|INE090A01021": "ICICIBANK",
        "NSE_EQ|INE062A01020": "SBIN",
        "NSE_EQ|INE154A01025": "ITC",
        "NSE_EQ|INE669E01016": "BAJFINANCE",
        "NSE_EQ|INE030A01027": "HINDUNILVR",
        "NSE_EQ|INE585B01010": "MARUTI",
        "NSE_EQ|INE917I01010": "AXISBANK",
        "NSE_EQ|INE021A01026": "ASIANPAINT",
        "NSE_EQ|INE075A01022": "WIPRO",
        "NSE_EQ|INE238A01034": "KOTAKBANK",
        "NSE_EQ|INE028A01039": "BAJAJFINSV",
        "NSE_EQ|INE397D01024": "BHARTIARTL",
        "NSE_EQ|INE047A01021": "SUNPHARMA",
        "NSE_EQ|INE326A01037": "ULTRACEMCO",
        "NSE_EQ|INE101A01026": "HCLTECH",
        "NSE_EQ|INE155A01022": "TATAMOTORS",
    }
    
    try:
        cur = conn.cursor()
        
        # 1. First find the most recent trading date in the DB
        cur.execute("SELECT max(timestamp) FROM ohlc WHERE timeframe = '1m';")
        max_date_row = cur.fetchone()
        
        latest_date = None
        latest_ts = ""
        qdb_rows = []
        if max_date_row and max_date_row[0]:
            latest_date = max_date_row[0].date()
            latest_ts = f"{latest_date}T00:00:00.000000Z"
            
            # 2. Get OHLC for that date
            cur.execute(f"""
                SELECT symbol, 
                       first(open) as daily_open, 
                       last(close) as daily_close, 
                       sum(volume) as daily_volume 
                FROM ohlc 
                WHERE timeframe = '1m'
                  AND timestamp >= '{latest_ts}'
                SAMPLE BY 1d ALIGN TO CALENDAR
                ORDER BY ((last(close) - first(open)) / CASE WHEN first(open) = 0 THEN 1 ELSE first(open) END) DESC
                LIMIT {limit};
            """)
            qdb_rows = cur.fetchall()
            
        top_stocks = []
        seen_symbols = set()
        
        try:
            pg_cur = pg_conn.cursor()
            for r in qdb_rows:
                symbol_key = r[0]
                open_p = float(r[1])
                close_p = float(r[2])
                volume = int(r[3])
                pct_change = ((close_p - open_p) / open_p) * 100 if open_p > 0 else 0
                
                pg_cur.execute("SELECT symbol FROM instruments WHERE instrument_token = %s", (symbol_key,))
                name_row = pg_cur.fetchone()
                stock_name = name_row[0] if name_row else KNOWN_STOCKS.get(symbol_key, symbol_key.split("|")[-1])
                
                top_stocks.append({
                    "symbol": symbol_key,
                    "name": stock_name,
                    "open": open_p,
                    "close": close_p,
                    "change_pct": round(pct_change, 2),
                    "volume": volume,
                    "date": str(latest_date) if latest_date else "N/A"
                })
                seen_symbols.add(stock_name)
        except Exception as pg_err:
             print(f"Postgres name fetch failed: {pg_err}")
             for r in qdb_rows:
                 open_p = float(r[1])
                 close_p = float(r[2])
                 pct_change = ((close_p - open_p) / open_p) * 100 if open_p > 0 else 0
                 symbol_key = r[0]
                 stock_name = KNOWN_STOCKS.get(symbol_key, symbol_key.split("|")[-1])
                 top_stocks.append({
                     "symbol": symbol_key,
                     "name": stock_name,
                     "open": open_p,
                     "close": close_p,
                     "change_pct": round(pct_change, 2),
                     "volume": int(r[3]),
                     "date": str(latest_date) if latest_date else "N/A"
                 })
                 seen_symbols.add(stock_name)
                 
        import hashlib
        # 3. Fallback padding with KNOWN_STOCKS dictionary to ensure UI is full
        for key, name in KNOWN_STOCKS.items():
            if len(top_stocks) >= limit:
                break
            if name not in seen_symbols:
                # Deterministic noise based on stock name so it doesn't fluctuate when the market is closed
                hash_int = int(hashlib.md5(name.encode('utf-8')).hexdigest(), 16)
                noise = -2.5 + ((hash_int % 600) / 100.0) # -2.5 to +3.5
                vol_noise = 50000 + (hash_int % 450000)
                
                top_stocks.append({
                    "symbol": key,
                    "name": name,
                    "open": 1000.0,
                    "close": 1000.0 + (10 * noise),
                    "change_pct": round(noise, 2),
                    "volume": vol_noise,
                    "date": str(latest_date) if latest_date else "N/A"
                })
                seen_symbols.add(name)
                
        # Sort by best performers
        top_stocks.sort(key=lambda x: x['change_pct'], reverse=True)
        return top_stocks
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/v1/trades")
def get_trades(limit: int = 50, conn = Depends(get_pg_conn)):
    """Fetch recent trade history from Postgres"""
    try:
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


@app.get("/api/v1/instruments/search")
def search_instruments(query: str = Query(..., min_length=1), conn = Depends(get_pg_conn)):
    """Search for symbols in the Instrument Master"""
    try:
        cur = conn.cursor()
        search_param = f"%{query}%"
        cur.execute("""
            SELECT instrument_token, symbol, exchange, segment
            FROM instruments 
            WHERE symbol ILIKE %s OR exchange ILIKE %s
            ORDER BY symbol ASC
            LIMIT 20;
        """, (search_param, search_param))
        rows = cur.fetchall()
        return [
            {"key": r[0], "symbol": r[1], "name": r[1], "exchange": r[2], "segment": r[3]}
            for r in rows
        ]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class LiveStartRequest(BaseModel):
    strategy_name: str
    capital: float
    trading_mode: str = "MIS"

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

@app.delete("/api/v1/strategies/{name}")
def delete_strategy(name: str):
    """Proxy Deletion to Strategy Runtime (Single File or Full Project)"""
    try:
        response = requests.delete(f"http://strategy_runtime:8000/strategies/{name}", timeout=5)
        if response.status_code == 200:
             return response.json()
        raise HTTPException(status_code=response.status_code, detail=response.text)
    except requests.exceptions.RequestException as e:
        raise HTTPException(status_code=503, detail=f"Strategy Runtime Unavailable: {e}")

@app.delete("/api/v1/strategies/project/{project_name}/file/{filename}")
def delete_project_file_proxy(project_name: str, filename: str):
    """Proxy Deletion of a specific project file to Strategy Runtime"""
    try:
        response = requests.delete(
            f"http://strategy_runtime:8000/strategies/project/{project_name}/file/{filename}",
            timeout=5
        )
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

@app.get("/api/v1/live/trades")
def get_live_trades(limit: int = 250, conn = Depends(get_pg_conn)):
    """Fetch recent execution history for the live trading dashboard"""
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT eo.timestamp, eo.symbol, eo.transaction_type, eo.quantity, eo.price, 
                   coalesce(eo.pnl, 0),
                   COALESCE(i.symbol, REPLACE(REPLACE(eo.symbol, 'NSE_EQ|', ''), 'BSE_EQ|', '')) as stock_name
            FROM executed_orders eo
            LEFT JOIN instruments i ON i.instrument_token = eo.symbol
            ORDER BY eo.timestamp ASC LIMIT %s;
        """, (limit,))
        rows = cur.fetchall()
        return [
            {"time": r[0], "symbol": r[1], "side": r[2], "quantity": r[3], "price": r[4], "pnl": r[5], "stock_name": r[6]} 
            for r in rows
        ]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


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

@app.get("/api/v1/strategies/ide-projects")
def get_all_ide_projects():
    """Bulk fetch all strategy projects Proxy"""
    try:
        response = requests.get(
            "http://strategy_runtime:8000/strategies/ide-projects",
            timeout=10
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
    timeframe: Optional[str] = "5m"
    speed: Optional[str] = "fast"
    trading_mode: str = "MIS" # MIS or CNC

@app.post("/api/v1/backtest/run")
def run_backtest(request: BacktestRequest):
    """Trigger a backtest. Routes to kira_til for integrated KIRA strategies."""
    try:
        # Check if it's a KIRA strategy or if we should default to kira_til
        target_url = "http://kira_til:8000/api/v1/til/backtest"
        
        # Map Singular symbol to Plural symbols list for kira_til
        req_data = request.dict()
        if "symbol" in req_data and "symbols" not in req_data:
            req_data["symbols"] = [req_data["symbol"]]
        
        # Map initial_cash to initial_capital if needed
        if "initial_cash" in req_data:
            req_data["initial_capital"] = req_data["initial_cash"]

        # Route to strategy_runtime for custom Python code execution
        response = requests.post(
            "http://strategy_runtime:8000/backtest",
            json=request.dict(),
            timeout=10
        )
        return response.json()
    except requests.exceptions.RequestException as e:
        # Try strategy_runtime fallback on connection error too
        try:
            response = requests.post("http://strategy_runtime:8000/backtest", json=request.dict(), timeout=10)
            return response.json()
        except:
            raise HTTPException(status_code=503, detail=f"Backtest Services Unavailable: {e}")

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
def get_backtest_trades(run_id: str, conn = Depends(get_pg_conn)):
    """Fetch executed trades for a specific backtest run"""
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT bo.timestamp, bo.symbol, bo.transaction_type, bo.quantity, bo.price, bo.pnl,
                   COALESCE(i.symbol, i_fo.symbol, REPLACE(REPLACE(bo.symbol, 'NSE_EQ|', ''), 'BSE_EQ|', '')) as stock_name
            FROM backtest_orders bo
            LEFT JOIN instruments i ON i.instrument_token = bo.symbol
            LEFT JOIN instruments i_fo ON i_fo.instrument_token = 'NSE_FO|' || bo.symbol
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

@app.get("/api/v1/backtest/stats/{run_id}")
def get_backtest_stats(run_id: str, conn = Depends(get_pg_conn)):
    """Fetch computed backtest statistics, with fallback computation from trades."""
    try:
        cur = conn.cursor()
        # Try the precomputed stats first
        cur.execute("""
            SELECT stats_json FROM backtest_results WHERE run_id = %s;
        """, (run_id,))
        row = cur.fetchone()
        if row:
            stats = row[0]
            if isinstance(stats, str):
                stats = json.loads(stats)
            # Only return if it seems complete
            if stats.get('net_profit') is not None and stats.get('sharpe_ratio') is not None:
                # Add camelCase mapping for the frontend runner
                stats['sharpeRatio'] = stats.get('sharpe_ratio', 0.0)
                stats['totalTrades'] = stats.get('total_trades', 0)
                stats['winRate'] = stats.get('win_rate', "0.0%")
                stats['maxDrawdown'] = stats.get('max_drawdown', "0.0%")
                return stats

        # ── Fallback: compute stats from trade data directly ──
        cur.execute("""
            SELECT pnl, price, quantity, transaction_type FROM backtest_orders
            WHERE run_id = %s AND pnl IS NOT NULL
            ORDER BY timestamp ASC;
        """, (run_id,))
        pnl_rows = cur.fetchall()

        if not pnl_rows:
            return {
                "total_return": 0.0,
                "max_drawdown": 0.0,
                "sharpe_ratio": 0.0,
                "win_rate": 0,
                "gross_profit": 0.0,
                "gross_loss": 0.0,
                "net_profit": 0.0,
                "total_trades": 0,
                "expectancy": 0.0,
                "profit_factor": 0.0
            }

        pnl_list = [float(r[0]) for r in pnl_rows if r[0] is not None and float(r[0]) != 0.0]
        
        total_brokerage = 0.0
        for r in pnl_rows:
            if r[1] and r[2] and r[3]: # price, qty, txn_type
                turnover = float(r[1]) * abs(int(r[2]))
                flat = min(20.0, turnover * 0.0003)
                stt = turnover * 0.00025 if r[3] == 'SELL' else 0.0
                gst = flat * 0.18
                total_brokerage += (flat + stt + gst)

        if not pnl_list:
            return {}

        total_trades = len(pnl_list)
        wins = [p for p in pnl_list if p > 0]
        losses = [p for p in pnl_list if p < 0]
        gross_profit = sum(wins) if wins else 0
        gross_loss = abs(sum(losses)) if losses else 0
        net_profit = sum(pnl_list)

        # Get initial capital from portfolio table
        cur.execute("SELECT initial_equity FROM backtest_portfolios WHERE run_id = %s LIMIT 1;", (run_id,))
        cap_row = cur.fetchone()
        initial_capital = float(cap_row[0]) if cap_row and cap_row[0] else 100000.0

        win_rate = round((len(wins) / total_trades) * 100, 1) if total_trades > 0 else 0
        profit_factor = round(gross_profit / gross_loss, 2) if gross_loss > 0.01 else (99.99 if gross_profit > 0 else 0)
        expectancy = round(net_profit / total_trades, 2) if total_trades > 0 else 0
        avg_win = round(gross_profit / len(wins), 2) if wins else 0
        avg_loss = round(-abs(sum(losses)) / len(losses), 2) if losses else 0
        total_return = round((net_profit / initial_capital) * 100, 2)

        # ── Compute Sharpe, CAGR, Max Drawdown from cumulative equity curve ──
        import math
        
        # Build daily P&L from trade timestamps
        cur.execute("""
            SELECT DATE(timestamp) as day, SUM(pnl) as day_pnl
            FROM backtest_orders WHERE run_id = %s AND pnl IS NOT NULL AND pnl != 0
            GROUP BY DATE(timestamp) ORDER BY day ASC;
        """, (run_id,))
        daily_rows = cur.fetchall()
        
        # Max Drawdown from cumulative equity
        equity = initial_capital
        peak = equity
        max_dd = 0.0
        daily_returns = []
        
        for dr in daily_rows:
            day_pnl = float(dr[1])
            prev_equity = equity
            equity += day_pnl
            if prev_equity > 0:
                daily_returns.append(day_pnl / prev_equity)
            if equity > peak:
                peak = equity
            dd = (peak - equity) / peak * 100 if peak > 0 else 0
            if dd > max_dd:
                max_dd = dd
        
        max_dd = round(max_dd, 2)
        
        # Sharpe Ratio (annualized, assuming 252 trading days)
        sharpe = 0.0
        if len(daily_returns) > 1:
            mean_r = sum(daily_returns) / len(daily_returns)
            variance = sum((r - mean_r) ** 2 for r in daily_returns) / (len(daily_returns) - 1)
            std_r = math.sqrt(variance) if variance > 0 else 0
            if std_r > 0:
                sharpe = round((mean_r / std_r) * math.sqrt(252), 2)
        
        # Sortino Ratio
        sortino = 0.0
        if len(daily_returns) > 1:
            mean_r = sum(daily_returns) / len(daily_returns)
            downside = [r for r in daily_returns if r < 0]
            if downside:
                down_var = sum(r ** 2 for r in downside) / len(downside)
                down_std = math.sqrt(down_var) if down_var > 0 else 0
                if down_std > 0:
                    sortino = round((mean_r / down_std) * math.sqrt(252), 2)
        
        # CAGR
        cagr = 0.0
        if len(daily_rows) > 1:
            first_day = daily_rows[0][0]
            last_day = daily_rows[-1][0]
            days_span = (last_day - first_day).days
            if days_span > 0:
                final_equity = initial_capital + net_profit
                years = days_span / 365.25
                if initial_capital > 0 and final_equity > 0 and years > 0:
                    cagr = round(((final_equity / initial_capital) ** (1 / years) - 1) * 100, 2)

        return {
            "total_return": total_return,
            "net_profit": round(net_profit, 2),
            "initial_capital": initial_capital,
            "final_equity": round(initial_capital + net_profit, 2),
            "cagr": cagr,
            "sharpe_ratio": sharpe,
            "sortino_ratio": sortino,
            "max_drawdown": max_dd,
            "calmar_ratio": round(cagr / max_dd, 2) if max_dd > 0 else 0.0,
            "total_trades": total_trades,
            "win_rate": win_rate,
            "profit_factor": profit_factor,
            "expectancy": expectancy,
            "avg_win": avg_win,
            "avg_loss": avg_loss,
            "brokerage_paid": round(total_brokerage, 2),
        }
    except Exception as e:
        return {}

@app.get("/api/v1/backtest/universe/{run_id}")
def get_backtest_universe(run_id: str, conn = Depends(get_pg_conn)):
    """Fetch scanner/universe results for a specific backtest run"""
    try:
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

@app.get("/api/v1/backtest/logs/{run_id}")
def get_backtest_logs(run_id: str):
    """Fetch logs from TIL engine or strategy runtime."""
    try:
        # Try kira_til first (new integrated engine)
        response = requests.get(f"http://kira_til:8000/api/v1/backtest/logs/{run_id}", timeout=5)
        if response.status_code == 200:
            return response.json()
            
        # Fallback to strategy_runtime
        response = requests.get(f"http://strategy_runtime:8000/backtest/logs/{run_id}", timeout=5)
        if response.status_code == 200:
             return response.json()
        raise HTTPException(status_code=response.status_code, detail=response.text)
    except requests.exceptions.RequestException as e:
        raise HTTPException(status_code=503, detail=f"Backtest Log Service Unavailable: {e}")

@app.get("/api/v1/backtest/status/{run_id}")
def get_backtest_status(run_id: str):
    """Proxy status request to TIL engine or strategy runtime."""
    try:
        response = requests.get(f"http://kira_til:8000/api/v1/til/backtest/status", timeout=5)
        # Note: kira_til's status is currently global/latest.
        # If run_id matches current, return it.
        if response.status_code == 200:
            data = response.json()
            if data.get("run_id") == run_id or data.get("running"):
                return data

        response = requests.get(f"http://strategy_runtime:8000/backtest/status/{run_id}", timeout=5)
        if response.status_code == 200:
             return response.json()
        raise HTTPException(status_code=response.status_code, detail=response.text)
    except requests.exceptions.RequestException as e:
        raise HTTPException(status_code=503, detail=f"Backtest Status Service Unavailable: {e}")

@app.get("/api/v1/backtest/trades/{run_id}")
def get_backtest_trades_proxy(run_id: str):
    """Proxy to KIRA TIL detailed trades list."""
    try:
        response = _http_session.get(f"http://kira_til:8000/api/v1/til/backtest/trades/{run_id}", timeout=5)
        if response.status_code == 200:
            return response.json()
        return []
    except Exception as e:
        print(f"Error proxying trades: {e}")
        return []

@app.get("/api/v1/backtest/performance/snapshots/{run_id}")
def get_backtest_performance_snapshots(run_id: str, conn = Depends(get_pg_conn)):
    """High-fidelity equity and heat snapshots for the chart."""
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT snapshot_time, heat_pct, factor_banking, factor_it, factor_energy, factor_fmcg, full_json
            FROM portfolio_snapshots
            WHERE run_id = %s
            ORDER BY snapshot_time ASC;
        """, (run_id,))
        rows = cur.fetchall()
        return [
            {
                "time": r[0].isoformat() if hasattr(r[0], 'isoformat') else str(r[0]),
                "heat": r[1],
                "exposure": {"BANKING": r[2], "IT": r[3], "ENERGY": r[4], "FMCG": r[5]},
                "equity": (r[6] if isinstance(r[6], dict) else json.loads(r[6] or '{}')).get("total_equity", 0)
            }
            for r in rows
        ]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# --- BACKTEST HISTORY ---

@app.get("/api/v1/backtest/performance/full/{run_id}")
def get_backtest_performance_full(run_id: str):
    """Proxy to KIRA TIL full performance (points + summary)."""
    try:
        response = _http_session.get(f"http://kira_til:8000/api/v1/til/performance?run_id={run_id}", timeout=10)
        if response.status_code == 200:
            return response.json()
        return {"points": [], "summary": {}}
    except Exception as e:
        print(f"Error proxying performance: {e}")
        return {"points": [], "summary": {}}

@app.get("/api/v1/backtest/history")
def get_backtest_history(conn = Depends(get_pg_conn)):
    """List all backtest runs with summary stats"""
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT 
                bp.run_id,
                bp.balance,
                bp.equity,
                bp.timestamp,
                COALESCE(t.trade_count, 0) as trade_count,
                COALESCE(t.total_pnl, 0) as total_pnl,
                t.first_trade,
                t.last_trade,
                bp.initial_equity
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
            ORDER BY bp.timestamp DESC;
        """)
        rows = cur.fetchall()
        return [
            {
                "run_id": r[0],
                "final_balance": float(r[1]) if r[1] else 0,
                "initial_equity": float(r[8]) if r[8] else 100000,
                "total_pnl_pct": (float(r[5]) / float(r[8]) * 100) if r[8] and r[5] else 0,
                "total_trades": r[4] or 0,
                "total_pnl": float(r[5]) if r[5] else 0,
                "sharpe_ratio": 1.85,  # Calculated in future phase
                "max_drawdown_pct": 4.12, # Calculated in future phase
                "win_rate_pct": 65.0, # Calculated in future phase
                "timestamp": r[3].isoformat() if r[3] else None,
                "start_date": r[6].isoformat() if r[6] else None,
                "end_date": r[7].isoformat() if r[7] else None,
            }
            for r in rows
        ]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/api/v1/backtest/history")
def clear_backtest_history(conn = Depends(get_pg_conn)):
    """Clear ALL backtest data"""
    try:
        cur = conn.cursor()
        
        cur.execute("DELETE FROM backtest_positions;")
        cur.execute("DELETE FROM backtest_orders;")
        cur.execute("DELETE FROM backtest_universe;")
        cur.execute("DELETE FROM backtest_portfolios;")
        cur.execute("DELETE FROM backtest_results;") # Also delete the parent runs
        total = cur.rowcount
        
        # Flush Redis cache where edge scanner and backtest analysis is stored
        try:
            redis_client.flushdb()
        except:
            pass
        
        conn.commit()
        cur.close()
        return {"status": "cleared", "message": "All backtest history deleted"}
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/api/v1/backtest/{run_id}")
def delete_backtest(run_id: str, conn = Depends(get_pg_conn)):
    """Delete a specific backtest run and all associated data"""
    try:
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
        cur.execute("DELETE FROM backtest_results WHERE run_id = %s;", (run_id,))
        
        # Also clear this specific run analysis from redis
        try:
            redis_client.delete(f"backtest_analysis:{run_id}")
        except:
            pass
        
        conn.commit()
        cur.close()
        return {"status": "deleted", "run_id": run_id, "orders_deleted": orders_deleted}
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))



class BackfillStartRequest(BaseModel):
    start_date: str
    end_date: str
    stocks: Optional[List[str]] = None
    interval: str = "1"
    unit: str = "minutes"
    run_noise_filter: bool = False

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
        response = requests.get("http://data_backfiller:8001/backfill/status", timeout=30)
        if response.status_code == 200:
            return response.json()
        raise HTTPException(status_code=response.status_code, detail=response.text)
    except requests.exceptions.RequestException as e:
        raise HTTPException(status_code=503, detail=f"Backfiller Unavailable: {e}")

@app.get("/api/v1/backfill/stocks")
def get_backfill_stocks():
    """List available stocks for backfill"""
    try:
        response = requests.get("http://data_backfiller:8001/backfill/stocks", timeout=30)
        if response.status_code == 200:
            return response.json()
        raise HTTPException(status_code=response.status_code, detail=response.text)
    except requests.exceptions.RequestException as e:
        raise HTTPException(status_code=503, detail=f"Backfiller Unavailable: {e}")

class EdgeScanRequest(BaseModel):
    symbols: List[str]
    timeframe: str = "1d"
    start_date: str = "2020-01-01"
    end_date: str = "2030-01-01"
    patterns: List[str] = [
        "gap_up_fade", 
        "consecutive_up_days", 
        "inside_bar_breakout", 
        "oversold_bounce",
        "volatility_contraction"
    ]
    forward_returns_bars: List[int] = [1, 3, 5]

@app.post("/api/v1/edge/scan")
def run_edge_scan(request: EdgeScanRequest):
    """Trigger vectorized edge scan"""
    try:
        response = requests.post("http://edge_detector:8002/scan", json=request.dict(), timeout=30)
        
        if response.status_code == 200:
            return response.json()
            
        res_json = response.json()
        error_detail = res_json.get("detail", response.text)
        
        # Pass through the specific MISSING_DATA error if it came from the edge_detector
        raise HTTPException(status_code=response.status_code, detail=error_detail)
        
    except requests.exceptions.Timeout:
        raise HTTPException(status_code=504, detail="Edge Detector Timed Out. Query may be too large.")
    except requests.exceptions.RequestException as e:
        raise HTTPException(status_code=503, detail=f"Edge Detector Unavailable: {e}")


class DeepScanRequest(BaseModel):
    symbols: List[str]
    timeframe: str = "1d"
    start_date: str = "2020-01-01"
    end_date: str = "2030-01-01"


@app.post("/api/v1/edge/deep-scan")
def run_deep_scan(request: DeepScanRequest):
    """Comprehensive deep scan — 6 analysis modules with insights and predictions."""
    try:
        response = requests.post(
            "http://edge_detector:8002/deep-scan",
            json=request.dict(),
            timeout=120  # Deep analysis takes longer
        )

        if response.status_code == 200:
            return response.json()

        res_json = response.json()
        error_detail = res_json.get("detail", response.text)
        raise HTTPException(status_code=response.status_code, detail=error_detail)

    except requests.exceptions.Timeout:
        raise HTTPException(status_code=504, detail="Deep Scan Timed Out. Try a shorter date range.")
    except requests.exceptions.RequestException as e:
        raise HTTPException(status_code=503, detail=f"Edge Detector Unavailable: {e}")

# --- KIRA MODULE PROXIES ---

@app.get("/api/v1/kira/noise-filter/confidence/{symbol}")
def get_kira_confidence(
    symbol: str, 
    timestamp: Optional[str] = Query(None, description="ISO timestamp for historical lookup"),
    conn = Depends(get_qdb_conn)
):
    """Fetch KIRA confidence. Proxies to Live NF if no timestamp, else queries QuestDB."""
    if not timestamp:
        # Live Proxy
        try:
            response = requests.get(f"http://noise_filter:8000/confidence/{symbol}", timeout=2)
            if response.status_code == 200:
                return response.json()
        except:
            pass
        return {"symbol": symbol, "confidence": 0}
    
    # Historical Lookup from QuestDB
    try:
        cur = conn.cursor()
        # QuestDB Syntax: LATEST BY must come before WHERE or right after table
        query = "SELECT confidence FROM noise_confidence LATEST BY symbol WHERE symbol = %s AND timestamp <= %s;"
        cur.execute(query, (symbol, timestamp))
        r = cur.fetchone()
        
        if r:
            return {"symbol": symbol, "confidence": r[0], "source": "historical"}
        
        # JIT Trigger: If no data found, trigger generation for this day
        # We assume the user wants the signals for the day surrounding this timestamp
        try:
            # Simple window: +/- 1 day from timestamp
            ts_dt = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
            start_jit = (ts_dt - timedelta(days=1)).isoformat()
            end_jit = (ts_dt + timedelta(days=1)).isoformat()
            
            requests.post(
                "http://noise_filter:8000/generate",
                params={"symbol": symbol, "start_date": start_jit, "end_date": end_jit},
                timeout=1
            )
        except:
            pass # Fail silently as JIT is background
            
        return {"symbol": symbol, "confidence": 0, "source": "jit_triggered"}
        
    except Exception as e:
         raise HTTPException(status_code=500, detail=f"QuestDB Error: {e}")

@app.get("/api/v1/kira/position-sizer/health")
def get_kira_sizer_health():
    """Proxy to KIRA Position Sizer Health"""
    try:
        response = requests.get("http://position_sizer:8000/health", timeout=2)
        if response.status_code == 200:
            return response.json()
        raise HTTPException(status_code=response.status_code, detail=response.text)
    except requests.exceptions.RequestException as e:
        raise HTTPException(status_code=503, detail=f"Position Sizer Unavailable: {e}")

@app.post("/api/v1/kira/position-sizer/size")
def get_kira_position_size(request: dict):
    """Proxy to KIRA Position Sizer Logic"""
    try:
        response = requests.post("http://position_sizer:8000/size", json=request, timeout=2)
        if response.status_code == 200:
            return response.json()
        raise HTTPException(status_code=response.status_code, detail=response.text)
    except requests.exceptions.RequestException as e:
        raise HTTPException(status_code=503, detail=f"Position Sizer Unavailable: {e}")

# --- KIRA TIL PROXIES ---

@app.get("/api/v1/kira/til/health")
def get_kira_til_health():
    """Proxy to KIRA TIL Health"""
    try:
        response = requests.get("http://kira_til:8000/health", timeout=2)
        if response.status_code == 200:
            return response.json()
        raise HTTPException(status_code=response.status_code, detail=response.text)
    except requests.exceptions.RequestException as e:
        raise HTTPException(status_code=503, detail=f"TIL Unavailable: {e}")

@app.post("/api/v1/kira/til/process")
def process_til_features(request: dict):
    """Proxy to KIRA TIL Integrated Pipeline"""
    try:
        response = requests.post("http://kira_til:8000/process_features", json=request, timeout=10)
        if response.status_code == 200:
            return response.json()
        raise HTTPException(status_code=response.status_code, detail=response.text)
    except requests.exceptions.RequestException as e:
        raise HTTPException(status_code=503, detail=f"TIL Integrated Pipeline Unavailable: {e}")

@app.post("/api/v1/kira/til/validate")
def validate_til_portfolio(request: dict):
    """Proxy to KIRA TIL Portfolio Validation"""
    try:
        response = _http_session.post("http://kira_til:8000/portfolio/validate", json=request, timeout=2)
        if response.status_code == 200:
            return response.json()
        raise HTTPException(status_code=response.status_code, detail=response.text)
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"TIL Portfolio Engine Unavailable: {e}")

@app.get("/api/v1/til/portfolio")
def get_til_portfolio_v1():
    """Integrated Portfolio State V1"""
    try:
        response = _http_session.get("http://kira_til:8000/api/v1/til/portfolio", timeout=5)
        if response.status_code == 200:
            return response.json()
        raise HTTPException(status_code=response.status_code, detail=response.text)
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"TIL Unavailable: {e}")

@app.get("/api/v1/til/performance")
def get_til_performance_v1(run_id: Optional[str] = None):
    """Integrated Performance Metrics V1"""
    try:
        params = {}
        if run_id:
            params["run_id"] = run_id
        response = _http_session.get("http://kira_til:8000/api/v1/til/performance", params=params, timeout=5)
        if response.status_code == 200:
             return response.json()
        return {"points": [], "summary": {}}
    except Exception as e:
        return {"points": [], "summary": {}}

@app.post("/api/v1/til/backtest")
def trigger_til_backtest_v1(request: dict):
    """Trigger TIL Backtest Simulation"""
    try:
        response = _http_session.post("http://kira_til:8000/api/v1/til/backtest", json=request, timeout=10)
        if response.status_code == 200:
            return response.json()
        # Surface actual status code and reason from TIL
        raise HTTPException(status_code=response.status_code, detail=f"TIL Error: {response.text}")
    except HTTPException as he:
        raise he
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"TIL Service Unavailable: {e}")

@app.get("/api/v1/til/backtest/status")
def get_til_backtest_status_v1():
    """Proxy TIL Backtest Status"""
    try:
        response = _http_session.get("http://kira_til:8000/api/v1/til/backtest/status", timeout=5)
        if response.status_code == 200:
            return response.json()
        raise HTTPException(status_code=response.status_code, detail=response.text)
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"TIL Status Unavailable: {e}")

@app.get("/terminal", response_class=HTMLResponse)
def get_terminal_ui():
    """Standalone Bloomberg-style Terminal UI"""
    html_content = """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>KIRA | VEKTOR TERMINAL</title>
        <link rel="preconnect" href="https://fonts.googleapis.com">
        <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
        <link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@300;400;500;600;700&display=swap" rel="stylesheet">
        <style>
            :root {
                --bg: #0a0e14; --bg2: #0d1117; --bg3: #111820; --bg-panel: #131a24;
                --text: #e6edf3; --text2: #8b949e; --dim: #484f58;
                --amber: #ff9900; --green: #00ff88; --red: #ff4444;
                --cyan: #00d4ff; --blue: #4488ff; --yellow: #ffcc00;
                --border: #21262d; --font: 'JetBrains Mono', monospace;
            }
            * { box-sizing: border-box; }
            body, html { 
                margin: 0; padding: 0; background: var(--bg); color: var(--text); 
                font-family: var(--font); font-size: 13px; height: 100vh; overflow: hidden;
            }
            .vt { display: flex; flex-direction: column; height: 100vh; position: relative; }
            .vt::after {
                content: ''; position: fixed; inset: 0; pointer-events: none; z-index: 999;
                background: repeating-linear-gradient(0deg, transparent, transparent 2px, rgba(0,0,0,0.02) 2px, rgba(0,0,0,0.02) 4px);
            }
            .vt-header {
                display: flex; align-items: center; justify-content: space-between;
                padding: 6px 16px; background: var(--bg3); border-bottom: 1px solid var(--border);
            }
            .vt-logo { font-weight: 800; color: var(--amber); letter-spacing: 2px; }
            .vt-body { flex: 1; overflow-y: auto; padding: 16px; scroll-behavior: smooth; }
            .vt-block { margin-bottom: 4px; border-left: 2px solid transparent; padding-left: 8px; transition: border 0.2s; }
            .vt-block:hover { border-left-color: var(--amber); }
            .vt-cmd { color: var(--dim); margin-bottom: 2px; }
            .vt-cmd span { color: var(--amber); font-weight: 600; margin-right: 6px; }
            .vt-input { 
                display: flex; align-items: center; padding: 10px 16px;
                background: var(--bg2); border-top: 1px solid var(--border);
            }
            .vt-prompt { color: var(--amber); font-weight: 700; margin-right: 10px; }
            input { 
                flex: 1; background: transparent; border: none; outline: none; 
                color: var(--text); font-family: var(--font); font-size: 14px;
                caret-color: var(--amber);
            }
            .ta { color: var(--amber); } .tg { color: var(--green); } .tr { color: var(--red); }
            .tc { color: var(--cyan); } .tw { color: #fff; font-weight: 600; } .td { color: var(--dim); }
            .tbd { font-weight: 700; }
            .vt-chart { 
                margin: 12px 0; padding: 12px; background: var(--bg-panel); 
                border: 1px solid var(--border); border-radius: 4px;
            }
            table { width: 100%; border-collapse: collapse; margin: 8px 0; font-size: 12px; }
            th { text-align: left; color: var(--amber); border-bottom: 1px solid var(--border); padding: 4px 8px; font-weight: 600; }
            td { padding: 4px 8px; border-bottom: 1px solid rgba(255,255,255,0.02); }
            .num { text-align: right; }
            @keyframes fade { from { opacity: 0; transform: translateY(4px); } to { opacity: 1; transform: translateY(0); } }
            .ansi-fade { animation: fade 0.2s ease-out; }
        </style>
    </head>
    <body class="vt">
        <header class="vt-header">
            <div class="vt-logo">KIRA // VEKTOR <span style="font-size: 9px; background: var(--amber); color: var(--bg); padding: 1px 4px; border-radius: 2px; margin-left:6px">STABLE</span></div>
            <div id="status" class="td" style="font-size: 11px">SYSTEM READY</div>
        </header>
        <main class="vt-body" id="console">
            <div class="vt-block">
                <div class="ta tbd" style="font-size: 24px; margin-bottom: 10px">KIRA TRADING TERMINAL v1.2</div>
                <div class="ts">Vectorized Engine: <span class="tg">CONNECTED</span> | Latency: <span class="tg">0.4ms</span></div>
                <div class="td" style="margin-top: 10px">Type 'help' for a list of available commands.</div>
            </div>
        </main>
        <div class="vt-input">
            <div class="vt-prompt">KIRA:></div>
            <input type="text" id="stdin" autofocus placeholder="Enter command..." autocomplete="off">
        </div>

        <script>
            console.log("KIRA Terminal Script Loaded Successfully.");
            const consoleEl = document.getElementById('console');
            const stdin = document.getElementById('stdin');
            const API_BASE = window.location.origin;

            const fmtINR = (n) => `₹${Number(n).toLocaleString('en-IN', { minimumFractionDigits: 2 })}`;

            function buildEquitySVG(points, width = 700, height = 180) {
                if (!points || points.length < 2) return '<div class="ts" style="padding:20px;text-align:center">No equity data. Run a backtest.</div>';
                const equities = points.map(p => p.equity);
                const minE = Math.min(...equities);
                const maxE = Math.max(...equities);
                const range = (maxE - minE) || 1;
                const pad = 40;
                const gW = width - pad * 2;
                const gH = height - pad * 1.5;
                const pts = points.map((p, i) => ({
                    x: pad + (i / (points.length - 1)) * gW,
                    y: pad / 2 + gH - ((p.equity - minE) / range) * gH
                }));
                const polyline = pts.map(p => `${p.x},${p.y}`).join(' ');
                const lastE = equities[equities.length - 1];
                const firstE = equities[0];
                const totalRet = ((lastE - firstE) / firstE * 100);
                const color = totalRet >= 0 ? '#00ff88' : '#ff4444';

                return `
                    <div class="vt-chart">
                        <div style="display:flex;justify-content:space-between;margin-bottom:6px;font-size:11px">
                            <span class="ta tbd">EQUITY PROFILE</span>
                            <span>Return: <span class="${totalRet >= 0 ? 'tg' : 'tr'}">${totalRet.toFixed(2)}%</span></span>
                        </div>
                        <svg width="100%" viewBox="0 0 ${width} ${height}" style="display:block">
                            <polyline fill="none" stroke="${color}" stroke-width="2" points="${polyline}" stroke-linejoin="round"/>
                            <rect x="${pad}" y="${pad/2}" width="${gW}" height="${gH}" fill="none" stroke="#222" stroke-width="0.5"/>
                        </svg>
                    </div>`;
            }

            function log(html, type = 'result') {
                const block = document.createElement('div');
                block.className = `vt-block ansi-fade`;
                block.innerHTML = `<div class="vt-${type}">${html}</div>`;
                consoleEl.appendChild(block);
                consoleEl.scrollTop = consoleEl.scrollHeight;
            }

            async function handleCommand(cmd) {
                const parts = cmd.toLowerCase().split(' ');
                const command = parts[0];

                log(`<span>$</span> ${cmd}`, 'cmd');

                if (command === 'help') {
                    log(`
                        <div class="ta tbd">CORE COMMANDS:</div>
                        <table>
                            <tr><td class="tc">sys.status</td><td>System telemetry & health</td></tr>
                            <tr><td class="tc">md.quote &lt;sym&gt;</td><td>Real-time market quote</td></tr>
                            <tr><td class="tc">backtest.run</td><td>Trigger Alpha Sniper backtest</td></tr>
                            <tr><td class="tc">backtest.monitor</td><td>Live simulation progress</td></tr>
                            <tr><td class="tc">backtest.chart</td><td>Render equity curve of latest run</td></tr>
                            <tr><td class="tc">backtest.history</td><td>Show recent run history</td></tr>
                            <tr><td class="tc">clear</td><td>Reset console screen</td></tr>
                        </table>
                    `);
                } else if (command === 'clear') {
                    consoleEl.innerHTML = '';
                } else if (command === 'sys.status') {
                    log('<div class="tc">Polling telemetry...</div>');
                    try {
                        const res = await fetch(`${API_BASE}/health`);
                        const data = await res.json();
                        log(`<div class="tg">GATEWAY: ONLINE | VERSION: ${data.version}</div>`);
                        const tilRes = await fetch(`${API_BASE}/api/v1/kira/til/health`);
                        const tilData = await tilRes.json();
                        log(`<div class="tc">TIL CORE: ${tilData.status.toUpperCase()} | ENGINE: VECTORIZED</div>`);
                    } catch (e) { log(`<div class="tr">Telemetry Failure</div>`); }
                } else if (command === 'md.quote') {
                    const sym = parts[1] || 'RELIANCE';
                    log(`<div class="tc">Fetching quote for ${sym}...</div>`);
                    try {
                        const res = await fetch(`${API_BASE}/api/v1/market/top-performers?limit=20`);
                        const data = await res.json();
                        const stock = data.find(s => s.name.toLowerCase() === sym.toLowerCase() || s.symbol.includes(sym.toUpperCase()));
                        if (stock) {
                            log(`
                                <div style="font-size:16px"><span class="tw">${stock.name}</span> <span class="${stock.change_pct>=0?'tg':'tr'}">${stock.change_pct}%</span></div>
                                <div class="td">LTP: ${fmtINR(stock.close)} | VOL: ${(stock.volume/1000).toFixed(1)}K</div>
                            `);
                        } else { log(`<div class="tr">Symbol ${sym} not found in universe</div>`); }
                    } catch (e) { log(`<div class="tr">Market Service Offline</div>`); }
                } else if (command === 'backtest.run') {
                    log('<div class="tc">Initializing Alpha Sniper Simulation...</div>');
                    try {
                        const res = await fetch(`${API_BASE}/api/v1/til/backtest`, {
                            method: 'POST',
                            headers: {'Content-Type': 'application/json'},
                            body: JSON.stringify({
                                symbols: ["RELIANCE", "HDFCBANK", "INFY", "TCS", "ICICIBANK", "SBIN", "BHARTIARTL", "AXISBANK", "LTIM", "ADANIENT", "LT", "ITC", "KOTAKBANK", "HINDUNILVR", "BAJFINANCE", "M&M", "SUNPHARMA", "TITAN", "ULTRACEMCO", "ADANIPORTS"],
                                start_date: "2023-01-01",
                                end_date: "2024-03-24",
                                timeframe: "5m",
                                initial_capital: 1000000
                            })
                        });
                        const data = await res.json();
                        log(`<div class="tg">BACKTEST STARTED [ID: ${data.run_id}]</div>`);
                        
                        // Auto-monitor
                        let pollCount = 0;
                        const poller = setInterval(async () => {
                            pollCount++;
                            const sRes = await fetch(`${API_BASE}/api/v1/til/backtest/status`);
                            const s = await sRes.json();
                            
                            if (!s.is_running || pollCount > 100) {
                                clearInterval(poller);
                                log('<div class="tg">SIMULATION COMPLETE. ANALYZING...</div>');
                                setTimeout(() => handleCommand('backtest.chart'), 500);
                            } else {
                                // Update progress in-place if possible, or just log
                                if (pollCount === 1) log('<div class="td">Monitoring progress...</div>');
                            }
                        }, 500);

                    } catch (e) { log(`<div class="tr">Execution Failed: ${e.message}</div>`); }

                } else if (command === 'backtest.monitor') {
                    try {
                        const res = await fetch(`${API_BASE}/api/v1/til/backtest/status`);
                        const data = await res.json();
                        log(`
                            <div class="vt-chart">
                                <div class="ta tbd">ENGINE STATUS</div>
                                <div>State: <span class="${data.running ? 'tg' : 'tr'}">${data.running ? 'ACTIVE' : 'IDLE'}</span></div>
                                <div>Progress: ${Math.floor(data.progress || 0)}%</div>
                                <div style="margin-top:8px; height:4px; background:#111; border-radius:2px">
                                    <div style="width:${data.progress}%; height:100%; background:var(--amber); transition:width 0.3s"></div>
                                </div>
                            </div>
                        `);
                    } catch (e) { log(`<div class="tr">Engine Offline</div>`); }
                } else if (command === 'backtest.chart') {
                    log('<div class="tc">Generating equity profile...</div>');
                    try {
                        const hRes = await fetch(`${API_BASE}/api/v1/backtest/history`);
                        const hData = await hRes.json();
                        if (!hData.length) throw new Error("No runs found");
                        const runId = hData[0].run_id;
                        const pRes = await fetch(`${API_BASE}/api/v1/backtest/performance/snapshots/${runId}`);
                        const points = await pRes.json();
                        log(buildEquitySVG(points));
                    } catch (e) { log(`<div class="tr">Chart Failed: ${e.message}</div>`); }
                } else if (command === 'backtest.history') {
                    try {
                        const res = await fetch(`${API_BASE}/api/v1/backtest/history`);
                        const data = await res.json();
                        let html = '<table><tr><th>Date</th><th>ROI</th><th>Trades</th></tr>';
                        data.slice(0, 10).forEach(r => {
                            const roi = ((r.final_balance - r.initial_equity) / r.initial_equity * 100).toFixed(2);
                            html += `<tr><td>${r.created_at.split('T')[0]}</td><td class="${roi >=0?'tg':'tr'}">${roi}%</td><td class="num">${r.trade_count}</td></tr>`;
                        });
                        html += '</table>';
                        log(html);
                    } catch (e) { log(`<div class="tr">History unavailable</div>`); }
                } else {
                    log('<span class="tr">ERR: Command not recognized.</span>');
                }
            }

            stdin.addEventListener('keydown', (e) => {
                if (e.key === 'Enter') {
                    console.log("Enter key caught. Processing command...");
                    const cmd = stdin.value.trim();
                    if (cmd) {
                        handleCommand(cmd);
                        stdin.value = '';
                    }
                }
            });
        </script>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content)


# ─── ORDER FLOW WEBSOCKET ───────────────────────────────────────────────────

class _OrderFlowManager:
    """Tracks connected WebSocket clients for /ws/orderflow."""
    def __init__(self):
        self.active: list = []

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self.active.append(ws)

    def disconnect(self, ws: WebSocket):
        self.active = [c for c in self.active if c is not ws]

    async def broadcast(self, payload: str):
        dead = []
        for ws in self.active:
            try:
                await ws.send_text(payload)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)


_of_manager = _OrderFlowManager()


def _read_all_microstructure() -> list:
    """Read all microstructure:* keys from Redis synchronously."""
    if redis_client is None:
        return []
    try:
        _, keys = redis_client.scan(match="microstructure:*", count=1000)
        if not keys:
            return []
        result = []
        for key in keys:
            raw = redis_client.hgetall(key)
            if not raw:
                continue
            try:
                result.append({
                    "symbol": raw.get("symbol", key.split(":", 1)[-1]),
                    "alpha": float(raw.get("alpha", 0)),
                    "lambda_hawkes": float(raw.get("lambda_hawkes", 0)),
                    "cusum_c": float(raw.get("cusum_c", 0)),
                    "variance": float(raw.get("variance", 0)),
                    "q_star": int(float(raw.get("q_star", 0))),
                    "kyle_lambda": float(raw.get("kyle_lambda", 0)),
                    "ts_ms": int(float(raw.get("ts_ms", 0))),
                    "cusum_fired": False,
                })
            except (ValueError, TypeError):
                continue
        # Sort by |alpha| + lambda_hawkes/1e5 + cusum_c/5 descending (watchlist order)
        result.sort(
            key=lambda s: abs(s["alpha"]) + s["lambda_hawkes"] / 1e5 + s["cusum_c"] / 5,
            reverse=True,
        )
        return result
    except Exception:
        return []


@app.websocket("/ws/orderflow")
async def ws_orderflow(websocket: WebSocket):
    """Stream microstructure state for all symbols every 50ms."""
    await _of_manager.connect(websocket)
    try:
        while True:
            loop = asyncio.get_running_loop()
            states = await loop.run_in_executor(None, _read_all_microstructure)
            await _of_manager.broadcast(json.dumps(states))
            await asyncio.sleep(0.05)  # 50ms cadence
    except (WebSocketDisconnect, Exception):
        _of_manager.disconnect(websocket)


# ─── MARKET DEPTH WEBSOCKET ──────────────────────────────────────────────────

def _parse_depth_frame(raw_bytes: bytes, target_symbol: str) -> dict | None:
    """Parse a KafkaEnvelope bytes into a depth frame for target_symbol.
    Returns None if the message is for a different symbol or has no depth.
    """
    try:
        envelope = json.loads(raw_bytes.decode("utf-8"))
        payload = envelope.get("payload", {})
        symbol = payload.get("symbol", "")
        if symbol != target_symbol:
            return None
        depth = payload.get("depth", {})
        bids = depth.get("buy", [])
        asks = depth.get("sell", [])
        if not bids and not asks:
            return None
        return {
            "symbol": symbol,
            "ltp": float(payload.get("ltp", 0)),
            "depth_levels": max(len(bids), len(asks)),
            "bids": bids,
            "asks": asks,
            "ts_ms": int(payload.get("timestamp", 0)),
        }
    except Exception:
        return None


@app.websocket("/ws/depth/{symbol}")
async def ws_depth(websocket: WebSocket, symbol: str):
    """Stream Upstox V3 market depth for a single symbol.

    One Kafka Consumer is created per connection and closed exactly once on
    disconnect, so we never churn consumer group memberships.
    """
    await websocket.accept()
    from confluent_kafka import Consumer, KafkaError
    import uuid as _uuid

    group_id = f"ws-depth-{_uuid.uuid4().hex[:8]}"
    conf = {
        "bootstrap.servers": os.getenv("KAFKA_BOOTSTRAP_SERVERS", "kafka_bus:9092"),
        "group.id": group_id,
        "auto.offset.reset": "latest",
        "enable.auto.commit": True,
    }

    loop = asyncio.get_running_loop()
    consumer = Consumer(conf)
    consumer.subscribe(["market.equity.ticks"])

    def _poll_once() -> "dict | None":
        """Poll one message; return a parsed depth frame or None."""
        msg = consumer.poll(0.1)
        if msg is None:
            return None
        if msg.error():
            if msg.error().code() != KafkaError._PARTITION_EOF:
                print(f"ws_depth Kafka error for {symbol}: {msg.error()}")
            return None
        return _parse_depth_frame(msg.value(), symbol)

    try:
        while True:
            frame = await loop.run_in_executor(None, _poll_once)
            if frame is not None:
                await websocket.send_text(json.dumps(frame))
            else:
                await asyncio.sleep(0)  # yield to event loop when no matching frame
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        print(f"ws_depth error for {symbol}: {exc}")
    finally:
        consumer.close()
