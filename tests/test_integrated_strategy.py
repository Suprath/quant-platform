import sys
import os
import unittest
from unittest.mock import MagicMock, patch

# --- ROBUST MOCKING ---
sys.modules['fastapi'] = MagicMock()
sys.modules['aiokafka'] = MagicMock()
sys.modules['redis'] = MagicMock()
sys.modules['redis.asyncio'] = MagicMock()
sys.modules['requests'] = MagicMock()

# --- PATH SETUP ---
sys.path.append(os.path.abspath(os.path.join(os.getcwd(), 'services/strategy_runtime')))
sys.path.append(os.path.abspath(os.path.join(os.getcwd(), 'services/strategy_runtime/quant_sdk')))

from strategies.kira_integrated_strategy import KiraIntegratedStrategy

class TestKiraIntegratedStrategy(unittest.TestCase):
    def setUp(self):
        self.algo = KiraIntegratedStrategy()
        self.algo.Initialize()
        
        # Mock Portfolio and Engine
        self.algo.Portfolio = MagicMock()
        self.algo.Portfolio.TotalPortfolioValue = 1000000
        self.algo.Portfolio.get.return_value = None # No holdings initially
        self.algo.MarketOrder = MagicMock()
        self.algo.Liquidate = MagicMock()
        self.algo.Log = MagicMock()

    @patch('requests.get')
    def test_entry_with_high_confidence(self, mock_get):
        # Mock NF returns 80 confidence
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = {"confidence": 80}
        
        # Simulation Data
        symbol = "NSE_EQ|RELIANCE"
        data = MagicMock()
        data.Keys = [symbol]
        data.__getitem__.side_effect = lambda x: MagicMock(Price=2500) if x == symbol else None
        
        # 1. First tick (record price)
        self.algo.OnData(data)
        
        # 2. Second tick (momentum signal + NF check)
        data.__getitem__.side_effect = lambda x: MagicMock(Price=2510) if x == symbol else None
        self.algo.OnData(data)
        
        # Assertions
        self.algo.MarketOrder.assert_called_once()
        self.algo.Log.assert_any_call("KIRA APPROVED: Buying 199 shares of NSE_EQ|RELIANCE @ 2510")

    @patch('requests.get')
    def test_no_entry_with_low_confidence(self, mock_get):
        # Mock NF returns 40 confidence (< 60 threshold)
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = {"confidence": 40}
        
        symbol = "NSE_EQ|RELIANCE"
        data = MagicMock()
        data.Keys = [symbol]
        data.__getitem__.side_effect = lambda x: MagicMock(Price=2500) if x == symbol else None
        
        # 1. First tick
        self.algo.OnData(data)
        
        # 2. Second tick (momentum exists but confidence low)
        data.__getitem__.side_effect = lambda x: MagicMock(Price=2510) if x == symbol else None
        self.algo.OnData(data)
        
        # Assertions
        self.algo.MarketOrder.assert_not_called()

    def test_exit_on_profit_target(self):
        symbol = "NSE_EQ|RELIANCE"
        holding = MagicMock(Quantity=20, AveragePrice=2500)
        self.algo.Portfolio.get.return_value = holding
        self.algo.last_prices[symbol] = 2500 # Initialize to avoid continue
        
        data = MagicMock()
        data.Keys = [symbol]
        data.__getitem__.side_effect = lambda x: MagicMock(Price=2630) if x == symbol else None
        self.algo.OnData(data)
        
        self.algo.Liquidate.assert_called_once_with(symbol)
        self.algo.Log.assert_any_call("TARGET HIT: Exit NSE_EQ|RELIANCE @ 2630 | PnL: 5.20%")

if __name__ == "__main__":
    unittest.main()
