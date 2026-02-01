import os
import json
import asyncio
import websockets
import time
import logging
from confluent_kafka import Producer, Consumer
from dotenv import load_dotenv

# MarketDataFeedV3_pb2 is generated at runtime by the Dockerfile CMD
try:
    import MarketDataFeedV3_pb2 as pb
except ImportError:
    print("Warning: Protobuf classes not found. Generation pending at startup.")

load_dotenv()

# Logging Configuration
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("Dynamic-Ingestor-V3")

KAFKA_SERVER = os.getenv('KAFKA_BOOTSTRAP_SERVERS', 'kafka_bus:9092')

async def connect_upstox_v3():
    # 1. WAIT FOR KAFKA TO BE ONLINE
    producer = None
    while producer is None:
        try:
            p = Producer({'bootstrap.servers': KAFKA_SERVER, 'socket.timeout.ms': 1000})
            p.list_topics(timeout=1.0)
            producer = p
            logger.info("✅ Kafka Producer Online!")
        except Exception:
            logger.info("Waiting for Kafka...")
            await asyncio.sleep(2)

    # 2. INITIALIZE KAFKA CONSUMER FOR SCANNER SUGGESTIONS
    # This allows the ingestor to "hear" what the scanner finds
    scanner_consumer = Consumer({
        'bootstrap.servers': KAFKA_SERVER,
        'group.id': 'ingestor-dynamic-manager',
        'auto.offset.reset': 'latest'
    })
    scanner_consumer.subscribe(['scanner.suggestions'])

    # 3. UPSTOX V3 CONFIGURATION
    uri = "wss://api.upstox.com/v3/feed/market-data-feed"
    token = os.getenv('UPSTOX_ACCESS_TOKEN', '').strip()
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "*/*",
        "Api-Version": "2.0"
    }

    # Internal state to track active subscriptions
    # We start with indices to establish market context
    active_subs = {"NSE_INDEX|Nifty 50", "NSE_INDEX|India VIX"}

    logger.info(f"Connecting to Upstox V3 Live Stream...")
    
    try:
        # Compatibility check for websockets versions
        try:
            ws_conn = websockets.connect(uri, additional_headers=headers)
        except TypeError:
            ws_conn = websockets.connect(uri, extra_headers=headers)

        async with ws_conn as websocket:
            logger.info("🚀 SUCCESS: Connected to Upstox V3")

            # A. Initial Subscription for Indices
            init_req = {
                "guid": f"init_{int(time.time())}",
                "method": "sub",
                "data": {"mode": "full", "instrumentKeys": list(active_subs)}
            }
            await websocket.send(json.dumps(init_req).encode('utf-8'))
            logger.info(f"Initial subscription sent for: {active_subs}")

            # B. UNIFIED PROCESSING LOOP
            while True:
                # 1. Check for new suggestions from the Market Scanner (Non-blocking)
                msg = scanner_consumer.poll(0.01) 
                if msg and not msg.error():
                    try:
                        new_picks = json.loads(msg.value().decode('utf-8'))
                        # Only subscribe to stocks we aren't already tracking
                        to_subscribe = [p.replace(':', '|') for p in new_picks if p not in active_subs]

                        
                        if to_subscribe:
                            logger.info(f"🔥 Scanner found breakouts! Adding: {to_subscribe}")
                            dynamic_req = {
                                "guid": f"dyn_{int(time.time())}",
                                "method": "sub",
                                "data": {"mode": "full", "instrumentKeys": to_subscribe}
                            }
                            await websocket.send(json.dumps(dynamic_req).encode('utf-8'))
                            active_subs.update(to_subscribe)
                    except Exception as e:
                        logger.error(f"Error processing scanner suggestion: {e}")

                # 2. Receive and Decode Live Ticks from Upstox
                try:
                    # We use wait_for so the loop doesn't block forever 
                    # and can go back up to check for new scanner picks
                    raw_msg = await asyncio.wait_for(websocket.recv(), timeout=0.1)
                    
                    if isinstance(raw_msg, bytes):
                        # DECODE PROTOBUF
                        res = pb.MarketDataFeed()
                        res.ParseFromString(raw_msg)
                        
                        for key, feed in res.feeds.items():
                            tick_payload = None
                            
                            # Handle standard Price/OI Data
                            if feed.ltpc:
                                tick_payload = {
                                    "symbol": key,
                                    "ltp": feed.ltpc.ltp,
                                    "v": feed.ltpc.ltq,
                                    "oi": feed.ltpc.oi,
                                    "cp": feed.ltpc.cp,
                                    "timestamp": int(time.time() * 1000)
                                }
                                producer.produce('market.equity.ticks', key=key, value=json.dumps(tick_payload))
                            
                            # Handle Option Greeks if available
                            if feed.greeks:
                                greek_payload = {
                                    "symbol": key,
                                    "iv": feed.greeks.iv,
                                    "delta": feed.greeks.delta,
                                    "timestamp": int(time.time() * 1000)
                                }
                                producer.produce('market.option.greeks', key=key, value=json.dumps(greek_payload))

                        producer.poll(0) # Flush Kafka
                    else:
                        # Handle JSON (Market Status / Pings)
                        pass

                except asyncio.TimeoutError:
                    # No tick received in 0.1s, loop back to check scanner suggestions
                    continue

    except Exception as e:
        logger.error(f"V3 Connection Error: {e}")
        if "401" in str(e):
            logger.error("❌ AUTH EXPIRED: Update UPSTOX_ACCESS_TOKEN in .env")
        await asyncio.sleep(10)

if __name__ == "__main__":
    try:
        asyncio.run(connect_upstox_v3())
    except KeyboardInterrupt:
        logger.info("Ingestor stopped.")