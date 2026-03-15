import os
import aiohttp
import asyncio
import urllib.parse
from dotenv import load_dotenv

load_dotenv('.env')
token = os.getenv('UPSTOX_ACCESS_TOKEN').strip()

async def fetch():
    symbol = "NSE_EQ|INE002A01018"
    encoded = urllib.parse.quote(symbol)
    url = f"https://api.upstox.com/v3/historical-candle/{encoded}/day/1/2024-01-01/2023-12-02"
    headers = {'Accept': 'application/json', 'Authorization': f'Bearer {token}'}
    
    async with aiohttp.ClientSession() as session:
        print("Fetching:", url)
        async with session.get(url, headers=headers) as response:
            print("Status:", response.status)
            try:
                data = await response.json()
                print("JSON:", data)
            except Exception as e:
                print("Error reading json:", e)
                try:
                    text = await response.text()
                    print("TEXT:", text[:300])
                except:
                    pass

asyncio.run(fetch())
