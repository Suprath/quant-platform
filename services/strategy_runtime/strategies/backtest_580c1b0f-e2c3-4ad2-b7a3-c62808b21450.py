from quant_sdk.algorithm import QCAlgorithm

class MomentumScannerStrategy(QCAlgorithm):
    def Initialize(self):
        self.SetCash(100000)
        
        # 1. Scanner Logic is handled by the Backtest Runner
        # The runner scans the market for top momentum stocks and 
        # feeds their data into this algorithm automatically.
        # We just need to handle the data in OnData.
        
        self.stop_loss_pct = 0.01
        self.take_profit_pct = 0.02
        self.invested_amount = 0.20 # Invest 20% per stock

    def OnData(self, data):
        # 'data' contains the current tick/bar for all symbols in the universe
        
        for symbol in data.Keys:
            # Skip if we already have an open position for this symbol
            if self.Portfolio[symbol].Invested:
                self.ManagePosition(symbol, data[symbol].Price)
                continue
            
            # Entry Logic: Simple Buy
            # In a real scanner, we might want to check for confirmation (e.g. price > VWAP)
            # For now, we buy immediately since the scanner already selected the best stocks.
            
            self.SetHoldings(symbol, self.invested_amount)
            self.Log(f"🟢 BUY {symbol} @ {data[symbol].Price}")

    def ManagePosition(self, symbol, current_price):
        # Access the holding object
        holding = self.Portfolio[symbol]
        
        # Calculate PnL Percentage
        pnl_pct = (current_price - holding.AveragePrice) / holding.AveragePrice
        
        # Stop Loss
        if pnl_pct < -self.stop_loss_pct:
            self.Liquidate(symbol)
            self.Log(f"🔴 SELL (Stop Loss) {symbol} @ {current_price} ({pnl_pct*100:.2f}%)")
            
        # Take Profit
        elif pnl_pct > self.take_profit_pct:
            self.Liquidate(symbol)
            self.Log(f"🟢 SELL (Take Profit) {symbol} @ {current_price} (+{pnl_pct*100:.2f}%)")
