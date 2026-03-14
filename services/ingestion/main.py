import os
import json
import asyncio
import websockets
import time
import logging
import re
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
    unique_group_id = f"ingestor-subs-{int(time.time())}"
    subscription_consumer = Consumer({
        'bootstrap.servers': KAFKA_SERVER,
        'group.id': unique_group_id,
        'auto.offset.reset': 'earliest'
    })
    subscription_consumer.subscribe(['ingestor.subscriptions'])
    
    scanner_consumer = Consumer({
        'bootstrap.servers': KAFKA_SERVER,
        'group.id': f"ingestor-scanner-{int(time.time())}",
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
        "NSE_INDEX|Nifty 50",
        "NSE_EQ|INE585B01010", "NSE_EQ|INE917I01010", "NSE_EQ|INE160A01022", "NSE_EQ|INE814H01029",
        "NSE_EQ|INE102D01028", "NSE_EQ|INE134E01011", "NSE_EQ|INE009A01021", "NSE_EQ|INE237A01036",
        "NSE_EQ|INE361B01024", "NSE_EQ|INE030A01027", "NSE_EQ|INE476A01022", "NSE_EQ|INE691A01018",
        "NSE_EQ|INE028A01039", "NSE_EQ|INE670K01029", "NSE_EQ|INE158A01026", "NSE_EQ|INE123W01016",
        "NSE_EQ|INE192A01025", "NSE_EQ|INE094A01015", "NSE_EQ|INE528G01035", "NSE_EQ|INE849A01020",
        "NSE_EQ|INE669C01036", "NSE_EQ|INE216A01030", "NSE_EQ|INE002S01010", "NSE_EQ|INE062A01020",
        "NSE_EQ|INE081A01020", "NSE_EQ|INE883A01011", "NSE_EQ|INE075A01022", "NSE_EQ|INE027H01010",
        "NSE_EQ|INE121A01024", "NSE_EQ|INE974X01010", "NSE_EQ|INE742F01042", "NSE_EQ|INE047A01021",
        "NSE_EQ|INE213A01029", "NSE_EQ|INE053F01010", "NSE_EQ|INE021A01026", "NSE_EQ|INE733E01010",
        "NSE_EQ|INE565A01014", "NSE_EQ|INE239A01024", "NSE_EQ|INE437A01024", "NSE_EQ|INE399L01023",
        "NSE_EQ|INE019A01038", "NSE_EQ|INE522F01014", "NSE_EQ|INE296A01032", "NSE_EQ|INE066F01020",
        "NSE_EQ|INE002A01018", "NSE_EQ|INE203G01027", "NSE_EQ|INE467B01029", "NSE_EQ|INE040A01034",
        "NSE_EQ|INE066A01021", "NSE_EQ|INE844O01030", "NSE_EQ|INE752E01010", "NSE_EQ|INE271C01023",
        "NSE_EQ|INE318A01026", "NSE_EQ|INE042A01014", "NSE_EQ|INE918I01026", "NSE_EQ|INE758E01017",
        "NSE_EQ|INE089A01031", "NSE_EQ|INE494B01023", "NSE_EQ|INE646L01027", "NSE_EQ|INE397D01024",
        "NSE_EQ|INE775A08105", "NSE_EQ|INE059A01026", "NSE_EQ|INE949L01017", "NSE_EQ|INE280A01028",
        "NSE_EQ|INE298A01020", "NSE_EQ|INE095A01012", "NSE_EQ|INE562A01011", "NSE_EQ|INE364U01010",
        "NSE_EQ|INE238A01034", "NSE_EQ|INE044A01036", "NSE_EQ|INE038A01020", "NSE_EQ|INE242A01010",
        "NSE_EQ|INE692A01016", "NSE_EQ|INE263A01024", "NSE_EQ|INE020B01018", "NSE_EQ|INE860A01027",
        "NSE_EQ|INE457A01014", "NSE_EQ|INE171A01029", "NSE_EQ|INE323A01026", "NSE_EQ|INE176B01034",
        "NSE_EQ|INE545U01014", "NSE_EQ|INE154A01025", "NSE_EQ|INE101A01026", "NSE_EQ|INE208A01029",
        "NSE_EQ|INE303R01014", "NSE_EQ|INE090A01021", "NSE_EQ|INE787D01026", "NSE_EQ|INE018A01030",
        "NSE_EQ|INE092T01019", "NSE_EQ|INE347G01014", "NSE_EQ|INE103A01014", "NSE_EQ|INE067A01029",
        "NSE_EQ|INE423A01024", "NSE_EQ|INE259A01022", "NSE_EQ|INE257A01026", "NSE_EQ|INE699H01024",
        "NSE_EQ|INE129A01019", "NSE_EQ|INE481G01011", "NSE_EQ|INE003A01024", "NSE_EQ|INE029A01011",
        "NSE_EQ|INE200M01039"
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
            
            loop_count = 0
            while True:
                loop_count += 1
                if loop_count % 1000 == 0:
                    logger.info("💓 Ingestor Heartbeat: Loop active, polling Kafka/WS...")

                # 1. Scanner Logic (Non-blocking)
                msg = scanner_consumer.poll(0)
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

                # 2. Dynamic Subscription Sync (Non-blocking)
                sub_msg = subscription_consumer.poll(0)
                if sub_msg:
                    if sub_msg.error():
                        logger.error(f"Kafka Sync Error: {sub_msg.error()}")
                    else:
                        try:
                            sub_data = json.loads(sub_msg.value())
                            method = sub_data.get("method", "sub")
                            keys = sub_data.get("instrumentKeys", [])
                            mode = sub_data.get("mode", "full")
                            
                            if keys:
                                # Limit Management: Upstox V3 has a 200 instrument limit per socket.
                                # If we are adding new keys that push us over 200, we must unsub old ones.
                                MAX_ALLOWED = 200
                                current_active = list(active_subs)
                                potential_total = len(set(current_active + keys))

                                if potential_total > MAX_ALLOWED:
                                    # Identify candidates to unsub (Priority: keep Indices, unsub oldest Options)
                                    # Option tokens usually look like NSE_FO|...
                                    option_tokens = [k for k in current_active if "NSE_FO" in k and k not in keys]
                                    
                                    to_unsub_count = potential_total - MAX_ALLOWED
                                    to_unsub = option_tokens[:to_unsub_count]
                                    
                                    if to_unsub:
                                        logger.info(f"♻️ Limit reached. Unsubscribing {len(to_unsub)} old tokens to make room.")
                                        unsub_payload = json.dumps({
                                            "guid": "auto-unsub", "method": "unsub",
                                            "data": {"mode": mode, "instrumentKeys": to_unsub}
                                        })
                                        await websocket.send(unsub_payload.encode('utf-8'))
                                        for k in to_unsub:
                                            active_subs.discard(k)

                                logger.info(f"⚡ Kafka Sync Request: {method} {len(keys)} tokens")
                                sync_payload = json.dumps({
                                    "guid": "sync-request", "method": method,
                                    "data": {"mode": mode, "instrumentKeys": keys}
                                })
                                await websocket.send(sync_payload.encode('utf-8'))
                                active_subs.update(keys)
                        except Exception as e:
                            logger.error(f"Sync msg error: {e}")

                # 3. Receive Data
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
                                    
                                    # Extract Greeks and IV (scalars don't use HasField in proto3 unless optional)
                                    # Extract Greeks and IV
                                    if mff.iv != 0: 
                                        state['iv'] = mff.iv
                                        updated = True
                                    # OI can be 0, but we still want to capture it if it's the first time or explicitly sent
                                    state['oi'] = int(mff.oi)
                                    updated = True
                                    if mff.vtt != 0: 
                                        state['v'] = mff.vtt
                                        updated = True
                                    
                                    if mff.HasField('optionGreeks'):
                                        og = mff.optionGreeks
                                        state['greeks'] = {
                                            "delta": og.delta, "theta": og.theta, 
                                            "gamma": og.gamma, "vega": og.vega
                                        }
                                        updated = True
                                elif ff_type == 'indexFF':
                                    iff = feed.fullFeed.indexFF
                                    if iff.HasField('ltpc'): ltpc_obj = iff.ltpc

                            elif feed_type == 'firstLevelWithGreeks':
                                flg = feed.firstLevelWithGreeks
                                if flg.HasField('ltpc'): ltpc_obj = flg.ltpc
                                if flg.iv != 0: 
                                    state['iv'] = flg.iv
                                    updated = True
                                state['oi'] = int(flg.oi)
                                updated = True
                                    
                                if flg.vtt > 0: 
                                    state['v'] = flg.vtt
                                    updated = True
                                if flg.HasField('optionGreeks'):
                                    og = flg.optionGreeks
                                    state['greeks'] = {
                                        "delta": og.delta, "theta": og.theta, 
                                        "gamma": og.gamma, "vega": og.vega
                                    }
                                    updated = True

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
                                    
                                    # If Greeks were updated, produce to greeks topic ONLY for derivatives
                                    DERIVATIVE_PREFIXES = ('NSE_FO|', 'BSE_FO|', 'NCD_FO|', 'MCX_FO|')
                                    if 'greeks' in state and any(key.startswith(p) for p in DERIVATIVE_PREFIXES):
                                        greek_tick = {
                                            "symbol": key,
                                            "iv": state.get('iv', 0.0),
                                            "delta": state['greeks']['delta'],
                                            "theta": state['greeks']['theta'],
                                            "gamma": state['greeks']['gamma'],
                                            "vega": state['greeks']['vega'],
                                            "timestamp": tick['timestamp']
                                        }
                                        # Diagnostic log for non-zero greeks to verify broker feed quality
                                        if abs(greek_tick['delta']) > 0 or abs(greek_tick['theta']) > 0 or abs(greek_tick['gamma']) > 0:
                                            logger.info(f"🔥 [GREEK_LIVE] {key}: D={greek_tick['delta']:.3f}, G={greek_tick['gamma']:.5f}, T={greek_tick['theta']:.3f}")

                                        producer.produce('market.option.greeks', key=key, value=json.dumps(greek_tick))
                                        # Clear greeks state after sending to avoid duplicate writes if no change
                                        del state['greeks']
                         
                        producer.poll(0)

                except asyncio.TimeoutError:
                    continue

    except Exception as e:
        logger.error(f"Error: {e}")
        await asyncio.sleep(5)

if __name__ == "__main__":
    asyncio.run(connect_upstox_v3())