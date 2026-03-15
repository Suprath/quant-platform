import os
import logging
from services.strategy_runtime.backtest_runner import fetch_historical_data

logging.basicConfig(level=logging.INFO)

# Set Env for QuestDB
os.environ['QUESTDB_HOST'] = 'localhost' # Since we run from host and port 8812 is mapped

def test():
    symbol = "NSE_EQ|INE002A01018"
    start = "2024-01-08"
    end = "2024-01-10"
    
    print(f"Testing fetch for {symbol} from {start} to {end}...")
    candles = fetch_historical_data(symbol, start, end)
    print(f"Candles Found: {len(candles)}")
    if len(candles) > 0:
        print("First Candle:", candles[0])
        print("Last Candle:", candles[-1])

if __name__ == "__main__":
    test()
