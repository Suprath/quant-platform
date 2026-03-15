import os
import urllib.request
import urllib.parse
import json

token = ""
with open('.env', 'r') as f:
    for line in f:
        if line.startswith('UPSTOX_ACCESS_TOKEN='):
            token = line.strip().split('=', 1)[1]

symbol = "NSE_EQ|INE002A01018"
encoded = urllib.parse.quote(symbol)

def test_url(url):
    req = urllib.request.Request(url, headers={'Accept': 'application/json', 'Authorization': f'Bearer {token}'})
    try:
        with urllib.request.urlopen(req) as response:
            print(url)
            print("STATUS:", response.status)
            print("BODY:", response.read().decode('utf-8')[:300])
    except Exception as e:
        print(url, "FAILED:", e)

print("\n--- Testing v2 (day) ---")
test_url(f"https://api.upstox.com/v2/historical-candle/{encoded}/day/2024-01-01/2023-12-02")

print("\n--- Testing v2 (1minute) ---")
test_url(f"https://api.upstox.com/v2/historical-candle/{encoded}/1minute/2024-01-01/2023-12-02")

print("\n--- Testing v2 (1day) ---")
test_url(f"https://api.upstox.com/v2/historical-candle/intraday/{encoded}/1day/2024-01-01/2023-12-02")

print("\n--- Testing v2 (day/1) ---")
test_url(f"https://api.upstox.com/v2/historical-candle/{encoded}/day/1/2024-01-01/2023-12-02")
