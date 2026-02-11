from quant_sdk import QCAlgorithm, Resolution

class DemoStrategy(QCAlgorithm):
    """
    A simple Moving Average Crossover strategy using the new SDK.
    """
    def Initialize(self):
        self.SetCash(100000)
        self.SetStartDate(2024, 1, 1)
        self.SetEndDate(2024, 12, 31)
        
        self.symbol = "NSE_EQ|INE002A01018" # Reliance
        self.AddEquity(self.symbol, Resolution.Minute)
        
        # Define Indicators
        self.fast_ma = self.SMA(self.symbol, 9, Resolution.Minute)
        self.slow_ma = self.SMA(self.symbol, 21, Resolution.Minute)
        
        self.Debug("Demo Strategy Initialized")

    def OnData(self, data):
        """OnData event is the primary entry point for your algorithm."""
        if not self.fast_ma.IsReady or not self.slow_ma.IsReady:
            return

        # Access Indicator Values
        fast = self.fast_ma.Value
        slow = self.slow_ma.Value
        
        self.Log(f"Price: {data[self.symbol].Close} | Fast: {fast} | Slow: {slow}")
        
        # Simple Logic
        if fast > slow:
             if not self.Portfolio.get(self.symbol) or not self.Portfolio[self.symbol].Invested:
                 self.SetHoldings(self.symbol, 1.0)
                 self.Debug(f"BUY {self.symbol} @ {data[self.symbol].Close}")
        
        elif fast < slow:
             if self.Portfolio.get(self.symbol) and self.Portfolio[self.symbol].Invested:
                 self.Liquidate(self.symbol)
                 self.Debug(f"SELL {self.symbol} @ {data[self.symbol].Close}")
