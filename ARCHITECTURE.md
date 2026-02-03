# Quant Platform - Complete Architecture Guide

## System Overview
Your platform is a **fully automated intraday trading system** with ₹20,000 capital, running 14 microservices orchestrated by Docker Compose.

---

## 🏗️ Service Inventory (14 Services)

### **Core Infrastructure (5)**
| Service | Image | Purpose |
|---------|-------|---------|
| `kafka_bus` | apache/kafka | Message broker for real-time event streaming |
| `postgres_metadata` | postgres:15 | Relational DB for portfolios, trades, instruments |
| `questdb_tsdb` | questdb | Time-series DB for tick-by-tick market data |
| `redis_state` | redis:7 | Cache for session state & real-time lookups |
| `minio_s3` | minio | Object storage for historical data & backups |

### **Market Data Pipeline (3)**
| Service | Purpose | Input | Output |
|---------|---------|-------|--------|
| `upstox_ingestor` | Stream live market data from Upstox WebSocket | Upstox API | Kafka: `market.equity.ticks` |
| `feature_engine` | Calculate indicators (VWAP, RSI, OBI) | Kafka: `market.equity.ticks` | Kafka: `market.enriched.ticks` |
| `market_persistor` | Store enriched ticks to database | Kafka: `market.enriched.ticks` | QuestDB: `ticks` table |

### **Trading Logic (2)**
| Service | Purpose | Input | Output |
|---------|---------|-------|--------|
| `market_scanner` | Identify top momentum stocks (every 5 mins) | Upstox Quotes API | Postgres: `scanner_results` + Kafka: `scanner.suggestions` |
| `strategy_runtime` | Execute multi-factor strategy & paper trades | Kafka: `market.enriched.ticks` | Postgres: `portfolios`, `positions`, `executed_orders` |

### **Supporting Services (4)**
| Service | Purpose |
|---------|---------|
| `quant_grafana` | Visualization dashboard (Port 3000) |
| `api_gateway` | REST API for external access (Port 8080) |
| `data_backfiller` | Historical data download (runs on-demand) |
| `system_doctor` | Health monitoring & diagnostics |

---

## 📊 Complete Data Flow

```
┌─────────────────────────────────────────────────────────────────┐
│                    MARKET DATA INGESTION                        │
└─────────────────────────────────────────────────────────────────┘
                              ↓
    [Upstox WebSocket API] → Live Ticks (Nifty, Reliance, etc.)
                              ↓
                    ┌─────────────────┐
                    │ upstox_ingestor │ ← Protobuf decoding
                    └─────────────────┘
                              ↓
                 Kafka Topic: market.equity.ticks
                    {symbol, ltp, volume, depth}
                              ↓
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│                    FEATURE ENRICHMENT                           │
└─────────────────────────────────────────────────────────────────┘
                              ↓
                    ┌─────────────────┐
                    │ feature_engine  │ ← Calculates:
                    └─────────────────┘   • VWAP (Volume-Weighted Avg Price)
                              ↓           • RSI (Relative Strength Index)
                              ↓           • OBI (Order Book Imbalance)
                 Kafka Topic: market.enriched.ticks            • SMA (Simple Moving Average)
                    {symbol, ltp, vwap, rsi, obi, sma}
                              ↓
                              ├──────────────────┐
                              ↓                  ↓
                    ┌─────────────────┐  ┌──────────────────┐
                    │market_persistor │  │strategy_runtime  │
                    └─────────────────┘  └──────────────────┘
                              ↓                  ↓
                    QuestDB: ticks table    (See Trading Logic)
                    [Historical Analysis]

┌─────────────────────────────────────────────────────────────────┐
│                    STOCK SELECTION                              │
└─────────────────────────────────────────────────────────────────┘
                              ↓
                    ┌─────────────────┐
                    │ market_scanner  │ ← Runs every 5 minutes
                    └─────────────────┘
                              ↓
              Upstox Quotes API (100 stocks)
                              ↓
           Calculates Momentum Score = |ΔPrice%| × Volume
                              ↓
              Picks Top 5 Stocks & Saves:
                              ↓
                ├─────────────────┬──────────────────┐
                ↓                 ↓                  ↓
    Postgres: scanner_results    Kafka Topic    Notify Ingestor
    [For Grafana]          scanner.suggestions  [Subscribe to these]

┌─────────────────────────────────────────────────────────────────┐
│                    TRADING STRATEGY EXECUTION                   │
└─────────────────────────────────────────────────────────────────┘
                              ↓
                    ┌──────────────────┐
                    │strategy_runtime  │
                    └──────────────────┘
                              ↓
           Listens: market.enriched.ticks
                              ↓
        ┌─────────────────────────────────────┐
        │ Multi-Factor Strategy Decision:     │
        │ BUY IF:                              │
        │  • Price > VWAP                      │
        │  • RSI > 50                          │
        │  • OBI > 0 (Buy pressure)            │
        │                                      │
        │ SELL IF:                             │
        │  • Price < VWAP OR RSI < 45          │
        │  • Time >= 3:20 PM (EOD Square-Off)  │
        └─────────────────────────────────────┘
                              ↓
                    ┌──────────────────┐
                    │ paper_exchange   │ ← Virtual Broker
                    └──────────────────┘
                              ↓
              Executes Buy/Sell Orders
              Position Size = 10% of capital
                              ↓
                    Updates Postgres Tables:
                              ↓
        ├─────────────────┬──────────────────┬────────────────┐
        ↓                 ↓                  ↓                ↓
    portfolios        positions      executed_orders    (audit log)
    [Balance: ₹20k]   [Holdings]     [Trade History]

┌─────────────────────────────────────────────────────────────────┐
│                    VISUALIZATION & MONITORING                    │
└─────────────────────────────────────────────────────────────────┘
                              ↓
                    ┌─────────────────┐
                    │ quant_grafana   │ (Port 3000)
                    └─────────────────┘
                              ↓
              Connects to postgres_metadata
                              ↓
            Displays Real-Time Dashboards:
              • Scanner Top Picks
              • Trade Execution History
              • Portfolio Equity Chart
              • Open Positions
              • Daily P&L
```

---

## 🔄 Service Interactions

### **Kafka Topics (Message Bus)**
| Topic | Producer | Consumer | Data Schema |
|-------|----------|----------|-------------|
| `market.equity.ticks` | upstox_ingestor | feature_engine | `{symbol, ltp, volume, depth}` |
| `market.enriched.ticks` | feature_engine | market_persistor, strategy_runtime | `{symbol, ltp, vwap, rsi, obi, sma}` |
| `scanner.suggestions` | market_scanner | upstox_ingestor | `["NSE_EQ:RELIANCE", ...]` |
| `market.option.greeks` | (unused) | market_persistor | N/A |

### **Database Schemas**

#### **Postgres (postgres_metadata)**
```sql
-- Strategy Runtime Tables
portfolios (user_id, balance, equity, last_updated)
positions (portfolio_id, symbol, quantity, avg_price, last_updated)
executed_orders (timestamp, strategy_id, symbol, transaction_type, quantity, price, pnl)

-- Market Scanner Tables
scanner_results (timestamp, symbol, score, ltp, volume)
instruments (instrument_token, exchange, segment, symbol)
```

#### **QuestDB (questdb_tsdb)**
```sql
ticks (timestamp, symbol, ltp, volume, vwap, rsi, obi, sma, spread, aggressor)
```

---

## ⚙️ Key Configuration Files

| File | Purpose |
|------|---------|
| `services/ingestion/.env` | Upstox API credentials |
| `services/strategy_runtime/schema.py` | Portfolio defaults (₹20,000) |
| `services/strategy_runtime/paper_exchange.py` | Position sizing logic |
| `services/strategy_runtime/strategies/momentum.py` | Trading strategy rules |
| `infra/docker-compose.yml` | Service orchestration |

---

## 🎯 Critical Features

### **Intraday Compliance**
- ✅ **Auto Square-Off**: All positions closed at 3:20 PM IST
- ✅ **No Overnight Holdings**: Strictly intraday

### **Risk Management**
- ✅ **Capital**: ₹20,000
- ✅ **Position Size**: 10% per trade (₹2,000)
- ✅ **Max Positions**: 10 concurrent
- ✅ **Risk Per Trade**: 1% (₹200)

### **Rate Limit Safety**
- ✅ **Scanner**: Every 5 minutes (0.003 req/sec)
- ✅ **WebSocket**: Unlimited (streaming)
- ✅ **Upstox Free Tier**: Compliant

---

## 🚀 System Startup Sequence

1. Infrastructure boots: Kafka, Postgres, QuestDB, Redis
2. `upstox_ingestor` connects to Upstox WebSocket
3. `feature_engine` starts processing raw ticks
4. `market_persistor` begins storing enriched data
5. `market_scanner` performs initial scan
6. `strategy_runtime` initializes portfolio & listens for signals
7. Grafana dashboards become accessible at `http://localhost:3000`

---

## 📈 Monitoring

**View Logs:**
```bash
# All services
docker compose logs -f

# Specific service
docker compose logs -f strategy_runtime
docker compose logs -f feature_engine
```

**Check Status:**
```bash
docker compose ps
```

**Database Queries:**
```bash
# Portfolio status
docker compose exec postgres psql -U admin -d quant_platform -c "SELECT * FROM portfolios;"

# Recent trades
docker compose exec postgres psql -U admin -d quant_platform -c "SELECT * FROM executed_orders ORDER BY timestamp DESC LIMIT 10;"
```
