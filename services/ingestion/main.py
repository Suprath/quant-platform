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
    # High-volume equities - Using ISINs which are often more reliable in V3
    active_subs = {
        "NSE_EQ|INE002A01018", # RELIANCE
        "NSE_EQ|INE062A01020", # SBIN
        "NSE_INDEX|Nifty 50"
    }
    debug_count = 0
    
    # State Store for Incremental Updates
    # format: { symbol: { "ltp": 0.0, "v": 0, "oi": 0, "cp": 0.0, "depth": {"buy": [], "sell": []} } }
    symbol_states = {}

    try:
        # Websockets connect
        try:
            ws_conn = websockets.connect(uri, additional_headers=headers)
        except TypeError:
            ws_conn = websockets.connect(uri, extra_headers=headers)

        async with ws_conn as websocket:
            logger.info("🚀 SUCCESS: Connected to Upstox V3")

            # 1. Subscribe Indices (LTPC-only)
            indices = [k for k in active_subs if "INDEX" in k]
            if indices:
                msg = json.dumps({
                    "guid": "sub-indices", "method": "sub",
                    "data": {"mode": "ltpc", "instrumentKeys": indices}
                })
                logger.info(f"Subscribing Indices (LTPC): {indices}")
                await websocket.send(msg.encode('utf-8'))

            # 2. Subscribe Equities (FULL mode for depth)
            equities = [k for k in active_subs if "INDEX" not in k]
            if equities:
                msg = json.dumps({
                    "guid": "sub-equities", "method": "sub",
                    "data": {"mode": "full", "instrumentKeys": equities}
                })
                logger.info(f"Subscribing Equities (FULL): {equities}")
                await websocket.send(msg.encode('utf-8'))
            
            while True:
                # 1. Scanner Logic
                msg = scanner_consumer.poll(0.1)
                if msg and not msg.error():
                    new_picks = [p.replace(':', '|') for p in json.loads(msg.value())]
                    to_sub = [p for p in new_picks if p not in active_subs]
                    if to_sub:
                        logger.info(f"🔥 Subscribing Dynamic (FULL): {to_sub}")
                        await websocket.send(json.dumps({
                            "guid": "dyn", "method": "sub",
                            "data": {"mode": "full", "instrumentKeys": to_sub}
                        }).encode('utf-8'))
                        active_subs.update(to_sub)

                # 2. Receive Data
                try:
                    raw_msg = await asyncio.wait_for(websocket.recv(), timeout=0.1)
                    
                    if isinstance(raw_msg, bytes):
                        res = pb.FeedResponse()
                        res.ParseFromString(raw_msg)
                        
                        if not res.feeds:
                            continue

                        for key, feed in res.feeds.items():
                            # Initialize state if not present
                            if key not in symbol_states:
                                symbol_states[key] = {
                                    "ltp": 0.0, "v": 0, "oi": 0, "cp": 0.0, 
                                    "depth": {"buy": [], "sell": []}
                                }
                            
                            state = symbol_states[key]
                            updated = False
                            
                            # Official V3 uses nested oneof unions
                            # FeedUnion has (ltpc, fullFeed, firstLevelWithGreeks)
                            # FullFeedUnion has (marketFF, indexFF)
                            feed_type = feed.WhichOneof('FeedUnion')
                            ltpc_obj = None
                            quotes = []

                            if feed_type == 'fullFeed':
                                ff_type = feed.fullFeed.WhichOneof('FullFeedUnion')
                                if ff_type == 'marketFF':
                                    mff = feed.fullFeed.marketFF
                                    if mff.HasField('ltpc'): ltpc_obj = mff.ltpc
                                    if mff.HasField('marketLevel'):
                                        quotes = mff.marketLevel.bidAskQuote
                                elif ff_type == 'indexFF':
                                    iff = feed.fullFeed.indexFF
                                    if iff.HasField('ltpc'): ltpc_obj = iff.ltpc
                            elif feed_type == 'ltpc':
                                ltpc_obj = feed.ltpc
                            
                            # DEBUG: Log raw LTPC structure for equities and indices
                            if ("NSE_EQ" in key or "Nifty 50" in key) and debug_count < 50:
                                ltpc_data = str(ltpc_obj).replace('\n', ' ') if ltpc_obj else "NONE"
                                logger.info(f"🔍 FEED {key} | Type: {feed_type} | LTPC: {ltpc_data} | Quotes: {len(quotes)}")

                            # 1. Update LTP/LTPC
                            if ltpc_obj:
                                if ltpc_obj.ltp > 0:
                                    state['ltp'] = ltpc_obj.ltp
                                    updated = True
                                if ltpc_obj.ltq > 0: state['v'] = ltpc_obj.ltq
                                if ltpc_obj.cp > 0: state['cp'] = ltpc_obj.cp

                            # 2. Update Depth (Official: bidAskQuote contains both buy/sell info)
                            if quotes:
                                state['depth']['buy'] = [{"price": q.bidP, "quantity": q.bidQ} for q in quotes if q.bidP > 0]
                                state['depth']['sell'] = [{"price": q.askP, "quantity": q.askQ} for q in quotes if q.askP > 0]
                                updated = True
                            
                            # Produce if updated and we have valid price/depth
                            if updated:
                                current_ltp = state['ltp']
                                # Backup calculate LTP from mid-price if still 0
                                if current_ltp == 0.0 and state['depth']['buy'] and state['depth']['sell']:
                                    current_ltp = round((state['depth']['buy'][0]['price'] + state['depth']['sell'][0]['price']) / 2, 2)

                                if current_ltp > 0 or state['depth']['buy']:
                                    tick = {
                                        "symbol": key,
                                        "ltp": current_ltp,
                                        "v": state['v'],
                                        "oi": state['oi'], 
                                        "cp": state['cp'],
                                        "depth": state['depth'],
                                        "timestamp": int(time.time() * 1000)
                                    }
                                    
                                    if debug_count % 100 == 0:
                                        logger.info(f"📈 TICK {key}: {tick['ltp']} | Depth: {len(tick['depth']['buy'])} levels")
                                    
                                    debug_count += 1
                                    producer.produce('market.equity.ticks', key=key, value=json.dumps(tick))
                        
                        producer.poll(0)

                except asyncio.TimeoutError:
                    continue

    except Exception as e:
        logger.error(f"Error: {e}")
        await asyncio.sleep(5)

if __name__ == "__main__":
    asyncio.run(connect_upstox_v3())