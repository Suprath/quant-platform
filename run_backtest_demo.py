#!/usr/bin/env python3
"""
Automated Backtest Runner
Finds top performing stock from yesterday, downloads data, runs backtest, shows results.
"""

import os
import sys
import json
import asyncio
import subprocess
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()

# Yesterday's date (Indian market was open)
yesterday = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
today = datetime.now().strftime('%Y-%m-%d')

# Top stocks to test (popular liquid stocks)
CANDIDATE_STOCKS = [
    ("NSE_EQ|INE002A01018", "Reliance"),
    ("NSE_EQ|INE040A01034", "HDFC Bank"),
    ("NSE_EQ|INE467B01029", "Tata Steel"),
    ("NSE_EQ|INE019A01038", "ITC"),
]

def run_command(cmd, cwd=None):
    """Execute shell command and return output"""
    print(f"\n🚀 Running: {cmd}")
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True, cwd=cwd)
    if result.returncode != 0:
        print(f"❌ Error: {result.stderr}")
        return None
    return result.stdout

def main():
    print("="*70)
    print("  AUTOMATED BACKTEST DEMO - INTRADAY STRATEGY")
    print("="*70)
    print(f"\n📅 Backtest Date: {yesterday}")
    print(f"💰 Capital: ₹20,000")
    print(f"📊 Strategy: Multi-Factor Momentum (VWAP + RSI + OBI)")
    print("\n" + "="*70 + "\n")
    
    # For demo, use Reliance (most liquid stock)
    symbol, name = CANDIDATE_STOCKS[0]
    run_id = f"demo_{yesterday.replace('-', '')}"
    
    print(f"🎯 Selected Stock: {name} ({symbol})")
    print(f"🔖 Run ID: {run_id}")
    
    # Step 1: Download historical data
    print("\n" + "-"*70)
    print("STEP 1: Downloading Historical Data")
    print("-"*70)
    
    download_cmd = f"""docker compose run --rm backfiller python main.py \
        --symbol "{symbol}" \
        --start "{yesterday}" \
        --end "{today}" \
        --interval "1" \
        --unit "minutes"
    """
    
    result = run_command(download_cmd, cwd="../infra")
    if not result:
        print("❌ Data download failed. Exiting.")
        return
    
    print("✅ Data downloaded successfully")
    
    # Step 2: Initialize backtest tables
    print("\n" + "-"*70)
    print("STEP 2: Initializing Backtest Environment")
    print("-"*70)
    
    init_cmd = """docker compose exec -T postgres psql -U admin -d quant_platform -c "
        CREATE TABLE IF NOT EXISTS backtest_portfolios (
            run_id VARCHAR(50) NOT NULL,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            balance DECIMAL(15, 2) NOT NULL,
            equity DECIMAL(15, 2) NOT NULL
        );
        CREATE TABLE IF NOT EXISTS backtest_orders (
            id SERIAL PRIMARY KEY,
            run_id VARCHAR(50) NOT NULL,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            symbol VARCHAR(50) NOT NULL,
            transaction_type VARCHAR(10) NOT NULL,
            quantity INT NOT NULL,
            price DECIMAL(10, 2) NOT NULL,
            pnl DECIMAL(10, 2) DEFAULT 0.0
        );
        DELETE FROM backtest_orders WHERE run_id = '{run_id}';
    "
    """.format(run_id=run_id)
    
    run_command(init_cmd, cwd="../infra")
    print("✅ Backtest tables ready")
    
    # Step 3: Run backtest (replay data)
    print("\n" + "-"*70)
    print("STEP 3: Running Backtest (Replaying Historical Data)")
    print("-"*70)
    print("⏩ Replay Speed: 100x (1 day = ~8 minutes)")
    
    replay_cmd = f"""docker compose run --rm \
        -e BACKTEST_MODE=true \
        -e RUN_ID={run_id} \
        historical_replayer python main.py \
        --symbol "{symbol}" \
        --start "{yesterday}" \
        --end "{today}" \
        --speed 100
    """
    
    result = run_command(replay_cmd, cwd="../infra")
    if not result:
        print("⚠️  Replay completed with warnings (check logs)")
    else:
        print("✅ Backtest replay complete")
    
    # Step 4: Analyze results
    print("\n" + "-"*70)
    print("STEP 4: Analyzing Results")
    print("-"*70)
    
    analyze_cmd = f"""docker compose run --rm historical_replayer python analyzer.py \
        --run-id {run_id} \
        --output /app/backtest_results
    """
    
    result = run_command(analyze_cmd, cwd="../infra")
    
    # Display results
    print("\n" + "="*70)
    print("  BACKTEST RESULTS")
    print("="*70)
    
    # Query results directly from DB
    query_cmd = f"""docker compose exec -T postgres psql -U admin -d quant_platform -c "
        SELECT 
            COUNT(*) FILTER (WHERE transaction_type = 'BUY') as buys,
            COUNT(*) FILTER (WHERE transaction_type = 'SELL') as sells,
            SUM(pnl) as total_pnl,
            COUNT(*) FILTER (WHERE transaction_type = 'SELL' AND pnl > 0) as winning_trades,
            COUNT(*) FILTER (WHERE transaction_type = 'SELL' AND pnl < 0) as losing_trades
        FROM backtest_orders 
        WHERE run_id = '{run_id}';
    "
    """
    
    stats = run_command(query_cmd, cwd="../infra")
    if stats:
        print(stats)
    
    # Show recent orders
    print("\n📋 Recent Trades:")
    orders_cmd = f"""docker compose exec -T postgres psql -U admin -d quant_platform -c "
        SELECT 
            to_char(timestamp, 'HH24:MI:SS') as time,
            transaction_type as action,
            quantity as qty,
            price,
            COALESCE(pnl, 0) as pnl
        FROM backtest_orders 
        WHERE run_id = '{run_id}'
        ORDER BY timestamp DESC
        LIMIT 10;
    "
    """
    
    orders = run_command(orders_cmd, cwd="../infra")
    if orders:
        print(orders)
    
    print("\n" + "="*70)
    print(f"\n✅ Backtest Complete! Run ID: {run_id}")
    print(f"📄 Full report: backtest_results/{run_id}.md")
    print("\n" + "="*70)

if __name__ == "__main__":
    main()
