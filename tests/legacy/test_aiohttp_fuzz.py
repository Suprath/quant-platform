import os
import aiohttp
import asyncio
import urllib.parse

token = os.environ.get('UPSTOX_ACCESS_TOKEN', '').strip()
symbol = "NSE_EQ|INE002A01018"
encoded = urllib.parse.quote(symbol)

async def test_unit(session, unit):
    url = f"https://api.upstox.com/v3/historical-candle/{encoded}/{unit}/1/2024-01-01/2023-12-02"
    headers = {'Accept': 'application/json', 'Authorization': f'Bearer {token}'}
    try:
        async with session.get(url, headers=headers) as response:
            data = await response.json()
            if response.status == 200:
                print(f"[{unit}] SUCCESS! 200 OK. Candles:", len(data.get('data', {}).get('candles', [])))
            elif response.status == 400:
                print(f"[{unit}] 400 Bad Request:", data.get('errors', [{}])[0].get('invalidValue', 'unknown'))
            else:
                print(f"[{unit}] HTTP {response.status}")
    except Exception as e:
        print(f"[{unit}] Exception:", e)

async def main():
    async with aiohttp.ClientSession() as session:
        units = ["day", "Day", "D", "d", "1day", "daily", "month", "week", "minute", "m", "M"]
        tasks = [test_unit(session, u) for u in units]
        await asyncio.gather(*tasks)

asyncio.run(main())
