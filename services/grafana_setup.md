# Grafana Setup Guide - Paper Trading Visualization

## Connection Setup

1. **Open Grafana**: Navigate to `http://localhost:3000`
   - Default credentials: `admin` / `admin`

2. **Add PostgreSQL Data Source**:
   - Click **Configuration** (gear icon) > **Data Sources** > **Add data source**
   - Select **PostgreSQL**
   - Configure:
     ```
     Host: postgres_metadata:5432
     Database: quant_platform
     User: admin
     Password: password123
     SSL Mode: disable
     ```
   - Click **Save & Test**

## Dashboard Panels

### Panel 1: Scanner Top Picks (Table)
Shows the latest 10 stocks picked by the scanner.

**SQL Query**:
```sql
SELECT 
  timestamp,
  symbol,
  ROUND(ltp, 2) as price,
  ROUND(score, 0) as momentum_score,
  volume
FROM scanner_results
WHERE timestamp > NOW() - INTERVAL '1 day'
ORDER BY timestamp DESC
LIMIT 10;
```

### Panel 2: Trade Execution History (Table)
Shows all paper trades executed today.

**SQL Query**:
```sql
SELECT 
  timestamp,
  symbol,
  transaction_type as action,
  quantity,
  price,
  ROUND(pnl, 2) as realized_pnl,
  strategy_id
FROM executed_orders
WHERE timestamp > NOW() - INTERVAL '1 day'
ORDER BY timestamp DESC;
```

### Panel 3: Portfolio Equity Over Time (Time Series)
Visualizes your portfolio value changing in real-time.

**SQL Query**:
```sql
SELECT 
  last_updated as time,
  equity as "Portfolio Value"
FROM portfolios
WHERE user_id = 'default_user'
ORDER BY last_updated;
```

### Panel 4: Current Open Positions (Table)
Shows what stocks you're currently holding.

**SQL Query**:
```sql
SELECT 
  symbol,
  quantity,
  ROUND(avg_price, 2) as avg_buy_price,
  last_updated
FROM positions
WHERE quantity > 0
ORDER BY last_updated DESC;
```

### Panel 5: Total P&L Today (Stat Panel)
Shows daily profit/loss as a single number.

**SQL Query**:
```sql
SELECT 
  SUM(pnl) as "Total P&L"
FROM executed_orders
WHERE timestamp > CURRENT_DATE
  AND transaction_type = 'SELL';
```

## Auto-Refresh
Set dashboard to auto-refresh every **10 seconds** to see live updates.

## Alerts (Optional)
You can set alerts in Grafana to notify you when:
- A trade is executed (`executed_orders` table gets new row)
- Portfolio drops below a threshold
- A high-momentum stock is found by scanner
