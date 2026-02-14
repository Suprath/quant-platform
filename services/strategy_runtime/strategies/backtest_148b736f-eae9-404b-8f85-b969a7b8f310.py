from quant_sdk.algorithm import QCAlgorithm
from quant_sdk.algorithm import Resolution

class GoldenCrossStrategy(QCAlgorithm):
    def Initialize(self):
        self.SetStartDate(2024, 1, 1)
        self.SetEndDate(2024, 1, 10)
        self.SetCash(100000)
        
        # Subscribe to Symbol
        self.symbol = "NSE_EQ|INE002A01018" # Reliance
        self.AddEquity(self.symbol, Resolution.Minute)
        
        # Define Indicators
        self.fast_sma = self.SMA(self.symbol, 50, Resolution.Minute)
        self.slow_sma = self.SMA(self.symbol, 200, Resolution.Minute)
        
        # State
        self.invested = False
        
    def OnData(self, data):
        # Ensure data exists for symbol
        if not data.ContainsKey(self.symbol):
            return
            
        # Ensure indicators are ready
        if not self.fast_sma.IsReady or not self.slow_sma.IsReady:
            return
            
        fast = self.fast_sma.Value
        slow = self.slow_sma.Value
        
        # Entry Logic (Golden Cross)
        if not self.invested and fast > slow:
            self.Log(f"Golden Cross! Fast: {fast:.2f} > Slow: {slow:.2f}")
            self.SetHoldings(self.symbol, 1.0) # 100% Portfolio
            self.invested = True
            
        # Exit Logic (Death Cross)
        elif self.invested and fast < slow:
            self.Log(f"Death Cross! Fast: {fast:.2f} < Slow: {slow:.2f}")
            self.Liquidate(self.symbol)
            self.invested = False