from quant_sdk.algorithm import QCAlgorithm

class MomentumScannerStrategy(QCAlgorithm):
    def Initialize(self):
        self.SetCash(100000)
        self.SetStartDate(2024, 1, 8)
        self.SetEndDate(2024, 1, 10)
        
        # 1. Request Dynamic Universe
        # This tells the backend to scan for Top 5 Momentum Stocks
        self.AddUniverse(self.Selection)
        print("INIT: Registered for Dynamic Universe")

    def Selection(self, coarse):
        # The actual selection logic is currently handled by the infrastructure
        # based on the AddUniverse call. In the future, you can filter 'coarse' here.
        return []

    def OnData(self, slice):
        # 'slice' contains data for all selected universe stocks
        for symbol in slice.Keys:
            # Ensure we have state for this symbol
            if symbol not in self.Portfolio: continue
            
            holding = self.Portfolio[symbol]
            tick = slice[symbol]
            
            if not holding.Invested:
                # Buy 15% of portfolio for each stock
                self.SetHoldings(symbol, 0.15)
                print(f"🟢 BUY {symbol} @ {tick.Price}")
            
            elif holding.Invested:
                # Exit if 1% Profit or 1% Loss
                pnl_pct = (tick.Price - holding.AveragePrice) / holding.AveragePrice
                
                if pnl_pct > 0.01:
                    self.Liquidate(symbol)
                    print(f"🔴 SELL (Take Profit) {symbol} @ {tick.Price} (+{pnl_pct*100:.2f}%)")
                elif pnl_pct < -0.01:
                    self.Liquidate(symbol)
                    print(f"🔴 SELL (Stop Loss) {symbol} @ {tick.Price} ({pnl_pct*100:.2f}%)")