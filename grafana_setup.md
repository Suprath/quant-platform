# Grafana Monitoring Setup Guide

This guide provides the SQL queries and configuration needed to monitor live and backtested trading performance in Grafana.

## 1. Connect Data Source
1. Open Grafana at [http://localhost:3000](http://localhost:3000) (Default Login: `admin`/`admin`).
2. Go to **Connections** > **Data Sources** > **Add Data Source**.
3. Select **PostgreSQL**.
4. Configure with:
   - **Host**: `postgres_metadata:5432`
   - **Database**: `quant_platform`
   - **User**: `admin`
   - **Password**: `password123`
   - **SSL Mode**: `disable`

---

## 2. Live Trading Dashboard Panels

### Live Portfolio Value (Stat Panel)
Monitor the total current value (Cash + Equity value).
```sql
SELECT 
  balance + equity as value
FROM portfolios 
WHERE user_id = 'default_user'
```

### Cumulative P&L (Time Series Panel)
Track the profit/loss curve over time.
```sql
SELECT 
  timestamp as time,
  SUM(pnl) OVER (ORDER BY timestamp) as cumulative_pnl
FROM executed_orders
ORDER BY timestamp ASC
```

### Recent Trades (Table Panel)
```sql
SELECT 
  timestamp, 
  symbol, 
  transaction_type, 
  quantity, 
  price, 
  pnl 
FROM executed_orders 
ORDER BY timestamp DESC
```

---

## 3. Backtest Monitoring Dashboard

### Backtest Equity (Time Series)
Filter by hisotry using the `run_id` variable.
```sql
SELECT 
  timestamp as time,
  SUM(pnl) OVER (ORDER BY timestamp) as cumulative_pnl
FROM backtest_orders 
WHERE run_id = '${run_id}'
ORDER BY timestamp ASC
```

### Trade List
```sql
SELECT 
  timestamp, 
  symbol, 
  transaction_type, 
  quantity, 
  price, 
  pnl 
FROM backtest_orders 
WHERE run_id = '${run_id}'
ORDER BY timestamp DESC
```

> [!TIP]
> You can create a **Dashboard Variable** named `run_id` using the query:
> `SELECT DISTINCT run_id FROM backtest_orders`
