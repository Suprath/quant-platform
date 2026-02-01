import os
import json
import time
import logging
from confluent_kafka import Consumer, Producer
from dotenv import load_dotenv

load_dotenv()

# Logging setup
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("FeatureEngine")

KAFKA_SERVER = os.getenv('KAFKA_BOOTSTRAP_SERVERS', 'kafka_bus:9092')

class SymbolState:
    """Maintains quant state for a single instrument"""
    def __init__(self, window_size=20):
        self.window_size = window_size
        self.prices = []
        
        # VWAP State
        self.cum_pv = 0.0 # Cumulative (Price * Volume)
        self.cum_v = 0.0  # Cumulative Volume
        
        # Signal State
        self.last_signal = None

    def update(self, ltp, volume, depth=None):
        # 1. Update SMA Price Window
        self.prices.append(ltp)
        if len(self.prices) > self.window_size:
            self.prices.pop(0)
        
        # 2. Update VWAP (Daily anchored)
        self.cum_pv += (ltp * volume)
        self.cum_v += volume
        vwap = round(self.cum_pv / self.cum_v, 2) if self.cum_v > 0 else ltp

        # 3. Calculate OBI (Order Book Imbalance)
        # OBI = (Total Bid Qty - Total Ask Qty) / (Total Bid Qty + Total Ask Qty)
        obi = 0.0
        if depth:
            # Assuming depth format from Upstox: {'buy': [{'quantity': 100}, ...], 'sell': [...]}
            total_bids = sum([b.get('quantity', 0) for b in depth.get('buy', [])])
            total_asks = sum([s.get('quantity', 0) for s in depth.get('sell', [])])
            if (total_bids + total_asks) > 0:
                obi = (total_bids - total_asks) / (total_bids + total_asks)

        # 4. Calculate SMA
        sma = sum(self.prices) / len(self.prices) if self.prices else ltp
        
        return round(sma, 2), vwap, round(obi, 4)

def run():
    # Producer to send enriched signals
    p = Producer({'bootstrap.servers': KAFKA_SERVER})
    
    # Consumer to read raw ticks
    c = Consumer({
        'bootstrap.servers': KAFKA_SERVER,
        'group.id': 'quant-feature-engine-v1',
        'auto.offset.reset': 'latest' # Focus on live data
    })
    c.subscribe(['market.equity.ticks'])

    # Dictionary to hold state for multiple symbols
    registry = {}

    logger.info("Quant Feature Engine Online. Processing Market Microstructure...")

    try:
        while True:
            msg = c.poll(1.0)
            if msg is None: continue
            if msg.error():
                logger.error(f"Kafka Error: {msg.error()}")
                continue

            # Parse incoming V3 tick
            tick = json.loads(msg.value().decode('utf-8'))
            symbol = tick.get('symbol')
            ltp = tick.get('ltp', 0)
            v = tick.get('v', 0) # Volume
            depth = tick.get('depth') # Depth from Upstox 'full' mode

            if symbol not in registry:
                registry[symbol] = SymbolState()

            state = registry[symbol]
            sma, vwap, obi = state.update(ltp, v, depth)

            # --- QUANT STRATEGY LOGIC ---
            # We look for CONFLUENCE: 
            # BUY if: Price is above SMA AND Price is above VWAP AND OBI shows strong buy pressure (> 0.3)
            signal = None
            if ltp > sma and ltp > vwap and obi > 0.3:
                signal = "BUY"
            # SELL if: Price is below SMA AND Price is below VWAP AND OBI shows strong sell pressure (< -0.3)
            elif ltp < sma and ltp < vwap and obi < -0.3:
                signal = "SELL"

            if signal and signal != state.last_signal:
                state.last_signal = signal
                payload = {
                    "symbol": symbol,
                    "action": signal,
                    "price": ltp,
                    "sma": sma,
                    "vwap": vwap,
                    "obi": obi,
                    "strategy_id": "QUANT_CONFLUENCE_V1",
                    "timestamp": int(time.time() * 1000)
                }
                p.produce('strategy.signals', value=json.dumps(payload))
                p.flush()
                logger.info(f"🚨 QUANT SIGNAL: {signal} {symbol} | Price: {ltp} | VWAP: {vwap} | OBI: {obi}")
            else:
                # Periodic log to show engine is thinking
                if int(time.time()) % 10 == 0:
                    logger.info(f"Monitoring {symbol}: Price={ltp}, VWAP={vwap}, OBI={obi}")

    except Exception as e:
        logger.error(f"Runtime Error: {e}")
    finally:
        c.close()

if __name__ == "__main__":
    run()