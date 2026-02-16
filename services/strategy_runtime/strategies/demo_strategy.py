from quant_sdk.algorithm import QCAlgorithm

class DemoStrategy(QCAlgorithm):
    """
    A simple momentum strategy that buys when price rises above 
    the opening price and exits when it falls below.
    """
    def Initialize(self):
        self.SetCash(10000)
        self.AddEquity("NSE_EQ|RELIANCE")
        self.entry_price = {}

    def OnData(self, data):
        for symbol in data.Keys:
            tick = data[symbol]
            price = tick.Price

            holding = self.Portfolio.get(symbol)
            qty = holding.Quantity if holding else 0

            if symbol not in self.entry_price:
                # Record first seen price as reference
                self.entry_price[symbol] = price
                return

            ref = self.entry_price[symbol]

            # Buy if price rises 0.5% above reference and not invested
            if qty == 0 and price > ref * 1.005:
                self.SetHoldings(symbol, 0.9)  # 90% allocation
                self.Log(f"BUY {symbol} @ {price}")

            # Exit if price drops 0.3% below entry
            elif qty > 0 and price < ref * 0.997:
                self.Liquidate(symbol)
                self.Log(f"EXIT {symbol} @ {price}")
                self.entry_price[symbol] = price  # Reset reference
