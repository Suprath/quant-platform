import os
import aiohttp
import asyncio
import urllib.parse

token = os.environ.get('UPSTOX_ACCESS_TOKEN', '').strip()
symbol = "NSE_EQ|INE002A01018"
encoded = urllib.parse.quote(symbol)

async def test_unit(session, interval):
    url = f"https://api.upstox.com/v2/historical-candle/{encoded}/{interval}/2024-01-01/2023-12-02"
    headers = {'Accept': 'application/json', 'Authorization': f'Bearer {token}'}
    try:
        async with session.get(url, headers=headers) as response:
            data = await response.json()
            if response.status == 200:
                print(f"[{interval}] SUCCESS! 200 OK. Candles:", len(data.get('data', {}).get('candles', [])))
            elif response.status == 400:
                print(f"[{interval}] 400 Bad Request:", data.get('errors', [{}])[0].get('invalidValue', 'unknown'))
            else:
                print(f"[{interval}] HTTP {response.status}:", data)
    except Exception as e:
        print(f"[{interval}] Exception:", e)

async def main():
    async with aiohttp.ClientSession() as session:
        units = ["day", "1day", "1minute", "30minute", "minute", "1", "d", "D"]
        tasks = [test_unit(session, u) for u in units]
        await asyncio.gather(*tasks)

asyncio.run(main())
