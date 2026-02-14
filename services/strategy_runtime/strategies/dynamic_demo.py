from quant_sdk.algorithm import QCAlgorithm

class DynamicMomentum(QCAlgorithm):
    def Initialize(self):
        self.SetCash(100000)
        # Request Dynamic Universe (Logic handled by Infra for now)
        self.AddUniverse(self.Selection)
        print("INIT: Requested Dynamic Universe")

    def Selection(self, coarse):
        return []

    def OnData(self, slice):
        # Iterate over all symbols in the current slice
        for symbol in slice.Keys:
            tick = slice[symbol]
            if not self.Portfolio[symbol].Invested:
                # Buy 10% of portfolio for each stock found in universe
                self.SetHoldings(symbol, 0.1)
                print(f"BUY {symbol} @ {tick.Price}")
