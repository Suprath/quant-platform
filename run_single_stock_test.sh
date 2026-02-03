#!/bin/bash
# Single-Stock Backtest - Simplified test to verify system works
set -e

echo "======================================================================"
echo "  SINGLE-STOCK BACKTEST TEST - Reliance Jan 1, 2025"
echo "======================================================================"

# Configuration
SYMBOL="NSE_EQ|INE002A01018"
NAME="Reliance"
START_DATE="2025-01-01"
END_DATE="2025-01-02"
RUN_ID="single_test_$(date +%Y%m%d_%H%M%S)"

cd infra

echo ""
echo "📅 Date: $START_DATE"
echo "💰 Capital: ₹20,000"
echo "📊 Strategy: VWAP + RSI (Backtest Mode - No OBI)"
echo "🎯 Stock: $NAME ($SYMBOL)"
echo "🔖 Run ID: $RUN_ID"
echo ""

# Step 1: Download data
echo "======================================================================"
echo "STEP 1: Downloading Data"
echo "======================================================================"

docker compose run --rm backfiller python main.py \
    --symbol "$SYMBOL" \
    --start "$START_DATE" \
    --end "$END_DATE" \
    --interval "1" \
    --unit "minutes"

echo "✅ Data downloaded"

# Step 2: Initialize tables
echo ""
echo "======================================================================"
echo "STEP 2: Initializing Backtest Tables"
echo "======================================================================"

docker compose exec -T postgres psql -U admin -d quant_platform <<EOF
-- DROP existing tables to ensure schema matches latest code
DROP TABLE IF EXISTS backtest_portfolios CASCADE;
DROP TABLE IF EXISTS backtest_orders CASCADE;

CREATE TABLE backtest_portfolios (
    id SERIAL PRIMARY KEY,
    run_id VARCHAR(50) NOT NULL,
    user_id VARCHAR(50) NOT NULL,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    balance DECIMAL(15, 2) NOT NULL,
    equity DECIMAL(15, 2) DEFAULT 0.0
);

CREATE TABLE backtest_orders (
    id SERIAL PRIMARY KEY,
    run_id VARCHAR(50) NOT NULL,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    symbol VARCHAR(50) NOT NULL,
    transaction_type VARCHAR(10) NOT NULL,
    quantity INT NOT NULL,
    price DECIMAL(10, 2) NOT NULL,
    pnl DECIMAL(10, 2) DEFAULT 0.0
);
EOF

echo "✅ Tables ready"

# Step 3: Start Feature Engine & Strategy Runtime in isolation
echo ""
echo "======================================================================"
echo "STEP 3: Starting Isolated Backtest Pipeline"
echo "======================================================================"

# Clean up existing test containers
echo "🧹 Cleaning up old containers..."
docker rm -f strategy_test feature_engine_test 2>/dev/null || true
docker container prune -f --filter "label=com.docker.compose.service=historical_replayer"

echo "🚀 Starting Feature Engine (Backtest Mode)..."
docker compose run -d --rm \
    -e BACKTEST_MODE=true \
    -e RUN_ID="$RUN_ID" \
    --name feature_engine_test \
    feature_engine python main.py

echo "🚀 Starting Strategy Runtime (Backtest Mode)..."
docker compose run -d --rm \
    -e BACKTEST_MODE=true \
    -e RUN_ID="$RUN_ID" \
    --name strategy_test \
    strategy_runtime python main.py

echo "⏳ Waiting for pipeline to initialize..."
sleep 10

# Step 4: Replaying Historical Data
echo ""
echo "======================================================================"
echo "STEP 4: Replaying Historical Data (Isolated Topic)"
echo "======================================================================"
echo "⏩ Speed: 10x"
echo ""

docker compose run --rm \
    -e RUN_ID="$RUN_ID" \
    historical_replayer python main.py \
    --symbol "$SYMBOL" \
    --start "$START_DATE" \
    --end "$END_DATE" \
    --timeframe "1m" \
    --speed 100

echo "✅ Replay complete"

# Give strategy time to process remaining ticks
echo "⏳ Allowing final ticks to process..."
sleep 5

# Cleanup (Disabled for debugging)
# docker stop strategy_test 2>/dev/null || true
# docker rm strategy_test 2>/dev/null || true

# Restart normal strategy runtime
docker compose up -d strategy_runtime

# Step 5: Display Results
echo ""
echo "======================================================================"
echo "  RESULTS - $NAME on $START_DATE"
echo "======================================================================"

docker compose exec -T postgres psql -U admin -d quant_platform <<EOF
\echo ''
\echo '📊 TRADE SUMMARY:'
SELECT 
    COUNT(*) FILTER (WHERE transaction_type = 'BUY') as "Buys",
    COUNT(*) FILTER (WHERE transaction_type = 'SELL') as "Sells",
    ROUND(SUM(pnl), 2) as "Total P&L (₹)",
    COUNT(*) FILTER (WHERE pnl > 0) as "Wins",
    COUNT(*) FILTER (WHERE pnl < 0) as "Losses"
FROM backtest_orders 
WHERE run_id = '$RUN_ID';

\echo ''
\echo '📋 ALL TRADES:'
SELECT 
    to_char(timestamp, 'YYYY-MM-DD HH24:MI:SS') as "Time",
    transaction_type as "Action",
    quantity as "Qty",
    price as "Price",
    ROUND(COALESCE(pnl, 0), 2) as "P&L"
FROM backtest_orders 
WHERE run_id = '$RUN_ID'
ORDER BY timestamp;
EOF

echo ""
echo "======================================================================"
echo "✅ Single-Stock Test Complete! Run ID: $RUN_ID"
echo "======================================================================"
