class DemoStrategy(QCAlgorithm):
    def Initialize(self):
        self.SetCash(10000)
        self.AddEquity("NSE_EQ|RELIANCE")
