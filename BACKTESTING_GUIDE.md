# Backtesting System - Usage Guide

## Overview
The backtesting system allows you to test your trading strategy against historical data to evaluate performance before risking real capital.

## ✅ API Limits (Upstox Free Tier)
- **Historical Data**: 20 requests/second
- **1-Minute Candles**: Max 30 days per request
- **Estimated Time**: 1 month backtest ≈ 1 API call (safe!)

## 🚀 3-Step Workflow

### Step 1: Download Historical Data
```bash
docker compose run --rm backfiller python main.py \
  --symbol "NSE_EQ|INE002A01018" \
  --start "2025-01-01" \
  --end "2025-01-31" \
  --interval "1" \
  --unit "minutes"
```

**Parameters:**
- `--symbol`: Stock symbol (get from Upstox instruments list)
- `--start/--end`: Date range (YYYY-MM-DD)
- `--interval`: Candle size (1, 5, 15, 30, etc.)
- `--unit`: Time unit (`minutes`, `hours`, `days`)

**Output:** OHLC data saved to QuestDB `ohlc` table

---

### Step 2: Run Backtest (Replay Data)
```bash
docker compose run --rm \
  -e BACKTEST_MODE=true \
  -e RUN_ID=reliance_jan2025 \
  historical_replayer python main.py \
    --symbol "NSE_EQ|INE002A01018" \
    --start "2025-01-01" \
    --end "2025-01-31" \
    --speed 100
```

**What happens:**
1. Replayer reads OHLC from QuestDB
2. Converts to tick-level events (4 ticks per candle: Open, High, Low, Close)
3. Streams to Kafka (`market.equity.ticks`)
4. Feature Engine calculates RSI, VWAP, OBI
5. Strategy executes trades (saved to `backtest_orders`)

**Speed Control:**
- `--speed 1`: Real-time (1 month = 1 month)
- `--speed 10`: 10x faster (1 month = 3 days)
- `--speed 100`: 100x faster (1 month = 7 hours)

**Note:** Strategy Runtime must be running (it auto-detects backtest mode via `BACKTEST_MODE` env var)

---

### Step 3: Analyze Results
```bash
docker compose run --rm historical_replayer python analyzer.py \
  --run-id reliance_jan2025 \
  --output backtest_results
```

**Output:**
- `backtest_results/reliance_jan2025.json` - Machine-readable metrics
- `backtest_results/reliance_jan2025.md` - Human-readable report

**Metrics Included:**
- **Total P&L**: Net profit/loss in ₹
- **Win Rate**: % of profitable trades
- **Sharpe Ratio**: Risk-adjusted returns (>1.0 is good)
- **Max Drawdown**: Largest decline from peak

---

## 📊 Example: Complete Backtest

```bash
# 1. Download Reliance data (Jan 2025)
docker compose run backfiller python main.py \
  --symbol "NSE_EQ|INE002A01018" \
  --start "2025-01-01" \
  --end "2025-01-31"

# 2. Start Strategy Runtime in backtest mode
docker compose run -d \
  -e BACKTEST_MODE=true \
  -e RUN_ID=test_run_001 \
  strategy_runtime python main.py &

# 3. Replay the data
docker compose run historical_replayer python main.py \
  --symbol "NSE_EQ|INE002A01018" \
  --start "2025-01-01" \
  --end "2025-01-31" \
  --speed 100

# 4. Generate report
docker compose run historical_replayer python analyzer.py \
  --run-id test_run_001

# View results
cat backtest_results/test_run_001.md
```

---

## 🔧 Customizing Strategy for Backtest

To test different strategy parameters:

1. Edit `services/strategy_runtime/strategies/momentum.py`
2. Change RSI threshold, VWAP logic, etc.
3. Re-run Step 2 & 3 with a new `RUN_ID`
4. Compare results in `backtest_results/`

---

## 🎯 Best Practices

1. **Start Small**: Test 1 week first, then expand to 1 month
2. **Compare Multiple Runs**: Try different RSI thresholds (45, 50, 55)
3. **Check Sharpe Ratio**: Aim for >1.0 for good risk-adjusted returns
4. **Mind Drawdowns**: Keep max drawdown <10% of capital
5. **Respect API Limits**: 1-minute data limited to 30 days per request

---

## ⚠️ Known Limitations

- **No Slippage**: Assumes perfect execution at signal price
- **No Transaction Costs**: Real trading has brokerage fees
- **Limited Depth**: Uses OHLC, not full order book
- **Future Leak Risk**: Ensure your strategy doesn't "look ahead"

---

## 🆘 Troubleshooting

**"No data found for symbol"**
→ Verify symbol format: `NSE_EQ|<ISIN>` (not `NSE_EQ:<SYMBOL>`)

**"Backtest orders table empty"**
→ Check if strategy conditions are too strict (no signals generated)

**"QuestDB connection failed"**
→ Ensure QuestDB is running: `docker compose ps questdb_tsdb`
