# KIRA Platform Modules

## Overview
This document describes the two core modules integrated into the KIRA platform: the **Noise Filter** and the **Position Sizer**.

### 1. Noise Filter (Module 1)
- **Role**: Assesses market signal quality and provides real-time confidence scores.
- **Data Flow**: Consumes high-frequency tick data from Kafka (`market.ticks.raw`) and stores live state in Redis.
- **API**: `GET /confidence/{symbol}` - Returns a 0-100 score for signal reliability.

### 2. Position Sizer (Module 2)
- **Role**: Computes exact share quantities and risk parameters for every trade.
- **Data Flow**: Consumes `sizing.requests` from Kafka and produces `sizing.results` back to the bus.
### 3. Integrated Strategy
- **`KiraIntegratedStrategy`**: A reference implementation that combines both modules.
- **SDK Native**: Uses `self.GetKiraConfidence()` and `self.GetKiraPositionSize()` provided by the `QCAlgorithm` base class.
- **Unified Routing**: All requests are routed through the **API Gateway** (`api_gateway:8000`), ensuring a single entry point for all platform intelligence.
- **Location**: `services/strategy_runtime/strategies/kira_integrated_strategy.py`

## Architecture
Both modules are implemented as modular, containerized microservices and share a common library (`kira-shared`). Strategies access these services through the **Unified API Gateway** and the **Quant SDK**.

### Unified Routing (API Gateway)
- **Noise Filter Confidence**: `GET /api/v1/kira/noise-filter/confidence/{symbol}`
- **Position Sizer Logic**: Asynchronous via Kafka or health checks via `GET /api/v1/kira/position-sizer/health`.

### Kafka Topic Registry
- `sizing.requests`: Inbound orders from strategies.
- `sizing.results`: Outbound sizing decisions and exit plans.

## Running the Modules
The modules are included in the production Docker stack. To start them:
```bash
docker compose -f docker-compose.prod.yml up -d noise_filter position_sizer
```

## Testing & Verification
Comprehensive test cases and system validation scripts are located in the `tests/` directory.
- `tests/test_modules.py`: Logical verification of module interaction.
- `tests/test_integrated_strategy.py`: Logic check for the integrated strategy.
- `tests/validate_system.py`: End-to-end health and logic check.
