import os
import requests
import urllib.parse
token = os.environ.get("UPSTOX_ACCESS_TOKEN", "")
sym = "NSE_INDEX|Nifty 50"
url = f"https://api.upstox.com/v2/historical-candle/{urllib.parse.quote(sym)}/1minute/2023-12-31/2023-11-01"
res = requests.get(url, headers={"Accept": "application/json", "Authorization": f"Bearer {token}"})
print(res.status_code)
d = res.json()
print("Candles found:", len(d.get("data", {}).get("candles", [])))
