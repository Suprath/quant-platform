#!/bin/bash
# Automated Backtest Demo - Shell Script Version
# No Python dependencies required on host

set -e

echo "======================================================================"
echo "  AUTOMATED BACKTEST DEMO - INTRADAY STRATEGY"
echo "======================================================================"

# Configuration
YESTERDAY=$(date -v-1d +%Y-%m-%d 2>/dev/null || date -d "yesterday" +%Y-%m-%d)
TODAY=$(date +%Y-%m-%d)
SYMBOL="NSE_EQ|INE002A01018"
NAME="Reliance"
RUN_ID="demo_$(echo $YESTERDAY | tr -d '-')"

echo ""
echo "📅 Backtest Date: $YESTERDAY"
echo "💰 Capital: ₹20,000"
echo "📊 Strategy: Multi-Factor Momentum (VWAP + RSI + OBI)"
echo "🎯 Stock: $NAME ($SYMBOL)"
echo "🔖 Run ID: $RUN_ID"
echo ""
echo "======================================================================"

# Step 1: Download Data
echo ""
echo "----------------------------------------------------------------------"
echo "STEP 1: Downloading Historical Data"
echo "----------------------------------------------------------------------"

cd infra
docker compose run --rm backfiller python main.py \
    --symbol "$SYMBOL" \
    --start "$YESTERDAY" \
    --end "$TODAY" \
    --interval "1" \
    --unit "minutes"

echo "✅ Data downloaded successfully"

# Step 2: Initialize Backtest Tables
echo ""
echo "----------------------------------------------------------------------"
echo "STEP 2: Initializing Backtest Environment"
echo "----------------------------------------------------------------------"

docker compose exec -T postgres psql -U admin -d quant_platform <<EOF
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

DELETE FROM backtest_orders WHERE run_id = '$RUN_ID';
EOF

echo "✅ Backtest tables ready"

# Step 3: Run Backtest
echo ""
echo "----------------------------------------------------------------------"
echo "STEP 3: Running Backtest (Replaying Historical Data)"
echo "----------------------------------------------------------------------"
echo "⏩ Replay Speed: 100x (1 day ≈ 8 minutes)"

docker compose run --rm \
    -e BACKTEST_MODE=true \
    -e RUN_ID="$RUN_ID" \
    historical_replayer python main.py \
    --symbol "$SYMBOL" \
    --start "$YESTERDAY" \
    --end "$TODAY" \
    --speed 100

echo "✅ Backtest replay complete"

# Step 4: Analyze Results
echo ""
echo "----------------------------------------------------------------------"
echo "STEP 4: Displaying Results"
echo "----------------------------------------------------------------------"

echo ""
echo "======================================================================"
echo "  BACKTEST RESULTS"
echo "======================================================================"

docker compose exec -T postgres psql -U admin -d quant_platform <<EOF
\echo ''
\echo '📊 TRADE STATISTICS:'
SELECT 
    COUNT(*) FILTER (WHERE transaction_type = 'BUY') as "Buy Orders",
    COUNT(*) FILTER (WHERE transaction_type = 'SELL') as "Sell Orders",
    ROUND(SUM(pnl), 2) as "Total P&L (₹)",
    COUNT(*) FILTER (WHERE transaction_type = 'SELL' AND pnl > 0) as "Winning Trades",
    COUNT(*) FILTER (WHERE transaction_type = 'SELL' AND pnl < 0) as "Losing Trades"
FROM backtest_orders 
WHERE run_id = '$RUN_ID';

\echo ''
\echo '📋 RECENT TRADES (Last 10):'
SELECT 
    to_char(timestamp, 'HH24:MI:SS') as "Time",
    transaction_type as "Action",
    quantity as "Qty",
    price as "Price (₹)",
    COALESCE(pnl, 0) as "P&L (₹)"
FROM backtest_orders 
WHERE run_id = '$RUN_ID'
ORDER BY timestamp DESC
LIMIT 10;
EOF

echo ""
echo "======================================================================"
echo "✅ Backtest Complete! Run ID: $RUN_ID"
echo "======================================================================"
