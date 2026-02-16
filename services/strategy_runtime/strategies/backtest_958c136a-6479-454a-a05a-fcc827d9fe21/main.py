from quant_sdk import QCAlgorithm, Resolution
import datetime

class SimpleMeanReversion(QCAlgorithm):
    """Simple strategy that trades every day - for testing only"""
    
    def Initialize(self):
        self.SetCash(500000)
        self.SetStartDate(2023, 1, 1)
        self.SetEndDate(2024, 12, 31)
        self.SetLeverage(3.0)
        
        self.symbol = "NSE_EQ|INE002A01018"
        self.AddEquity(self.symbol, Resolution.Tick)
        
        self.traded_today = False
        self.vwap = 0
        self.total_pv = 0
        self.total_vol = 0
        
    def OnData(self, data):
        if not data.ContainsKey(self.symbol):
            return
            
        tick = data[self.symbol]
        price = tick.Price
        
        # Reset daily
        current_time = data.Time if hasattr(data, 'Time') else datetime.datetime.now()
        if isinstance(current_time, datetime.datetime):
            time_only = current_time.time()
            if time_only < datetime.time(9, 16):
                self.traded_today = False
                self.vwap = price
                self.total_pv = price * tick.Quantity
                self.total_vol = tick.Quantity
        else:
            time_only = current_time
        
        # Update VWAP
        qty = getattr(tick, 'Quantity', 1)
        self.total_pv += price * qty
        self.total_vol += qty
        self.vwap = self.total_pv / self.total_vol
        
        # Simple logic: Buy if price < VWAP, Sell if price > VWAP (mean reversion)
        if not self.traded_today and time_only > datetime.time(10, 0):
            if price < self.vwap * 0.998:  # 0.2% below VWAP
                self.SetHoldings(self.symbol, 0.9)
                self.Log(f"BUY @ {price:.2f} (VWAP: {self.vwap:.2f})")
                self.traded_today = True
                self.entry = price
                self.stop = price * 0.99
                self.target = price * 1.02
                
        # Manage position
        if self.traded_today and self.Portfolio[self.symbol].Invested:
            if price <= self.stop or price >= self.target or time_only > datetime.time(15, 20):
                self.Liquidate(self.symbol)
                pnl = (price - self.entry) / self.entry * 100
                self.Log(f"SELL @ {price:.2f} | P&L: {pnl:.2f}%")