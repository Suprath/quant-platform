from quant_sdk.algorithm import QCAlgorithm
from .indicators_helper import BollingerBands

class MeanReversion(QCAlgorithm):
    def Initialize(self):
        self.SetCash(100000)
        self.AddUniverse(self.SelectUniverse)
        self.bands = {}

    def SelectUniverse(self, coarse):
        return coarse

    def OnData(self, data):
        for symbol in data.Keys:
            tick = data[symbol]
            price = tick.Price

            if symbol not in self.bands:
                self.bands[symbol] = BollingerBands(period=20)

            self.bands[symbol].update(price)

            if not self.bands[symbol].ready:
                continue

            upper, lower, mean = self.bands[symbol].values()
            holding = self.Portfolio.get(symbol)
            qty = holding.Quantity if holding else 0

            if price < lower and qty <= 0:
                self.SetHoldings(symbol, 0.1)
                self.Log(f"BUY {symbol} @ {price:.2f} (Below lower band)")
            elif price > upper and qty > 0:
                self.Liquidate(symbol)
                self.Log(f"SELL {symbol} @ {price:.2f} (Above upper band)")
