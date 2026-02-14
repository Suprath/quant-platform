
import statistics
from collections import deque

class MeanReversion(QCAlgorithm):
    def Initialize(self):
        self.SetCash(100000)
        self.lookback = 20
        self.history = {}
        self.invested = {}

    def OnData(self, data):
        for symbol in data.Keys:
            tick = data[symbol]
            price = tick.Price
            
            if symbol not in self.history:
                self.history[symbol] = deque(maxlen=self.lookback)
                self.invested[symbol] = False
            
            self.history[symbol].append(price)
            
            # Need full window
            if len(self.history[symbol]) < self.lookback:
                continue
                
            # Calculate Bollinger Bands (Simple)
            mean = statistics.mean(self.history[symbol])
            stdev = statistics.stdev(self.history[symbol])
            upper = mean + (2 * stdev)
            lower = mean - (2 * stdev)
            
            # Trading Logic
            holding = self.Portfolio.get(symbol)
            qty = holding.Quantity if holding else 0
            
            # 1. Buy Signal (Price drops below Lower Band - Oversold)
            if price < lower and qty <= 0:
                self.SetHoldings(symbol, 0.1) # Allocate 10%
                self.Log(f"BUY {symbol} @ {price} (Oversold)")
                
            # 2. Sell Signal (Price rises above Upper Band - Overbought)
            elif price > upper and qty >= 0:
                self.SetHoldings(symbol, -0.1) # Short 10%
                self.Log(f"SELL {symbol} @ {price} (Overbought)")
                
            # 3. Exit (Mean Reversion)
            elif qty > 0 and price >= mean:
                self.Liquidate(symbol)
                self.Log(f"EXIT LONG {symbol} @ {price} (Mean Reverted)")
                
            elif qty < 0 and price <= mean:
                self.Liquidate(symbol)
                self.Log(f"EXIT SHORT {symbol} @ {price} (Mean Reverted)")
