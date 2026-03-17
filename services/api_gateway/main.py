import os
import psycopg2
from fastapi import FastAPI, HTTPException, Query, Depends
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
from typing import List, Optional
import requests
from pydantic import BaseModel
from typing import Optional, Dict
import json
from datetime import datetime, timedelta
from confluent_kafka import Producer
from kira_shared.kafka.schemas import KafkaEnvelope
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
    limit: int = Query(10, le=50, description="Number of top stocks to return"),
    conn = Depends(get_qdb_conn),
    pg_conn = Depends(get_pg_conn)
):
    """Fetch yesterday's top performing stocks by % change from QuestDB"""
    try:
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
            ORDER BY ((last(close) - first(open)) / CASE WHEN first(open) = 0 THEN 1 ELSE first(open) END) DESC
            LIMIT {limit};
        """)
        qdb_rows = cur.fetchall()
        
        if not qdb_rows:
            return []
            
        # 3. Enhance with Postgres instrument metadata for human-readable names
        top_stocks = []
        try:
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

        # If strategy_name suggests traditional, we could route elsewhere, 
        # but for now, we point to the optimized kira_til engine.
        response = requests.post(
            target_url,
            json=req_data,
            timeout=10 
        )
        if response.status_code == 200:
             return response.json()
        else:
             # Fallback to strategy_runtime if kira_til fails or doesn't handle this type
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
            # Fallback to local computation if stats are missing or incomplete
            # But if we have net_profit, it's a TIL run, so we can use it.
            if stats.get('net_profit') is not None:
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

        win_rate = round((len(wins) / total_trades) * 100, 1) if total_trades > 0 else 0
        profit_factor = round(gross_profit / gross_loss, 2) if gross_loss > 0.01 else (99.99 if gross_profit > 0 else 0)
        expectancy = round(net_profit / total_trades, 2) if total_trades > 0 else 0
        avg_win = round(gross_profit / len(wins), 2) if wins else 0
        avg_loss = round(-abs(sum(losses)) / len(losses), 2) if losses else 0
        total_return = round((net_profit / 100000) * 100, 2)

        return {
            "total_return": total_return,
            "net_profit": round(net_profit, 2),
            "cagr": 0.0,
            "sharpe_ratio": 0.0,
            "sortino_ratio": 0.0,
            "max_drawdown": 0.0,
            "max_dd_duration": 0,
            "calmar_ratio": 0.0,
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
                "time": r[0],
                "heat": r[1],
                "exposure": {"BANKING": r[2], "IT": r[3], "ENERGY": r[4], "FMCG": r[5]},
                "equity": json.loads(r[6]).get("total_equity") if r[6] else 0
            }
            for r in rows
        ]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# --- BACKTEST HISTORY ---

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
        raise HTTPException(status_code=503, detail=f"TIL Integrated Pipeline e Unavailable: {e}")@app.post("/api/v1/kira/til/validate")
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
        response = _http_session.post("http://kira_til:8000/api/v1/til/backtest", json=request, timeout=5)
        if response.status_code == 200:
            return response.json()
        raise HTTPException(status_code=response.status_code, detail=response.text)
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"TIL Unavailable: {e}")

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

@app.get("/api/v1/kira/til/portfolio/state")
def get_til_portfolio_state():
    """Proxy to KIRA TIL Portfolio State"""
    try:
        response = _http_session.get("http://kira_til:8000/api/v1/til/portfolio", timeout=2)
        if response.status_code == 200:
            return response.json()
        raise HTTPException(status_code=response.status_code, detail=response.text)
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"TIL Portfolio Engine Unavailable: {e}")
