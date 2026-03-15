import pytest
from unittest.mock import MagicMock, patch
from quant_sdk.algorithm import QCAlgorithm

class TestableAlgorithm(QCAlgorithm):
    def Initialize(self): pass
    def OnData(self, data): pass

@pytest.fixture
def algo():
    """Fixture to create a mock QCAlgorithm instance."""
    engine = MagicMock()
    engine.BacktestMode = False
    algo = TestableAlgorithm(engine=engine)
    algo.Name = "TestStrat"
    algo.Time = MagicMock()
    algo.Time.isoformat.return_value = "2024-01-01T10:00:00"
    algo.Portfolio = MagicMock()
    algo.Portfolio.TotalPortfolioValue = 1000000.0
    return algo

def test_get_kira_confidence_success(algo):
    """Test successful confidence fetch from API."""
    with patch("requests.get") as mock_get:
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = {"confidence": 75}
        
        conf = algo.GetKiraConfidence("RELIANCE")
        assert conf == 75
        mock_get.assert_called_once()

def test_get_kira_confidence_fallback(algo):
    """Test fallback to 0 on API error."""
    with patch("requests.get") as mock_get:
        mock_get.return_value.status_code = 500
        
        conf = algo.GetKiraConfidence("RELIANCE")
        assert conf == 0

def test_get_kira_position_size_full(algo):
    """Test GetKiraPositionSize with return_full=True."""
    with patch("requests.post") as mock_post:
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {
            "shares": 100,
            "exit_plan": {"stop_loss": 2450.0}
        }
        
        # Mock confidence call to return 80
        with patch.object(algo, 'GetKiraConfidence', return_value=80.0):
            result = algo.GetKiraPositionSize("RELIANCE", 2500.0, return_full=True)
            
            assert isinstance(result, dict)
            assert result["shares"] == 100
            assert result["exit_plan"]["stop_loss"] == 2450.0

def test_get_kira_position_size_fallback(algo):
    """Test fallback to 0/empty dict on API timeout."""
    with patch("requests.post") as mock_post:
        mock_post.side_effect = Exception("Timeout")
        
        size = algo.GetKiraPositionSize("RELIANCE", 2500.0)
        assert size == 0
        
        full = algo.GetKiraPositionSize("RELIANCE", 2500.0, return_full=True)
        assert full == {}
