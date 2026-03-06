import os
import requests
from dotenv import load_dotenv
import urllib.parse

load_dotenv()
token = os.getenv('UPSTOX_ACCESS_TOKEN')
headers = {'Accept': 'application/json', 'Authorization': f'Bearer {token}'}

# URL Format: https://api.upstox.com/v2/historical-candle/instrumentKey/interval/to_date/from_date
instrument_key = urllib.parse.quote('NSE_EQ|INE002A01018')

# Try 6-month old data in 1-month chunk
to_date = "2023-08-31"
from_date = "2023-08-01"
url = f"https://api.upstox.com/v2/historical-candle/{instrument_key}/1minute/{to_date}/{from_date}"

print(f"Fetching: {url}")
res = requests.get(url, headers=headers)
print(f"Status: {res.status_code}")
try:
    print(res.json().get('status', 'no-status'))
except:
    print("Failed to parse json")
