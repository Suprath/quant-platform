import os
import urllib.request
import urllib.parse
import json

# Fetching the token from .env inside the backfiller
token = os.environ.get('UPSTOX_ACCESS_TOKEN', '').strip()
if not token:
    print("NO TOKEN FOUND in environment!")

symbol = "NSE_EQ|INE002A01018"
encoded = urllib.parse.quote(symbol)

def test_unit(unit):
    url = f"https://api.upstox.com/v3/historical-candle/{encoded}/{unit}/1/2024-01-01/2023-12-02"
    req = urllib.request.Request(url, headers={'Accept': 'application/json', 'Authorization': f'Bearer {token}'})
    try:
        with urllib.request.urlopen(req) as response:
            print(f"[{unit}] STATUS:", response.status)
            print(f"[{unit}] BODY:", response.read().decode('utf-8')[:300])
    except urllib.error.HTTPError as e:
        body = e.read().decode('utf-8')[:300]
        if 'Forbidden' not in body and '403' not in str(e):
            print(f"[{unit}] HTTPError {e.code}:", body)
    except Exception as e:
        print(f"[{unit}] FAILED:", e)

for unit in ["day", "Day", "D", "d", "1day", "daily", "month", "week", "m", "minute", "M"]:
    test_unit(unit)
