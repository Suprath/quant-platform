# 📘 Quantitative Strategy Development Guide

This guide details how to write, backtest, and deploy algorithmic trading strategies using the **Quant Platform SDK**. The SDK is designed to be familiar to users of **QuantConnect**, providing a robust event-driven framework.

---

## 🏗 Strategy Structure

All strategies must inherit from `QCAlgorithm` and implement two required methods: `Initialize` and `OnData`.

```python
from quant_sdk import QCAlgorithm, Resolution

class MyStrategy(QCAlgorithm):
    
    def Initialize(self):
        """
        Define initial cash, start/end dates, and subscribe to data.
        """
        self.SetCash(100000)
        self.SetStartDate(2024, 1, 1)
        self.SetEndDate(2024, 12, 31)
        
        # Subscribe to a symbol
        self.symbol = "NSE_EQ|INE002A01018" # Example: Reliance
        self.AddEquity(self.symbol, Resolution.Minute)
        
        # Define Indicators
        self.sma = self.SMA(self.symbol, 20, Resolution.Minute)

    def OnData(self, data):
        """
        Event handler for market data. Called on every tick/bar.
        
        :param data: Slice object containing current data for all symbols
        """
        if not data.ContainsKey(self.symbol):
            return

        bar = data[self.symbol]
        
        # Example Trading Logic
        if not self.Portfolio[self.symbol].Invested:
            if bar.Close > self.sma.Value:
                self.SetHoldings(self.symbol, 1.0) # Buy 100% Equity
                self.Log(f"BUY Signal at {bar.Close}")
                
        elif bar.Close < self.sma.Value:
            self.Liquidate(self.symbol) # Sell everything
            self.Log(f"SELL Signal at {bar.Close}")
```

---

## 📚 API Reference

### 1. Initialization Methods
Call these inside `Initialize()`.

| Method | Description | Example |
| :--- | :--- | :--- |
| `SetCash(amount)` | Set starting capital for backtest. | `self.SetCash(100000)` |
| `SetStartDate(y, m, d)` | Set backtest start date. | `self.SetStartDate(2023, 1, 1)` |
| `SetEndDate(y, m, d)` | Set backtest end date. | `self.SetEndDate(2023, 12, 31)` |
| `AddEquity(symbol, res)` | Subscribe to a stock. | `self.AddEquity("NSE_EQ\|...", Resolution.Minute)` |
| `SetLeverage(leverage)` | Set intraday leverage (multiplier). | `self.SetLeverage(5.0)` |

### 2. Trading Methods
Call these inside `OnData()`.

| Method | Description | Example |
| :--- | :--- | :--- |
| `SetHoldings(sym, pct)` | Rebalance portfolio to target %. Positive = Long, Negative = Short. | `self.SetHoldings(self.symbol, 0.5)` |
| `Liquidate(sym)` | Close all positions for a specific symbol. If `None`, liquidates all. | `self.Liquidate(self.symbol)` |
| `SubmitOrder(sym, qty)` | Submit a manual market order (not recommended, use SetHoldings). | `self.SubmitOrder(self.symbol, 10)` |

### 3. Indicators
Helper methods to create and register technical indicators.

| Method | Description | Example |
| :--- | :--- | :--- |
| `SMA(sym, period)` | Simple Moving Average. | `self.sma = self.SMA(self.symbol, 20)` |
| `EMA(sym, period)` | Exponential Moving Average. | `self.ema = self.EMA(self.symbol, 50)` |

**Using Indicators:**
Indicators have a `.Value` property and a `.IsReady` flag.
```python
if self.sma.IsReady:
    current_avg = self.sma.Value
```

### 4. Logging & Debugging
| Method | Description |
| :--- | :--- |
| `Log(message)` | Saves message to user logs (visible in dashboard). |
| `Debug(message)` | detailed debug information. |

---

## 📦 Data Objects

### Slice (`data`)
The object passed to `OnData`. It represents a "slice" of time containing data for all subscribed symbols.

- `data.ContainsKey(symbol)`: Check if data exists for symbol.
- `data[symbol]`: Access the `TradeBar` or `Tick` object.
- `data.Time`: Current timestamp of the slice.

### TradeBar / Tick
Represents the price data for a single asset.

```python
bar = data["NSE_EQ|..."]
print(f"Close: {bar.Close}, Volume: {bar.Volume}, Time: {bar.Time}")
```

- Properties: `Open`, `High`, `Low`, `Close`, `Volume`, `Time`, `Symbol`.

---

## 💼 Portfolio Management
Access current state via `self.Portfolio`.

- `self.Portfolio[symbol].Invested`: Boolean, true if you have a position.
- `self.Portfolio[symbol].Quantity`: Current held quantity (positive or negative).
- `self.Portfolio[symbol].AveragePrice`: Average entry price.
- `self.Portfolio['Cash']`: Available cash.
- `self.Portfolio['TotalPortfolioValue']`: Total Equity (Cash + Unrealized PnL).

---

## ⚡ Live Trading vs Backtesting
The same code runs in both modes!
- **Backtesting**: Engine loads historical data from QuestDB.
- **Live Trading**: Engine streams realtime data from Kafka (Upstox).

**Note:** In live trading, `SetHoldings` sends real orders to the Paper Trading Service (simulated execution).

---

## 📝 Example: EMA Crossover Strategy

```python
from quant_sdk import QCAlgorithm, Resolution

class EMACrossover(QCAlgorithm):
    def Initialize(self):
        self.SetCash(100000)
        self.symbol = "NSE_EQ|INE002A01018"
        self.AddEquity(self.symbol, Resolution.Minute)
        
        # Define Short and Long EMAs
        self.fast_ema = self.EMA(self.symbol, 9)
        self.slow_ema = self.EMA(self.symbol, 21)

    def OnData(self, data):
        if not data.ContainsKey(self.symbol): return
        
        # Wait for indicators to warm up
        if not self.fast_ema.IsReady or not self.slow_ema.IsReady:
            return

        # Check for Crossover
        if not self.Portfolio[self.symbol].Invested:
            if self.fast_ema.Value > self.slow_ema.Value:
                self.SetHoldings(self.symbol, 1.0)
                self.Log("BOUGHT on Crossover")
        
        else:
            if self.fast_ema.Value < self.slow_ema.Value:
                self.Liquidate(self.symbol)
                self.Log("SOLD on Crossover")
```
