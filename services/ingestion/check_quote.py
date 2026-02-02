import os
import json
import urllib.request
from dotenv import load_dotenv

load_dotenv()

def check_real_price():
    # Symbols to check
    symbols = "NSE_EQ|INE002A01018,NSE_INDEX|Nifty 50"
    url = f"https://api.upstox.com/v2/market-quote/quotes?symbol={symbols}"
    
    token = os.getenv('UPSTOX_ACCESS_TOKEN')
    if not token:
        print("❌ Error: UPSTOX_ACCESS_TOKEN is missing in .env")
        return

    # Create Request
    req = urllib.request.Request(url)
    req.add_header('Accept', 'application/json')
    req.add_header('Authorization', f"Bearer {token}")

    print(f"Querying Upstox API for {symbols}...")
    
    try:
        with urllib.request.urlopen(req) as response:
            if response.status == 200:
                raw_data = response.read().decode()
                data = json.loads(raw_data).get('data', {})
                
                print("\n--- ✅ UPSTOX API RESPONSE ---")
                for key, val in data.items():
                    print(f"Symbol: {val.get('symbol')}")
                    print(f"LTP   : {val.get('last_price')}")
                    print(f"Close : {val.get('close')}")
                    print(f"Vol   : {val.get('volume')}")
                    print("-" * 30)
            else:
                print(f"❌ API Error: {response.status}")
    except Exception as e:
        print(f"❌ Connection Error: {e}")
        print("Tip: If HTTP 401, run auth_helper.py again.")

if __name__ == "__main__":
    check_real_price()