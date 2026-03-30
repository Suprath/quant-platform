# services/scanner/tests/test_conviction_ranker.py
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from unittest.mock import patch
from conviction_ranker import get_top_symbols_by_conviction

def test_returns_list_of_symbols():
    mock_rows = [
        {"symbol": "RELIANCE", "conviction_score": 0.75},
        {"symbol": "INFY",     "conviction_score": 0.68},
    ]
    with patch("conviction_ranker._query_top_symbols", return_value=mock_rows), \
         patch("conviction_ranker.create_engine"):
        result = get_top_symbols_by_conviction(top_n=2)
    assert result == ["RELIANCE", "INFY"]

def test_caps_at_top_n():
    mock_rows = [{"symbol": f"SYM{i}", "conviction_score": 1.0 - i * 0.01} for i in range(20)]
    with patch("conviction_ranker._query_top_symbols", return_value=mock_rows), \
         patch("conviction_ranker.create_engine"):
        result = get_top_symbols_by_conviction(top_n=5)
    assert len(result) == 5

def test_returns_empty_on_no_data():
    with patch("conviction_ranker._query_top_symbols", return_value=[]), \
         patch("conviction_ranker.create_engine"):
        result = get_top_symbols_by_conviction(top_n=10)
    assert result == []
