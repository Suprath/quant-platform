import urllib.parse
import requests
import json
QUESTDB_URL = "http://localhost:9000"
sym = "NSE_INDEX|Nifty 50"
start_date = "2023-01-01"
end_date = "2023-12-31"

query = f"""
SELECT first(timestamp) FROM ohlc 
WHERE symbol = '{sym}' 
  AND timestamp >= '{start_date}T00:00:00.000000Z' 
  AND timestamp <= '{end_date}T23:59:59.999999Z'
SAMPLE BY 1d
"""
encoded = urllib.parse.urlencode({"query": query})
resp = requests.get(f"{QUESTDB_URL}/exec?{encoded}")
print(resp.status_code)
print(json.dumps(resp.json(), indent=2))
