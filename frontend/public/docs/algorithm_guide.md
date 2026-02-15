# Algorithm Design Guide

This guide provides a comprehensive reference for developing trading algorithms on the Quant Platform. It follows a structure similar to QuantConnect's Lean Engine, allowing for event-driven strategy development.

---

## 1. Essential Imports
Every algorithm file must start with valid imports. The platform pre-loads common libraries, but you should explicitly import what you need.

```python
from AlgorithmImports import *
# This includes: QCAlgorithm, Resolution, OrderType, etc.
```

**Note:** Do not import `pandas` or `numpy` for data manipulation unless you are doing custom analysis outside the platform's core data structures. The `data` object provided in `OnData` is optimized for performance.

---

## 2. The `QCAlgorithm` Class
Your strategy must be a class that inherits from `QCAlgorithm`. It requires two primary methods:
- **`Initialize()`**: Setup (cash, dates, data subscriptions).
- **`OnData(data)`**: The trading loop triggered by market updates.

### Basic Template
```python
class MyStrategy(QCAlgorithm):
    def Initialize(self):
        self.SetCash(100000)
        self.SetStartDate(2024, 1, 1)
        self.AddEquity("NSE_EQ|RELIANCE", Resolution.Minute)
        
    def OnData(self, data):
        if "NSE_EQ|RELIANCE" in data:
            price = data["NSE_EQ|RELIANCE"].Close
            if not self.Portfolio.Invested:
                self.SetHoldings("NSE_EQ|RELIANCE", 1.0)
```

---

## 3. Data Subscription & Access
You must subscribe to data in `Initialize` to receive it in `OnData`.

### Subscribe
```python
# Equity (Stocks)
self.AddEquity("NSE_EQ|TCS", Resolution.Minute)

# Indices
self.AddEquity("NSE_INDEX|Nifty 50", Resolution.Minute)
```

### Accessing Data
The `data` object in `OnData` is a **Slice**. It works like a dictionary keyed by the symbol string.
```python
bar = data["NSE_EQ|TCS"]
print(f"Time: {bar.Time}, Close: {bar.Close}, Volume: {bar.Volume}")
```

**Check for Data Existence:** Always check if the key exists before accessing to avoid errors during market holidays or gaps.
```python
if "NSE_EQ|TCS" in data:
    # safe to access
```

---

## 4. Trading API

### `SetHoldings(symbol, percentage)`
Calculates the number of shares based on current price and portfolio equity.
- `1.0`: 100% Long
- `-0.5`: 50% Short
- `0.0`: Liquidate (Close position)

### `Liquidate(symbol)`
Immediately closes all open positions for the symbol.

### `MarketOrder(symbol, quantity)` (Advanced)
If you need precise quantity control instead of percentages.
```python
self.MarketOrder("NSE_EQ|INFY", 100) # Buy 100
self.MarketOrder("NSE_EQ|INFY", -50) # Sell 50
```

---

## 5. Technical Indicators
The platform supports creating indicators in `Initialize` which automatically update with price data.

```python
def Initialize(self):
    self.rsi = self.RSI("NSE_EQ|RELIANCE", 14, Resolution.Minute)
    self.sma_fast = self.SMA("NSE_EQ|RELIANCE", 50, Resolution.Minute)

def OnData(self, data):
    # Always check if indicators are ready (have enough data)
    if not self.rsi.IsReady or not self.sma_fast.IsReady:
        return
        
    if self.rsi.Current.Value > 70:
        self.Liquidate("NSE_EQ|RELIANCE")
```

---

## 6. Logging & Debugging
- **`self.Debug(message)`**: Sends a high-priority message to the console. Good for critical events.
- **`self.Log(message)`**: Standard logging for info/tracking.

```python
self.Debug(f"Buying Reliance at {price}")
```

---

## 7. Dos and Don'ts

| Category | Do | Don't |
|----------|----|-------|
| **Logic** | Use `self.Time` for current algorithm time. | Use `datetime.now()` (it gives system time, not backtest time). |
| **Performance** | Pre-calculate heavy math in `Initialize` if possible. | Run complex loops or I/O inside `OnData`. |
| **Safety** | Check `if self.Portfolio.Invested`. | Assume you have cash; the system will reject orders if fondless. |
| **State** | Use instance variables (`self.var`) to store state. | Use global variables. |

---

## 8. Complete Example: Moving Average Crossover

```python
from AlgorithmImports import *

class MovingAverageCross(QCAlgorithm):
    def Initialize(self):
        self.SetCash(100000)
        self.symbol = "NSE_EQ|SBIN"
        self.AddEquity(self.symbol, Resolution.Minute)
        
        # Define Indicators
        self.fast = self.SMA(self.symbol, 20, Resolution.Minute)
        self.slow = self.SMA(self.symbol, 50, Resolution.Minute)
        
        # Warmup (optional, ensures indicators are ready immediately)
        self.SetWarmUp(50)

    def OnData(self, data):
        # Wait for indicators
        if not self.fast.IsReady or not self.slow.IsReady:
            return

        # Strategy Logic
        if self.fast.Current.Value > self.slow.Current.Value:
            if not self.Portfolio[self.symbol].IsLong:
                self.SetHoldings(self.symbol, 1.0)
                self.Debug(f"Golden Cross! Buying {self.symbol}")
                
        elif self.fast.Current.Value < self.slow.Current.Value:
            if self.Portfolio[self.symbol].IsLong:
                self.Liquidate(self.symbol)
                self.Debug(f"Death Cross! Selling {self.symbol}")
```
