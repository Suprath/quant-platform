from quant_sdk.algorithm import QCAlgorithm
class TestStrategy(QCAlgorithm):
    def Initialize(self):
        self.Log("Test Init")
    def OnData(self, data):
        pass