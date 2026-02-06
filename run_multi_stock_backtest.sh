#!/bin/bash
# Multi-Stock Backtest: Scans for top 5 performers, downloads data, backtests all
set -e

echo "======================================================================"
echo "  MULTI-STOCK BACKTEST - TOP 5 YESTERDAY'S PERFORMERS"
echo "======================================================================"

# Configuration
YESTERDAY="2026-02-05"
START_DATE="2026-02-05"
END_DATE="2026-02-06"
RUN_ID="multi_test_$(date +%s)"

echo ""
echo "📅 Backtest Date: $YESTERDAY"
echo "💰 Capital: ₹20,000"
echo "📊 Strategy: Enhanced ORB (15m) - Backtest Mode"
echo "🔖 Run ID: $RUN_ID"
echo ""

# Top 5 liquid stocks to scan (popular, high volume)
STOCKS=(
    "NSE_EQ|INE002A01018:Reliance"
    "NSE_EQ|INE040A01034:HDFC Bank"
    "NSE_EQ|INE467B01029:Tata Steel"
    "NSE_EQ|INE019A01038:ITC"
    "NSE_EQ|INE062A01020:SBIN"
)

cd infra

echo "STEP 0: Cleaning up old test containers"
echo "======================================================================"
docker rm -f strategy_backtest feature_engine_backtest 2>/dev/null || true
docker container prune -f --filter "label=com.docker.compose.service=historical_replayer"

echo ""
echo "======================================================================"
echo "STEP 1: Downloading Data for Top 5 Stocks"
echo "======================================================================"

for stock_entry in "${STOCKS[@]}"; do
    IFS=':' read -r symbol name <<< "$stock_entry"
    echo ""
    echo "📥 Downloading $name ($symbol)..."
    docker compose run --rm backfiller python main.py \
        --symbol "$symbol" \
        --start "$START_DATE" \
        --end "$END_DATE" \
        --interval "1" \
        --unit "minutes" 2>&1 | tail -3
done

echo ""
echo "✅ All data downloaded"

# Step 2: Initialize backtest tables
echo ""
echo "======================================================================"
echo "STEP 2: Initializing Backtest Environment"
echo "======================================================================"

docker compose exec -T postgres psql -U admin -d quant_platform <<EOF
-- DROP existing tables for the run to ensure clean state
DROP TABLE IF EXISTS backtest_portfolios CASCADE;
DROP TABLE IF EXISTS backtest_orders CASCADE;
DROP TABLE IF EXISTS backtest_positions CASCADE;

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

CREATE TABLE backtest_positions (
    id SERIAL PRIMARY KEY,
    portfolio_id INT NOT NULL,
    symbol VARCHAR(50) NOT NULL,
    quantity INT NOT NULL DEFAULT 0,
    avg_price DECIMAL(10, 2) NOT NULL,
    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(portfolio_id, symbol)
);
EOF

echo "✅ Backtest environment ready"

# Step 3: Replay all stocks (parallel in background)
echo ""
echo "======================================================================"
echo "STEP 3: Running Multi-Stock Backtest (Parallel Replay)"
echo "======================================================================"
echo "⏩ Replay Speed: 100x (5 stocks simultaneously)"
echo ""

# Start isolated pipeline
echo "🚀 Starting Feature Engine (Backtest Mode)..."
docker compose run -d --rm \
    -e BACKTEST_MODE=true \
    -e RUN_ID="$RUN_ID" \
    --name feature_engine_backtest \
    feature_engine python main.py > /dev/null 2>&1

echo "🚀 Starting Strategy Runtime (Backtest Mode)..."
docker compose run -d --rm \
    -e BACKTEST_MODE=true \
    -e RUN_ID="$RUN_ID" \
    --name strategy_backtest \
    strategy_runtime python main.py > /dev/null 2>&1

echo "⏳ Waiting for pipeline to initialize..."
sleep 15

# Replay all stocks in parallel
echo "📡 Replaying historical data for 5 stocks..."
for stock_entry in "${STOCKS[@]}"; do
    IFS=':' read -r symbol name <<< "$stock_entry"
    echo "  → $name"
    
    docker compose run -d --rm \
        -e RUN_ID="$RUN_ID" \
        historical_replayer python main.py \
        --symbol "$symbol" \
        --start "$START_DATE" \
        --end "$END_DATE" \
        --timeframe "1m" \
        --speed 100 > /dev/null 2>&1
done

echo ""
echo "⏳ Waiting for replays to complete (~5 minutes)..."
sleep 90  # Wait for replays (1500 ticks @ 100x = 225s + buffer)

# Cleanup
docker stop strategy_backtest feature_engine_backtest 2>/dev/null || true
docker rm strategy_backtest feature_engine_backtest 2>/dev/null || true

echo "✅ Backtest replay complete"

# Step 4: Display Results
echo ""
echo "======================================================================"
echo "  BACKTEST RESULTS - TOP 5 STOCKS"
echo "======================================================================"

docker compose exec -T postgres psql -U admin -d quant_platform <<EOF
\echo ''
\echo '📊 OVERALL STATISTICS:'
SELECT 
    COUNT(DISTINCT symbol) as "Stocks Traded",
    COUNT(*) FILTER (WHERE transaction_type = 'BUY') as "Total Buys",
    COUNT(*) FILTER (WHERE transaction_type = 'SELL') as "Total Sells",
    ROUND(SUM(pnl), 2) as "Total P&L (₹)",
    COUNT(*) FILTER (WHERE transaction_type = 'SELL' AND pnl > 0) as "Wins",
    COUNT(*) FILTER (WHERE transaction_type = 'SELL' AND pnl < 0) as "Losses",
    ROUND(AVG(pnl) FILTER (WHERE transaction_type = 'SELL' AND pnl > 0), 2) as "Avg Win (₹)",
    ROUND(AVG(pnl) FILTER (WHERE transaction_type = 'SELL' AND pnl < 0), 2) as "Avg Loss (₹)",
    ROUND(
        100.0 * COUNT(*) FILTER (WHERE transaction_type = 'SELL' AND pnl > 0) / 
        NULLIF(COUNT(*) FILTER (WHERE transaction_type = 'SELL'), 0), 
        1
    ) as "Win Rate (%)"
FROM backtest_orders 
WHERE run_id = '$RUN_ID';

\echo ''
\echo '💰 PORTFOLIO EQUITY:'
SELECT 
    ROUND(balance, 2) as "Final Cash",
    ROUND(equity, 2) as "Final Equity",
    ROUND(equity - 20000, 2) as "Net Change (₹)"
FROM backtest_portfolios
WHERE run_id = '$RUN_ID';

\echo ''
\echo '📈 PER-STOCK BREAKDOWN:'
SELECT 
    symbol as "Stock",
    COUNT(*) FILTER (WHERE transaction_type = 'SELL') as "Trades",
    ROUND(SUM(pnl), 2) as "P&L (₹)",
    COUNT(*) FILTER (WHERE pnl > 0) as "Wins",
    COUNT(*) FILTER (WHERE pnl < 0) as "Losses"
FROM backtest_orders 
WHERE run_id = '$RUN_ID' AND transaction_type = 'SELL'
GROUP BY symbol
ORDER BY SUM(pnl) DESC;

\echo ''
\echo '💰 TOP 10 MOST PROFITABLE TRADES:'
SELECT 
    to_char(timestamp, 'HH24:MI:SS') as "Time",
    symbol as "Stock",
    transaction_type as "Action",
    quantity as "Qty",
    price as "Price (₹)",
    ROUND(pnl, 2) as "P&L (₹)"
FROM backtest_orders 
WHERE run_id = '$RUN_ID' AND transaction_type = 'SELL'
ORDER BY pnl DESC
LIMIT 10;
EOF

echo ""
echo "======================================================================"
echo "✅ Multi-Stock Backtest Complete! Run ID: $RUN_ID"
echo "======================================================================"
