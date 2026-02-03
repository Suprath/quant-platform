import os
import json
import asyncio
import websockets
import time
import logging
from confluent_kafka import Producer, Consumer
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("Ingestor-V3-Fix")
KAFKA_SERVER = os.getenv('KAFKA_BOOTSTRAP_SERVERS', 'kafka_bus:9092')

async def connect_upstox_v3():
    # Force imports after startup generation
    await asyncio.sleep(2)
    try:
        import MarketDataFeedV3_pb2 as pb
    except ImportError:
        logger.error("Protobuf missing. Rebuild container.")
        return

    # Kafka Setup
    producer = Producer({'bootstrap.servers': KAFKA_SERVER})
    scanner_consumer = Consumer({
        'bootstrap.servers': KAFKA_SERVER,
        'group.id': 'ingestor-fix-v4',
        'auto.offset.reset': 'latest'
    })
    scanner_consumer.subscribe(['scanner.suggestions'])

    uri = "wss://api.upstox.com/v3/feed/market-data-feed"
    headers = {
        "Authorization": f"Bearer {os.getenv('UPSTOX_ACCESS_TOKEN').strip()}",
        "Accept": "*/*",
        "Api-Version": "2.0"
    }

    # Tracking
    # Unified List: Indices and Equities both on LTPC for maximum compatibility
    active_subs = {
        "NSE_INDEX|Nifty 50", 
        "NSE_INDEX|India VIX", 
        "NSE_EQ|INE002A01018" # Reliance ISIN
    }

    try:
        # Websockets connect
        try:
            ws_conn = websockets.connect(uri, additional_headers=headers)
        except TypeError:
            ws_conn = websockets.connect(uri, extra_headers=headers)

        async with ws_conn as websocket:
            logger.info("🚀 SUCCESS: Connected to Upstox V3")

            # 1. Subscribe All (LTPC)
            msg = json.dumps({
                "guid": "sub-all", "method": "sub",
                "data": {"mode": "ltpc", "instrumentKeys": list(active_subs)}
            })
            logger.info(f"Subscribing ALL (LTPC): {list(active_subs)}")
            await websocket.send(msg.encode('utf-8'))
            
            while True:
                # 1. Scanner Logic
                msg = scanner_consumer.poll(0.001)
                if msg and not msg.error():
                    new_picks = [p.replace(':', '|') for p in json.loads(msg.value())]
                    to_sub = [p for p in new_picks if p not in active_subs]
                    if to_sub:
                        # Default new picks to LTPC as well for safety
                        logger.info(f"🔥 Subscribing Dynamic (LTPC): {to_sub}")
                        await websocket.send(json.dumps({
                            "guid": "dyn", "method": "sub",
                            "data": {"mode": "ltpc", "instrumentKeys": to_sub}
                        }).encode('utf-8'))
                        active_subs.update(to_sub)

                # 2. Receive Data
                try:
                    raw_msg = await asyncio.wait_for(websocket.recv(), timeout=0.1)
                    
                    if isinstance(raw_msg, bytes):
                        res = pb.FeedResponse()
                        res.ParseFromString(raw_msg)
                        
                        for key, feed in res.feeds.items():
                            # Logic: Check FF then LTPC
                            ltpc = None
                            if feed.HasField('ff') and feed.ff.HasField('ltpc'):
                                ltpc = feed.ff.ltpc
                            elif feed.HasField('ltpc'):
                                ltpc = feed.ltpc
                            
                            if ltpc:
                                tick = {
                                    "symbol": key,
                                    "ltp": ltpc.ltp,
                                    "v": ltpc.ltq,
                                    "oi": ltpc.oi, 
                                    "cp": ltpc.cp,
                                    "timestamp": int(time.time() * 1000)
                                }
                                
                                if tick['ltp'] == 0.0:
                                    logger.info(f"💤 MARKET CLOSED/NO DATA: {key} | Close: {tick['cp']} | Content: {feed}")
                                else:
                                    logger.info(f"📈 TICK: {key} @ {tick['ltp']} | Vol: {tick['v']}")
                                
                                producer.produce('market.equity.ticks', key=key, value=json.dumps(tick))
                        
                        producer.poll(0)

                except asyncio.TimeoutError:
                    continue

    except Exception as e:
        logger.error(f"Error: {e}")
        await asyncio.sleep(5)

if __name__ == "__main__":
    asyncio.run(connect_upstox_v3())