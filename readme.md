# KIRA - Quantitative Trading Platform

A high-frequency, event-driven algorithmic trading platform designed for the Indian equity markets using the Upstox API.

Built with a sophisticated microservices architecture, KIRA handles real-time data ingestion, market microstructure analysis (such as Volume Weighted Average Price and Order Book Imbalance), dynamic support and resistance detection, and automated execution. It is designed to be highly scalable while remaining compliant with standard brokerage API rate limits.

---

## Quick Start

You can deploy the entire production-ready platform with a single command.

Requirements: **Docker Desktop** with at least 8 GB of RAM allocated, and your **Upstox Developer API credentials** ready.

```bash
# 1. Clone the repository
git clone https://github.com/Suprath/KIRA.git kira
cd kira

# 2. Create your environment file from the template
cp .env.example .env
```

Open the `.env` file in your editor and fill in three required fields:

```bash
UPSTOX_API_KEY=your_api_key_here
UPSTOX_API_SECRET=your_api_secret_here
UPSTOX_ACCESS_TOKEN=your_daily_access_token_here
```

> **Important:** Also set `GITHUB_REPOSITORY_LOWER=suprath/kira` in `.env` — this tells Docker where to pull the pre-built images from GitHub Container Registry (GHCR).

```bash
# 3. Start the platform (pulls all pre-built images from GHCR)
docker compose -f docker-compose.prod.yml up -d
```

Once the containers have initialized (30-60 seconds), open your browser and navigate to:

- **Trading Dashboard:** `http://localhost:3001`
- **API Gateway:** `http://localhost:8080`
- **QuestDB Console:** `http://localhost:9000`

---

## Architecture Overview

The system strictly adheres to a reactive, event-driven design built around an Apache Kafka message bus. This allows individual components to scale independently and prevents network bottlenecks during highly volatile market sessions.

```mermaid
flowchart TB
    subgraph External["External Interfaces"]
        Upstox["Upstox Trading API"]
    end

    subgraph Streaming["Event Streaming Layer"]
        Kafka(("Apache Kafka\nMessage Bus"))
    end

    subgraph DataLayer["Data & Persistence Layer"]
        QDB[("QuestDB\nTime-Series Data")]
        PG[("PostgreSQL\nMetadata & Orders")]
        RS[("Redis\nState & Caching")]
        S3[("Minio S3\nModels & Assets")]
    end

    subgraph DataIngestion["Ingestion & Processing"]
        Ingestor["Ingestor\nWebSocket Feed"]
        Scanner["Scanner\nMomentum Detection"]
        FeatureEngine["Feature Engine\nMicrostructure Metrics"]
        Backfiller["Data Backfiller\nHistorical Downloader"]
        Persistor["Market Persistor\nData Storage"]
        EdgeDetector["Edge Detector\nSupport & Resistance"]
    end

    subgraph AI["Strategy & Execution"]
        Optimizer["Parameter Optimizer\nHyperparameter Tuning"]
        Runtime["Strategy Runtime\nLive Execution Engine"]
        Replayer["Historical Replayer\nBacktest Simulation"]
    end

    subgraph Interface["User Interface"]
        API["API Gateway\nFastAPI REST"]
        Frontend["Quant Frontend\nNext.js Dashboard"]
    end

    %% Connections
    Upstox <-->|WebSockets & REST| Ingestor
    Upstox -->|REST| Scanner
    Runtime -->|Execute Orders| Upstox

    Ingestor -->|Raw Market Data| Kafka
    Scanner -->|Momentum Candidates| Kafka
    FeatureEngine -->|VWAP and OBI| Kafka
    EdgeDetector -->|Price Levels| Kafka
    
    Kafka -.->|Stream| FeatureEngine
    Kafka -.->|Stream| EdgeDetector
    Kafka -.->|Stream| Persistor
    Kafka -.->|Market Events| Runtime
    
    Persistor -->|Save Ticks| QDB
    Backfiller -->|Historical OHLC| QDB
    Replayer -->|Playback Data| Kafka
    
    Optimizer -->|Optimal Parameters| PG
    Runtime -->|Load Models| S3
    Runtime -->|Portfolios and Trades| PG
    Runtime -->|Historical Data| QDB
    
    API <-->|Manage Strategies| Runtime
    API -->|Read & Write| PG
    API -->|Read| QDB
    API -->|Cache| RS
    
    Frontend <-->|REST API| API
```

---

## Core Microservices

The platform is divided into specialized, isolated microservices that communicate predominantly over Kafka to ensure deep decoupling and minimum latency.

### 1. Ingestor
Connects directly to the Upstox V3 WebSocket feed. It subscribes to a dynamic list of instruments, including the top 100 highly liquid NSE equities globally recognized in the NIFTY index, and publishes raw tick data (Last Traded Price, Volume, Open Interest, and Level 2 Market Depth) directly to Kafka.

### 2. Market Scanner
Operates on a scheduled interval to scan the broader market for high-momentum breakout candidates. It calculates momentum scores based on price action and trading volume, alerting the Ingestor to dynamically subscribe to new, highly-active symbols.

### 3. Feature Engine
Consumes the raw market ticks from Kafka and calculates enriched technical indicators in real-time. This includes Volume-Weighted Average Price, Order Book Imbalance, and short-term Simple Moving Averages. The enriched data stream is then republished back to the event bus for downstream execution elements.

### 4. Edge Detector
A real-time analytics module that listens to the market feed and mathematically computes dynamic local support and resistance levels. It constantly maps out the structural boundaries of the market, helping algorithmic strategies identify optimal entry and exit edges based on recent price consolidation zones.

### 5. Market Persistor
Listens to all enriched market data passing through Kafka and heavily batches it for insertion into QuestDB, an ultra-fast time-series database. This ensures every single tick, quote, and calculated metric is safely and efficiently stored for long-term historical analysis.

### 6. Strategy Runtime (Algorithm Engine)
The core execution environment. This service loads trading strategies built using the native Quant SDK. It handles everything from evaluating live market signals and managing the portfolio, to strictly sizing positions and tracking daily risk compliance. It interfaces securely with the Upstox API to submit live market orders, or routes them through an internal virtual paper exchange simulator.

### 7. Parameter Optimizer
A background service responsible for continuous hyperparameter tuning. It performs grid searches across historical datasets to find the most mathematically optimal parameters (such as trailing stop-loss percentages or momentum thresholds) for active strategies, adjusting them as market regimes change.

### 8. Historical Replayer & Data Backfiller
The Data Backfiller strictly downloads historical OHLCV data from the Upstox API while elegantly managing rigorous rate limits. The Historical Replayer is then able to stream this stored historical data back into the main Kafka bus at expedited speeds, mimicking a live market and allowing for extremely accurate, event-driven time-series backtesting.

### 9. API Gateway
A robust FastAPI REST interface that acts as the secure bridge between the internal cluster and external applications. It handles routing and caching (via Redis) for real-time portfolio metrics, historical chart data, strategy management, and live performer leaderboards.

### 10. Quant Frontend
A sleek Next.js resilient dashboard providing a graphical interface for the platform. It visualizes scanner results, active portfolio positions, live equity curves, and allows users to manually backtest custom strategies or transition them cleanly into live execution.

### 11. System Doctor
A comprehensive diagnostics utility that continuously monitors the health of the Kafka broker, the databases, and broker API connectivity, ensuring the platform remains completely stable throughout the volatile trading day.

---

## Database Infrastructure

The persistence layer is intentionally fragmented based on distinct optimization requirements:

- **QuestDB**: Optimized for millions of rows of high-frequency time-series data. Stores all raw ticks, historical OHLC candles, option greeks, and microstructure metrics.
- **PostgreSQL**: Acts as the relational state store. Manages user authentication, instrument metadata mappings, strategy definitions, portfolio balances, active positions, and the comprehensive audit trail of all executed orders.
- **Redis**: Provides fast, ephemeral caching for the API Gateway and connection limit management.
- **Minio S3**: Object storage designated to save trained machine learning models, persistent strategy state files, and routine system backups.

---

## Writing a Strategy

The platform provides a flexible SDK for implementing quantitative logic inside the Strategy Runtime. 

```python
from quant_sdk import QCAlgorithm, Resolution

class MomentumStrategy(QCAlgorithm):
    def Initialize(self):
        self.SetCash(20000)
        self.symbol = "NSE_EQ|INE002A01018"
        self.AddEquity(self.symbol, Resolution.Minute)
        self.sma = self.SMA(self.symbol, 20, Resolution.Minute)

    def OnData(self, data):
        bar = data[self.symbol]
        
        # Determine trend and allocate portfolio sizing
        if not self.Portfolio[self.symbol].Invested:
            if bar.Close > self.sma.Value:
                self.SetHoldings(self.symbol, 1.0) 
        elif bar.Close < self.sma.Value:
            self.Liquidate(self.symbol)
```

---

## Upstox Access Token

KIRA uses the **Upstox V3 API** for real-time market data, historical backfill, and live order execution. Upstox access tokens expire every 24 hours, so you need to regenerate one each trading day before the market opens.

### How to Get Your Token

1. Log in to the [Upstox Developer Console](https://developer.upstox.com/).
2. Create a new application (or open your existing one).
3. Set the **Redirect URL** to `http://localhost` in your app settings.
4. Generate your authorization URL in this format and open it in your browser:
   ```
   https://api.upstox.com/v2/login/authorization/dialog?response_type=code&client_id=YOUR_API_KEY&redirect_uri=http://localhost
   ```
5. After logging in, Upstox will redirect you to `http://localhost?code=AUTHORIZATION_CODE`. Copy the `code` value from the URL.
6. Exchange the code for an access token by running:
   ```bash
   curl -X POST https://api.upstox.com/v2/login/authorization/token \
     -H 'Content-Type: application/x-www-form-urlencoded' \
     -d 'code=YOUR_CODE&client_id=YOUR_API_KEY&client_secret=YOUR_API_SECRET&redirect_uri=http://localhost&grant_type=authorization_code'
   ```
7. Copy the `access_token` value from the JSON response.

### Updating the Token Daily

Once you have the new token, update your `.env` file before starting (or restarting) the platform:

```bash
# Open the .env file and update the UPSTOX_ACCESS_TOKEN value
UPSTOX_ACCESS_TOKEN=your_new_token_here

# Then restart the ingestion and strategy services to pick up the new token
docker compose -f infra/docker-compose.yml restart ingestion strategy_runtime
```

For a smoother daily experience, you can automate the token fetch using a simple Python script that calls the Upstox OAuth flow and updates the `.env` file automatically before market open (9:00 AM IST).

---

## A Note on Sharpe Ratio Stability

The Sharpe Ratio reported in your backtest results can be **highly unreliable for short testing periods**.

When you backtest over a period shorter than 6 months, the result from the formula is computed using very few daily return data points. Statistically, a small number of outlier days (a single massive gain or loss) can swing the Sharpe Ratio dramatically, making a mediocre strategy look exceptional or a solid strategy look terrible.

As a guide:

| Backtest Period | Sharpe Reliability |
|---|---|
| 1 - 4 weeks | Very unreliable. Ignore the value. |
| 1 - 3 months | Rough estimate. Use with caution. |
| 6 months - 1 year | Reasonably meaningful. |
| 1 year+ | Statistically robust. |

Always pair the Sharpe Ratio with the **Win Rate**, **Max Drawdown**, and **total number of trades** to get a complete picture. A strategy with 3 trades and a Sharpe Ratio of 4.5 tells you almost nothing.

---

## Disclaimer
This software is for educational, quantitative research, and informational purposes only. Do not risk money which you are afraid to lose. USE THE SOFTWARE AT YOUR OWN RISK. THE AUTHORS AND ALL AFFILIATES ASSUME NO RESPONSIBILITY FOR YOUR TRADING RESULTS.
## Core Backtest Fast Path

To scale out simulation effectively using in-memory Python calculations:
 - Our platform supports a simulated event loop using unlinked local data.
 - Ticks load datetime objects (`_dt`, `_hour`, `_minute`) internally. No per-trick datetime variables dynamically compute via loop.
 - Avoid explicit class declarations within iterations using Python `__slots__` memory assignments (`FastSlice`). Time complexity dramatically goes down!

---
