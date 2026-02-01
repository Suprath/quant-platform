# 🚀 Production-Grade Quant Trading Platform (Indian Markets)

A **high-frequency, event-driven algorithmic trading platform** designed for **NSE/BSE (India)** using the **Upstox V3 API**.

Built with a **microservices architecture**, it handles real-time ingestion, market microstructure analysis (VWAP, Order Book Imbalance), and automated execution — all while staying within **Upstox free-tier API limits**.

---

## 🏗 Architecture

The system follows a **reactive, event-driven design**.

| Layer | Component | Technology | Purpose |
|------|----------|-----------|---------|
| 1 | Scout | Market Scanner (Python) | Scans 100+ stocks every 5 mins to find high-momentum breakout candidates |
| 2 | Sensor | Ingestor (Upstox V3 / Protobuf) | WebSocket ingestion & dynamic subscriptions |
| 3 | Bus | Message Bus (Apache Kafka) | Low-latency streaming of ticks, greeks, and signals |
| 4 | Storage | Time-Series DB (QuestDB) | Stores ticks, OHLC, and option greeks |
| 4 | Storage | Relational DB (PostgreSQL) | Instrument master, user metadata, trade logs |
| 5 | Brain | Feature Engine (Pandas / NumPy) | VWAP, OBI, Spread, Aggressor detection |
| 6 | Hands | Strategy Runtime (Python) | Executes trades (Paper / Live) |
| 7 | Window | API Gateway (FastAPI) | REST API for dashboards and clients |

---

## ⚡ Quick Start

### Prerequisites
- Docker Desktop (minimum **6 GB RAM** allocated)
- Upstox API Credentials (API Key & Secret)

### Installation

Clone repository and prepare environment:
- `git clone https://github.com/yourusername/quant-platform.git`
- `cd quant-platform`
- `cd services/ingestion`
- `cp .env.example .env`

### Configuration (`services/ingestion/.env`)

UPSTOX_API_KEY=your_api_key  
UPSTOX_API_SECRET=your_api_secret  
UPSTOX_REDIRECT_URI=http://localhost:8501  
UPSTOX_ACCESS_TOKEN= *(leave blank initially)*  

KAFKA_BOOTSTRAP_SERVERS=kafka_bus:9092  
POSTGRES_HOST=postgres_metadata  
QUESTDB_HOST=questdb_tsdb  

---

## 📅 Daily Routine (Runbook)

⚠️ **Upstox access tokens expire daily at 3:30 AM IST**  
Follow this routine every trading day before market open (~08:45 AM).

### Step 1: Start Infrastructure
- `cd infra`
- `docker compose up -d`

### Step 2: Authenticate (Generate Daily Token)
- `docker compose run --rm ingestor python auth_helper.py`
- Login via browser, copy auth code, paste into terminal
- Update `UPSTOX_ACCESS_TOKEN` in `.env`

### Step 3: Sync Instrument Master (IPOs / Expiries)
Downloads ~22,000 instruments into PostgreSQL.
- `docker exec -it api_gateway python sync_instruments.py`

### Step 4: Launch Application Services
- `docker compose restart ingestor scanner feature_engine`

### Step 5: Verify System Health
- `docker compose run --rm doctor`

---

## 📡 Kafka Topics & Data Streams

### Raw Market Data (`market.equity.ticks`)
Fields: symbol, ltp, volume, open interest, previous close, timestamp

### Option Greeks (`market.option.greeks`)
Fields: iv, delta, gamma, theta, vega

### Enriched Microstructure (`market.enriched.ticks`)
Fields: vwap, order book imbalance, spread, aggressor side

### Scanner Suggestions (`scanner.suggestions`)
List of high-momentum equities detected pre-breakout

---

## 🔌 API Documentation

**Base URL:** http://localhost:8080

### Get Live Quote
- `GET /api/v1/market/quote/{symbol}`

### Get Option Greeks
- `GET /api/v1/market/greeks/{symbol}`

### Get Trade History
- `GET /api/v1/trades?limit=50`

### Search Instruments
- `GET /api/v1/instruments/search?query=<text>`

---

## 🛠 Developer Utilities

### Data Backfiller
Downloads historical 1-minute OHLCV data for backtesting.
- Configure parameters in `services/backfiller/main.py`
- Run: `docker compose run --rm backfiller`

### System Doctor
Runs diagnostics on Kafka, databases, and API connectivity.
- `docker compose run --rm doctor`

---

## 📊 Database Schema

### PostgreSQL (`quant_platform`)
- instruments — master symbol dictionary
- executed_orders — audit trail of trades
- users — authentication and profile data

### QuestDB (`qdb`)
- ticks — price, volume, spread, aggressor
- option_greeks — IV, delta, gamma
- ohlc — 1-minute historical candles

---

## 🛑 Troubleshooting

### Kafka Connection Refused
Kafka takes ~30s to boot on macOS.  
Restart ingestor if needed.

### HTTP 401 Unauthorized
Token expired — rerun authentication helper.

### Topic Not Found
Topics auto-create; if failure occurs, run system doctor.

## 👤 Author
Suprath PS
