import os
import json
import asyncio
import websockets
import time
import logging
from confluent_kafka import Producer
from dotenv import load_dotenv

# We import the generated proto file. 
# Note: This file is generated at container startup by the Dockerfile CMD.
try:
    import MarketDataFeedV3_pb2 as pb
except ImportError:
    print("Protobuf file not found. Ensure Dockerfile compiled the .proto file.")

load_dotenv()

# Logging Configuration
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("Ingestor-V3")

KAFKA_SERVER = os.getenv('KAFKA_BOOTSTRAP_SERVERS', 'kafka_bus:9092')

async def connect_upstox_v3():
    """Handles the V3 WebSocket life cycle: Connect -> Auth -> Sub -> Decode"""
    
    # 1. WAIT FOR KAFKA TO BE READY
    producer = None
    logger.info(f"Connecting to Kafka at {KAFKA_SERVER}...")
    while producer is None:
        try:
            # We use a short timeout for the health check
            p = Producer({'bootstrap.servers': KAFKA_SERVER, 'socket.timeout.ms': 1000})
            p.list_topics(timeout=1.0)
            producer = p
            logger.info("✅ Kafka is Online!")
        except Exception:
            logger.info("Kafka not ready, retrying in 2s...")
            await asyncio.sleep(2)

    # 2. UPSTOX V3 CONFIGURATION
    # Live V3 URL as per documentation
    uri = "wss://api.upstox.com/v3/feed/market-data-feed"
    token = os.getenv('UPSTOX_ACCESS_TOKEN', '').strip()
    
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "*/*",
        "Api-Version": "2.0"
    }

    # 3. INSTRUMENT SUBSCRIPTION LIST (The Quant Stack)
    instruments = [
        "NSE_EQ|INE002A01018",  # Reliance Industries (Stock)
        "NSE_INDEX|Nifty 50",    # Nifty 50 (Market Benchmark)
        "NSE_INDEX|India VIX"    # India VIX (Fear/Volatility Gauge)
    ]

    logger.info(f"Attempting Upstox V3 Connection to {uri}...")
    
    try:
        # Compatibility handling for websockets library v14+ (additional_headers)
        # vs older versions (extra_headers)
        try:
            ws_conn = websockets.connect(uri, additional_headers=headers)
        except TypeError:
            ws_conn = websockets.connect(uri, extra_headers=headers)

        async with ws_conn as websocket:
            logger.info("🚀 SUCCESS: Connected to Upstox V3 Live Stream!")

            # Construct the binary subscription request (Ref: PDF Page 28 & V3 Docs)
            sub_request = {
                "guid": f"quant_mac_{int(time.time())}",
                "method": "sub",
                "data": {
                    "mode": "full", # 'full' provides LTPC, Market Depth, and OI
                    "instrumentKeys": instruments
                }
            }
            
            # Send as binary (utf-8 encoded string)
            await websocket.send(json.dumps(sub_request).encode('utf-8'))
            logger.info(f"Subscribed to: {', '.join(instruments)}")

            # 4. DATA PROCESSING LOOP
            async for message in websocket:
                if isinstance(message, bytes):
                    # DECODE PROTOBUF BINARY
                    try:
                        res = pb.MarketDataFeed()
                        res.ParseFromString(message)
                        
                        for key, feed in res.feeds.items():
                            if feed.ltpc:
                                tick = {
                                    "symbol": key,
                                    "ltp": feed.ltpc.ltp,
                                    "cp": feed.ltpc.cp,
                                    "v": feed.ltpc.ltq,  # Last Traded Quantity
                                    "oi": feed.ltpc.oi,   # Open Interest (Critical for Quant)
                                    "ltt": feed.ltpc.ltt, # Last Traded Time
                                    "timestamp": int(time.time() * 1000)
                                }
                                
                                # Broadcast to Kafka for Persistor & Feature Engine
                                producer.produce(
                                    'market.equity.ticks', 
                                    key=key, 
                                    value=json.dumps(tick)
                                )
                                producer.poll(0)
                                
                                # Log activity
                                if "VIX" in key:
                                    logger.info(f"Fear Gauge (VIX): {tick['ltp']}")
                                elif "Nifty" in key:
                                    logger.info(f"Market (Nifty): {tick['ltp']}")
                                else:
                                    logger.info(f"Stock ({key}): {tick['ltp']}")
                                    
                    except Exception as decode_err:
                        logger.error(f"Protobuf Decode Error: {decode_err}")
                else:
                    # Handle JSON messages (Market Status / Heartbeats)
                    msg_json = json.loads(message)
                    if msg_json.get("type") == "market_info":
                        logger.info(f"Market Status Received: {msg_json.get('marketInfo')}")
                    else:
                        logger.info(f"Heartbeat/Notification: {message}")

    except Exception as e:
        logger.error(f"V3 Connection Error: {e}")
        if "401" in str(e):
            logger.error("❌ AUTH ERROR: Your Access Token is invalid or expired.")
        await asyncio.sleep(10) # Wait before reconnecting

if __name__ == "__main__":
    try:
        asyncio.run(connect_upstox_v3())
    except KeyboardInterrupt:
        logger.info("Ingestor stopped by user.")