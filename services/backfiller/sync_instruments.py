import os
import requests
import csv
import gzip
import io
import psycopg2
import re
from datetime import datetime

# --- CONFIG ---
UPSTOX_INSTRUMENTS_URL = "https://assets.upstox.com/market-quote/instruments/exchange/complete.csv.gz"

def get_pg_conn():
    host = os.getenv("POSTGRES_HOST", "postgres_metadata")
    return psycopg2.connect(
        host=host, 
        port=5432, 
        user="admin", 
        password="password123", 
        database="quant_platform"
    )

def sync_fo_instruments():
    print("🚀 Downloading NSE_FO instruments from Upstox...")
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        response = requests.get(UPSTOX_INSTRUMENTS_URL, headers=headers)
        response.raise_for_status()
        
        # Decompress GZ in memory
        with gzip.GzipFile(fileobj=io.BytesIO(response.content)) as gz:
            csv_content = gz.read().decode('utf-8')
            
        reader = csv.DictReader(io.StringIO(csv_content))
        
        conn = get_pg_conn()
        cur = conn.cursor()
        
        # Fetch equity symbols for matching OPTSTK underlying
        cur.execute("SELECT symbol FROM instruments WHERE segment IN ('EQUITY')")
        equity_symbols_list = [row[0] for row in cur.fetchall() if row[0]]
        # Sort by length descending, so we match longer prefixes first (e.g. SENSEX50 before SENSEX)
        equity_symbols_list.sort(key=len, reverse=True)
        print(f"✅ Loaded {len(equity_symbols_list)} equity symbols for prefix-matching.")
        
        # Ensure schema
        cur.execute("""
            CREATE TABLE IF NOT EXISTS instruments (
                instrument_token VARCHAR(255) PRIMARY KEY, 
                exchange VARCHAR(50),
                segment VARCHAR(50), 
                symbol VARCHAR(50),
                expiry DATE NULL,
                strike DOUBLE PRECISION NULL,
                option_type VARCHAR(10) NULL,
                underlying_symbol VARCHAR(50) NULL,
                lot_size INT NULL
            );
        """)
        
        insert_count = 0
        update_count = 0
        
        print("💾 Upserting to Postgres...")
        row_idx = 0
        for row in reader:
            row_idx += 1
            token = row['instrument_key']
            exchange = row['exchange']
            segment = row['instrument_type'] # e.g. OPTIDX, OPTSTK, FUTIDX, FUTSTK
            symbol = row['tradingsymbol']
            
            # F&O specific fields
            expiry_str = row.get('expiry')
            expiry_date = None
            if expiry_str:
                # Upstox date format: YYYY-MM-DD
                try:
                    expiry_date = datetime.strptime(expiry_str, "%Y-%m-%d").date()
                except ValueError:
                    pass
            
            strike = row.get('strike')
            strike_val = float(strike) if strike else None
            
            option_type = row.get('option_type') # CE or PE
            if option_type and option_type.upper() not in ('CE', 'PE'):
                option_type = None
                
            underlying = None
            if segment in ('OPTIDX', 'FUTIDX', 'OPTSTK', 'FUTSTK'):
                ts = row['tradingsymbol']
                # Extract everything before the 2-digit year (e.g. 26) and 3-char Month
                m = re.match(r"^([A-Z0-9\-&]+?)\d{2}[A-Z]{3}", ts)
                if m:
                    underlying = m.group(1)
            
            lot_size = row.get('lot_size')
            lot_size_val = int(lot_size) if lot_size else 1
            
            if underlying and insert_count < 10:
                 print(f"DEBUG [{segment}]: Setting {ts} underlying = {underlying}")
                 
            cur.execute("""
                INSERT INTO instruments 
                (instrument_token, exchange, segment, symbol, expiry, strike, option_type, underlying_symbol, lot_size)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (instrument_token) DO UPDATE 
                SET symbol = EXCLUDED.symbol,
                    expiry = EXCLUDED.expiry,
                    strike = EXCLUDED.strike,
                    option_type = EXCLUDED.option_type,
                    underlying_symbol = EXCLUDED.underlying_symbol,
                    lot_size = EXCLUDED.lot_size;
            """, (token, exchange, segment, symbol, expiry_date, strike_val, option_type, underlying, lot_size_val))
            insert_count += 1
            
        conn.commit()
        cur.close()
        conn.close()
        print(f"✅ Successfully processed {insert_count} F&O instruments.")
        
    except Exception as e:
        print(f"❌ Failed to sync instruments: {e}")

if __name__ == "__main__":
    sync_fo_instruments()
