import statistics
from collections import deque
from quant_sdk.algorithm import QCAlgorithm  # <--- Added this import

class BollingerMeanReversion(QCAlgorithm):
    def Initialize(self):
        self.SetCash(100000)
        self.lookback = 20
        self.history = {}   # Map: Symbol -> deque of prices
        self.invested = {}  # Map: Symbol -> bool

    def OnData(self, data):
        # Loop through all symbols in the current data slice
        for symbol in data.Keys:
            tick = data[symbol]
            price = tick.Price
            
            # Initialize history for new symbols
            if symbol not in self.history:
                self.history[symbol] = deque(maxlen=self.lookback)
                
            self.history[symbol].append(price)
            
            # Wait for enough data
            if len(self.history[symbol]) < self.lookback:
                continue
                
            # --- Calculate Bollinger Bands ---
            mean = statistics.mean(self.history[symbol])
            stdev = statistics.stdev(self.history[symbol])
            upper = mean + (2 * stdev)
            lower = mean - (2 * stdev)
            
            # --- Trading Logic ---
            holding = self.Portfolio.get(symbol)
            qty = holding.Quantity if holding else 0
            
            # 1. Buy Signal (Oversold)
            if price < lower and qty <= 0:
                self.SetHoldings(symbol, 0.1) # Invest 10%
                self.Log(f"BUY {symbol} @ {price} (Oversold < {lower:.2f})")
                
            # 2. Sell Signal (Overbought)
            elif price > upper and qty >= 0:
                self.SetHoldings(symbol, -0.1) # Short 10%
                self.Log(f"SELL {symbol} @ {price} (Overbought > {upper:.2f})")
                
            # 3. Exit (Mean Reversion)
            elif qty > 0 and price >= mean:
                self.Liquidate(symbol)
                self.Log(f"EXIT LONG {symbol} @ {price} (Reverted to Mean {mean:.2f})")
                
            elif qty < 0 and price <= mean:
                self.Liquidate(symbol)
                self.Log(f"EXIT SHORT {symbol} @ {price} (Reverted to Mean {mean:.2f})")