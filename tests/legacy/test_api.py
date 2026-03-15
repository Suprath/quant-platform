import os
import requests
import urllib.parse
from dotenv import load_dotenv

load_dotenv('.env')
token = os.getenv('UPSTOX_ACCESS_TOKEN')
token = token.strip() if token else ''

symbol = "NSE_EQ|INE002A01018"
encoded = urllib.parse.quote(symbol)
unit = "day"
interval = "1"
to_date = "2024-01-01"
from_date = "2023-12-02"

url = f"https://api.upstox.com/v2/historical-candle/{encoded}/{interval}{unit}/{to_date}/{from_date}"
print("V2 URL:", url)
res = requests.get(url, headers={'Accept': 'application/json', 'Authorization': f'Bearer {token}'})
print("V2 Status:", res.status_code)
print("V2 JSON:", res.text[:200])

url3 = f"https://api.upstox.com/v3/historical-candle/{encoded}/{unit}/{interval}/{to_date}/{from_date}"
print("\nV3 URL:", url3)
res3 = requests.get(url3, headers={'Accept': 'application/json', 'Authorization': f'Bearer {token}'})
print("V3 Status:", res3.status_code)
print("V3 JSON:", res3.text[:200])
