# services/eod_ingestor/tests/test_bhavcopy_parse.py
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import io
from main import parse_bhavcopy

SAMPLE_CSV = """SYMBOL,SERIES,OPEN,HIGH,LOW,CLOSE,LAST,PREVCLOSE,TOTTRDQTY,TOTTRDVAL,TIMESTAMP,TOTALTRADES,ISIN,DELIV_QTY,DELIV_PER
RELIANCE,EQ,2900.0,2950.0,2880.0,2920.0,2920.0,2890.0,1000000,2920000000,24-Mar-2026,50000,INE002A01018,600000,60.0
INFY,EQ,1750.0,1800.0,1740.0,1780.0,1780.0,1760.0,500000,890000000,24-Mar-2026,25000,INE009A01021,350000,70.0
JUNKSTOCK,BE,100.0,105.0,99.0,102.0,102.0,100.0,10000,1020000,24-Mar-2026,500,INE999Z99999,5000,50.0
"""

def test_parse_filters_eq_series_only():
    df = parse_bhavcopy(io.StringIO(SAMPLE_CSV))
    assert len(df) == 2  # JUNKSTOCK is 'BE' series, should be excluded
    assert set(df['SYMBOL'].tolist()) == {'RELIANCE', 'INFY'}

def test_parse_computes_conviction_score():
    df = parse_bhavcopy(io.StringIO(SAMPLE_CSV))
    reliance = df[df['SYMBOL'] == 'RELIANCE'].iloc[0]
    # conviction_score = DELIV_QTY / TOTTRDQTY = 600000 / 1000000 = 0.6
    assert abs(reliance['conviction_score'] - 0.6) < 0.001

def test_parse_handles_zero_volume():
    csv_with_zero = SAMPLE_CSV.replace("1000000,2920000000", "0,0")
    df = parse_bhavcopy(io.StringIO(csv_with_zero))
    reliance = df[df['SYMBOL'] == 'RELIANCE'].iloc[0]
    assert reliance['conviction_score'] == 0.0  # No division by zero
