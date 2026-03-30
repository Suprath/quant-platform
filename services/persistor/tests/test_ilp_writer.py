# services/persistor/tests/test_ilp_writer.py
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from unittest.mock import MagicMock
from ilp_writer import write_ticks_ilp

def test_write_ticks_ilp_calls_flush():
    ticks = [
        {"instrument_token": "NSE_EQ|INE002A01018", "last_price": 2920.0,
         "volume": 1000, "oi": 0, "exchange_timestamp": 1711270200000},
    ]
    mock_sender = MagicMock()
    write_ticks_ilp(ticks, sender=mock_sender)
    mock_sender.row.assert_called_once()
    mock_sender.flush.assert_called_once()

def test_write_ticks_ilp_skips_invalid_rows():
    ticks = [{"instrument_token": "TEST", "last_price": None}]  # Missing/invalid fields
    mock_sender = MagicMock()
    write_ticks_ilp(ticks, sender=mock_sender)
    mock_sender.flush.assert_called_once()  # Flush still called; row skipped
    mock_sender.row.assert_not_called()
