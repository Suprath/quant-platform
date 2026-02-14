from quant_sdk.algorithm import QCAlgorithm

class MomentumScannerStrategy(QCAlgorithm):
    def Initialize(self):
    self.SetCash(100000)
    self.SetStartDate(2024, 1, 8)
    self.SetEndDate(2024, 1, 10)
    self.AddUniverse(self.Selection)
    print("INIT: Registered for Dynamic Universe")

    def Selection(self, coarse):
    return []

    def OnData(self, slice):
    for symbol in slice.Keys:
    if symbol not in self.Portfolio: continue
    holding = self.Portfolio[symbol]
    tick = slice[symbol]
    if not holding.Invested:
    self.SetHoldings(symbol, 0.15)
    print(f"BUY {symbol} @ {tick.Price}")
    elif holding.Invested:
    pnl_pct = (tick.Price - holding.AveragePrice) / holding.AveragePrice
    if pnl_pct > 0.01:
    self.Liquidate(symbol)
    print(f"SELL (Take Profit) {symbol} @ {tick.Price}")
    elif pnl_pct < -0.01:
    self.Liquidate(symbol)
    print(f"SELL (Stop Loss) {symbol} @ {tick.Price}")
    