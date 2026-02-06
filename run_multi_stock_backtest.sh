#!/bin/bash
# Multi-Stock Backtest: Scans for top 5 performers, downloads data, backtests all
set -e

# ============================================================================
# CLI ARGUMENT PARSING
# ============================================================================
usage() {
    echo "Usage: $0 [-s START_DATE] [-e END_DATE] [-t STOCKS] [-u]"
    echo ""
    echo "Options:"
    echo "  -s  Start date for backtest (YYYY-MM-DD). Default: yesterday."
    echo "  -e  End date for backtest (YYYY-MM-DD). Default: today."
    echo "  -t  Comma-separated stock symbols (e.g., 'NSE_EQ|INE002A01018,NSE_EQ|INE040A01034')."
    echo "      Default: Top 5 liquid stocks."
    echo "  -u  Use dynamic scanner to select best stocks for the target date."
    echo "  -h  Show this help message."
    echo ""
    echo "Examples:"
    echo "  $0 -s 2026-02-03 -e 2026-02-04"
    echo "  $0 -s 2026-02-05 -e 2026-02-06 -u   # Use scanner"
    echo "  $0 -t 'NSE_EQ|INE002A01018,NSE_EQ|INE040A01034'"
    exit 1
}


# Defaults
DEFAULT_START_DATE=$(date -v-1d +%Y-%m-%d 2>/dev/null || date -d "yesterday" +%Y-%m-%d)
DEFAULT_END_DATE=$(date +%Y-%m-%d)
START_DATE=""
END_DATE=""
CUSTOM_STOCKS=""

# Parse arguments
USE_SCANNER=false
while getopts ":s:e:t:uh" opt; do
    case ${opt} in
        s ) START_DATE="$OPTARG" ;;
        e ) END_DATE="$OPTARG" ;;
        t ) CUSTOM_STOCKS="$OPTARG" ;;
        u ) USE_SCANNER=true ;;
        h ) usage ;;
        \? ) echo "Invalid option: -$OPTARG" >&2; usage ;;
        : ) echo "Option -$OPTARG requires an argument." >&2; usage ;;
    esac
done
shift $((OPTIND -1))


# Apply defaults if not provided
START_DATE="${START_DATE:-$DEFAULT_START_DATE}"
END_DATE="${END_DATE:-$DEFAULT_END_DATE}"
RUN_ID="multi_test_$(date +%s)"

# Every docker command needs to be in the infra directory
cd infra

# Stock list: use scanner, custom, or default
if [ "$USE_SCANNER" = true ]; then
    # Expanded candidate list for scanning (15 liquid stocks)
    echo "📥 Downloading scan candidates and Nifty 50 for RS benchmarking..."
    docker compose run --rm backfiller python main.py --symbol "NSE_INDEX|Nifty 50" --start "$START_DATE" --end "$START_DATE" > /dev/null 2>&1
    
    CANDIDATES=(
        "NSE_EQ|INE002A01018:Reliance"
        "NSE_EQ|INE040A01034:HDFCBank"
        "NSE_EQ|INE467B01029:TataSteel"
        "NSE_EQ|INE019A01038:ITC"
        "NSE_EQ|INE062A01020:SBIN"
        "NSE_EQ|INE090A01021:ICICIBank"
        "NSE_EQ|INE009A01021:Infosys"
        "NSE_EQ|INE044A01036:TCS"
        "NSE_EQ|INE154A01025:BajajFinance"
        "NSE_EQ|INE238A01034:AxisBank"
    )

    for entry in "${CANDIDATES[@]}"; do
         sym="${entry%%:*}"
         docker compose run --rm backfiller python main.py --symbol "$sym" --start "$START_DATE" --end "$START_DATE" > /dev/null 2>&1
    done

    echo "🔍 Scanning candidates for High-Probability (RS-based) entries..."
    SCANNED_SYMBOLS=$(docker compose run --rm scanner python main.py --date "$START_DATE" --output symbols --top-n 5 | tail -n 1)
    
    if [[ "$SCANNED_SYMBOLS" == *"NSE_EQ"* ]]; then
        echo "✅ Scanner selected: $SCANNED_SYMBOLS"
        IFS=',' read -ra SYMBOLS <<< "$SCANNED_SYMBOLS"
        STOCKS=()
        for sym in "${SYMBOLS[@]}"; do
            STOCKS+=("$sym:Scanned")
        done
    else
        echo "⚠️ Scanner failed or returned no data. Using fallback stocks."
        STOCKS=("NSE_EQ|INE002A01018:Reliance" "NSE_EQ|INE040A01034:HDFC Bank")
    fi
elif [ -n "$CUSTOM_STOCKS" ]; then
    # Convert comma-separated symbols to array format
    IFS=',' read -ra SYMBOLS <<< "$CUSTOM_STOCKS"
    STOCKS=()
    for sym in "${SYMBOLS[@]}"; do
        STOCKS+=("$sym:Custom")
    done
else
    # Default Top 5 liquid stocks
    STOCKS=(
        "NSE_EQ|INE002A01018:Reliance"
        "NSE_EQ|INE040A01034:HDFC Bank"
        "NSE_EQ|INE467B01029:Tata Steel"
        "NSE_EQ|INE019A01038:ITC"
        "NSE_EQ|INE062A01020:SBIN"
    )
fi


echo "======================================================================"
echo "  MULTI-STOCK BACKTEST"
echo "======================================================================"
echo ""
echo "📅 Start Date: $START_DATE"
echo "📅 End Date: $END_DATE"
echo "💰 Capital: ₹5,000"
echo "📊 Strategy: Enhanced ORB (15m) - Backtest Mode"
echo "🔖 Run ID: $RUN_ID"
echo "📈 Stocks: ${#STOCKS[@]}"
echo ""

echo "STEP 0: Cleaning up old test containers"
echo "======================================================================"
docker rm -f strategy_backtest feature_engine_backtest 2>/dev/null || true
docker ps -a --filter "name=historical_replayer" -q | xargs docker rm -f 2>/dev/null || true
docker container prune -f --filter "label=com.docker.compose.service=historical_replayer"

# Clear QuestDB OHLC to avoid replaying old data from previous runs
echo "🧹 Clearing stale QuestDB data..."
docker exec questdb_tsdb curl -G "http://localhost:9000/exec?query=TRUNCATE+TABLE+ohlc" > /dev/null 2>&1
docker exec questdb_tsdb curl -G "http://localhost:9000/exec?query=TRUNCATE+TABLE+prices" > /dev/null 2>&1

# STEP 1: Download Nifty 50 and Stocks
echo "📥 Downloading Nifty 50 (Regime Filter)..."
docker compose run --rm backfiller python main.py --symbol "NSE_INDEX|Nifty 50" --start "$START_DATE" --end "$END_DATE" > /dev/null 2>&1

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

# Replay Nifty 50 First
echo "📡 Replaying Nifty 50..."
docker compose run -d --rm \
    -e RUN_ID="$RUN_ID" \
    historical_replayer python main.py \
    --symbol "NSE_INDEX|Nifty 50" \
    --start "$START_DATE" \
    --end "$END_DATE" \
    --timeframe "1m" \
    --speed 0

# Replay all stocks in parallel (unlimited speed for backtest)
echo "📡 Replaying historical data for ${#STOCKS[@]} stocks..."
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
        --speed 0
done

echo ""
echo "⏳ Waiting for replays to complete..."
# Wait while any historical_replayer container is still running
while docker ps --format '{{.Names}}' | grep -q "historical_replayer"; do
    sleep 5
done

# Small buffer for Kafka consumers to finish processing the last ticks
sleep 15

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
    ROUND(equity - 5000, 2) as "Net Change (₹)"
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
