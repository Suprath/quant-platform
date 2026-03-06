import os
import requests
from dotenv import load_dotenv

load_dotenv()
token = os.getenv('UPSTOX_ACCESS_TOKEN')
headers = {'Accept': 'application/json', 'Authorization': f'Bearer {token}'}

# Try a 30-day window for 1minute data one year ago
to_date = "2023-01-31"
from_date = "2023-01-01"
# Note: KIRA uses v3 in server.py ("https://api.upstox.com/v3/historical-candle")
url = f"https://api.upstox.com/v3/historical-candle/NSE_EQ%7CINE002A01018/1minute/{to_date}/{from_date}"

print(f"Fetching: {url}")
res = requests.get(url, headers=headers)
print(f"Status: {res.status_code}")
try:
    print(res.json())
except:
    print(res.text)
