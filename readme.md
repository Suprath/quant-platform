# 🚀 Production-Grade Quant Trading Platform (Indian Markets)

A high-frequency, event-driven algorithmic trading platform designed for **NSE/BSE (India)** using the **Upstox V3 API**.

Built with a microservices architecture, it handles real-time ingestion, market microstructure analysis (VWAP, Order Book Imbalance), and automated execution, all while staying within API free-tier rate limits.

---

## 🏗 Architecture

The system follows a reactive, event-driven design:

| Layer | Component | Technology | Purpose |
| :--- | :--- | :--- | :--- |
| **1. Scout** | **Market Scanner** | Python | Scans 100+ stocks every 5 mins to find high-momentum breakout candidates. |
| **2. Sensor** | **Ingestor** | Upstox V3 / Protobuf | Connects to WebSocket, handles dynamic subscriptions from Scanner. |
| **3. Bus** | **Message Bus** | Apache Kafka | Low-latency streaming of Ticks, Greeks, and Signals. |
| **4. Storage** | **Time-Series DB** | QuestDB | Stores high-frequency Ticks, OHLC, and Greeks. |
| **4. Storage** | **Relational DB** | PostgreSQL | Stores Instrument Master, User Metadata, and Trade Logs. |
| **5. Brain** | **Feature Engine** | Pandas / Numpy | Calculates Real-time VWAP, OBI, Spread, and Aggressor Side. |
| **6. Hands** | **Strategy Runtime** | Python | Listens for signals and executes trades (Paper/Live). |
| **7. Window** | **API Gateway** | FastAPI | Provides a REST interface for Dashboards/Frontend. |

---

## ⚡ Quick Start

### 1. Prerequisites
*   Docker Desktop (Allocated min 6GB RAM in Settings > Resources).
*   Upstox API Credentials (API Key & Secret).
*   Python 3.11+ (for local scripts).

### 2. Installation
```bash
# Clone repository
git clone https://github.com/yourusername/quant-platform.git
cd quant-platform

# Create Environment File
cd services/ingestion
# Create a .env file with the content below