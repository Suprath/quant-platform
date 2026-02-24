from quant_sdk.algorithm import QCAlgorithm, Resolution
from datetime import timedelta

class SwingDeliveryStrategy(QCAlgorithm):
    """
    A Delivery (CNC) optimized Swing Trading Strategy.
    
    Logic:
    - Uses Daily timeframe data to capture multi-day trends.
    - Entry: 10-Day SMA crosses above 50-Day SMA (Golden Cross-lite).
    - Exit: 10-Day SMA crosses below 50-Day SMA or Trailing Stop Loss hits.
    - Operates entirely in CNC mode: positions are held overnight/for weeks.
    """
    def Initialize(self):
        self.SetCash(100000)
        
        # Subscribe to a basket of high-liquidity large cap stocks
        self.symbols = [
            "NSE_EQ|INE002A01018", # RELIANCE
            "NSE_EQ|INE040A01034", # HDFCBANK 
            "NSE_EQ|INE090A01021", # TCS
            "NSE_EQ|INE467B01029", # ICICIBANK
            "NSE_EQ|INE062A01020"  # SBIN
        ]
        
        self.fast_smas = {}
        self.slow_smas = {}
        self.trailing_stops = {}
        
        # Allocate 20% of capital to each stock
        self.allocation = 1.0 / len(self.symbols)
        
        for symbol in self.symbols:
            # Important: Register Daily Resolution (1440 mins) for Swing Trading
            self.AddEquity(symbol, Resolution.Daily)
            
            # 10-Day and 50-Day Simple Moving Averages
            self.fast_smas[symbol] = self.SMA(symbol, 10, Resolution.Daily)
            self.slow_smas[symbol] = self.SMA(symbol, 50, Resolution.Daily)
            self.trailing_stops[symbol] = 0.0

    def OnData(self, data):
        for symbol in self.symbols:
            if symbol not in data:
                continue
                
            bar = data[symbol]
            price = bar.Close
            
            # Ensure indicators are fully warmed up (have 50 days of data)
            if not self.slow_smas[symbol].IsReady:
                continue
                
            fast_val = self.fast_smas[symbol].Value
            slow_val = self.slow_smas[symbol].Value
            
            is_invested = self.Portfolio[symbol].Invested
            
            # --- ENTRY LOGIC ---
            if not is_invested:
                # Golden Cross: Fast SMA crosses ABOVE Slow SMA
                if fast_val > slow_val:
                    # Allocate 20% of portfolio to this stock
                    self.SetHoldings(symbol, self.allocation)
                    
                    # Set initial Stop Loss at 5% below entry price
                    self.trailing_stops[symbol] = price * 0.95
                    
            # --- EXIT LOGIC ---
            else:
                # 1. Update Trailing Stop if price goes up (Lock in profits)
                current_stop = self.trailing_stops[symbol]
                if price * 0.95 > current_stop:
                    self.trailing_stops[symbol] = price * 0.95
                    
                # 2. Death Cross (Trend Reversal) OR Trailing Stop Hit
                if fast_val < slow_val or price <= self.trailing_stops[symbol]:
                    self.Liquidate(symbol)
                    self.trailing_stops[symbol] = 0.0
