import requests
import json

url = "http://localhost:8000/api/v1/til/backtest"
payload = {
    "symbols": ["NSE_EQ|INE002A01018"],
    "start_date": "2026-02-01",
    "end_date": "2026-02-10",
    "timeframe": "1m",
    "initial_capital": 100000.0
}

try:
    response = requests.post(url, json=payload)
    print(f"Status: {response.status_code}")
    print(f"Result: {response.json()}")
except Exception as e:
    print(f"Error: {e}")
