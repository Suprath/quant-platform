import os
import json
import asyncio
import websockets
import time
from confluent_kafka import Producer
from dotenv import load_dotenv

load_dotenv()

# Kafka Setup
KAFKA_SERVER = os.getenv('KAFKA_BOOTSTRAP_SERVERS', 'kafka_bus:9092')

async def connect_upstox_v3():
    # Compilation happens at Docker startup, so we import here
    import MarketDataFeedV3_pb2 as pb 

    # 1. WAIT FOR KAFKA TO BE READY
    producer = None
    print(f"Checking Kafka at {KAFKA_SERVER}...")
    while producer is None:
        try:
            producer = Producer({'bootstrap.servers': KAFKA_SERVER})
            producer.list_topics(timeout=2.0) # Test connection
            print("✅ Kafka is Online!")
        except Exception:
            print("Kafka not ready, waiting 3 seconds...")
            await asyncio.sleep(3)

    # 2. CONNECT TO UPSTOX
    uri = "wss://api.upstox.com/v3/feed/market-data-feed"
    headers = {
        "Authorization": f"Bearer {os.getenv('UPSTOX_ACCESS_TOKEN').strip()}",
        "Accept": "*/*",
        "Api-Version": "2.0"
    }

    print(f"Connecting to Upstox V3: {uri}")
    
    try:
        # Compatibility check for websockets library version
        try:
            ws_conn = websockets.connect(uri, additional_headers=headers)
        except TypeError:
            ws_conn = websockets.connect(uri, extra_headers=headers)

        async with ws_conn as websocket:
            print("🚀 SUCCESS: Connected to Upstox V3 Live Stream!")

            subscription_request = {
                "guid": str(int(time.time())),
                "method": "sub",
                "data": {
                    "mode": "full",
                    "instrumentKeys": ["NSE_EQ|INE002A01018"] # RELIANCE
                }
            }
            
            await websocket.send(json.dumps(subscription_request).encode('utf-8'))
            print("Subscription sent for RELIANCE.")

            async for message in websocket:
                if isinstance(message, bytes):
                    feed_response = pb.MarketDataFeed()
                    feed_response.ParseFromString(message)
                    
                    for key, feed in feed_response.feeds.items():
                        if feed.ltpc:
                            tick = {
                                "symbol": key,
                                "ltp": feed.ltpc.ltp,
                                "cp": feed.ltpc.cp,
                                "v": feed.ltpc.ltq 
                            }
                            producer.produce('market.equity.ticks', value=json.dumps(tick))
                            producer.poll(0)
                            print(f"Tick: {key} @ {tick['ltp']}")
                else:
                    print(f"Server Message: {message}")

    except Exception as e:
        # If we get a 401 here, the token in .env is definitely expired
        print(f"V3 Connection Error: {e}")
        if "401" in str(e):
            print("❌ ERROR: Access Token is invalid or expired. Refresh using auth_helper.py")
        await asyncio.sleep(10) 

if __name__ == "__main__":
    asyncio.run(connect_upstox_v3())