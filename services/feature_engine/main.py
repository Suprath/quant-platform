import os
import json
import time
import logging
from confluent_kafka import Consumer, Producer
from confluent_kafka.admin import AdminClient, NewTopic
from dotenv import load_dotenv

load_dotenv()

# Logging Setup
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("QuantFeatureEngine")

KAFKA_SERVER = os.getenv('KAFKA_BOOTSTRAP_SERVERS', 'kafka_bus:9092')

class QuantProcessor:
    """
    State machine for a single stock.
    Calculates: VWAP, OBI, Spread, Aggressor Side, Day High/Low
    """
    def __init__(self, symbol):
        self.symbol = symbol
        self.day_high = -1.0
        self.day_low = float('inf')
        
        # VWAP State
        self.cum_pv = 0.0 # Cumulative (Price * Volume)
        self.cum_v = 0    # Cumulative Volume
        
        # Indicator State
        self.history = [] # List of {'close': float} for RSI
        self.window_size = 50 # Keep enough for RSI-14
        
        self.last_signal = None

    def calculate_rsi(self, prices, period=14):
        if len(prices) < period + 1:
            return 50.0 # Neutral default
        
        import pandas as pd
        series = pd.Series(prices)
        delta = series.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
        
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        return round(rsi.iloc[-1], 2)

    def process(self, tick):
        ltp = tick.get('ltp', 0.0)
        v = tick.get('v', 0)
        depth = tick.get('depth', {})

        # 1. Update Session High/Low
        if ltp > self.day_high: self.day_high = ltp
        if self.day_low == float('inf') or ltp < self.day_low: self.day_low = ltp

        # 2. Update VWAP
        self.cum_pv += (ltp * v)
        self.cum_v += v
        vwap = round(self.cum_pv / self.cum_v, 2) if self.cum_v > 0 else ltp

        # 3. Update History & Calculate RSI
        self.history.append(ltp)
        if len(self.history) > self.window_size:
            self.history.pop(0)
        
        rsi = self.calculate_rsi(self.history)
        sma = sum(self.history) / len(self.history)

        # 4. Microstructure: Spread & OBI
        spread = 0.0
        obi = 0.0
        best_bid = 0.0
        best_ask = 0.0

        if depth:
            bids = depth.get('buy', [])
            asks = depth.get('sell', [])
            total_bid_qty = sum(b['quantity'] for b in bids)
            total_ask_qty = sum(a['quantity'] for a in asks)
            
            if (total_bid_qty + total_ask_qty) > 0:
                obi = round((total_bid_qty - total_ask_qty) / (total_bid_qty + total_ask_qty), 4)

            if bids and asks:
                best_bid = bids[0]['price']
                best_ask = asks[0]['price']
                spread = round(best_ask - best_bid, 2)

        # 5. Microstructure: Aggressor Side
        aggressor = "NEUTRAL"
        if best_ask > 0 and ltp >= best_ask:
            aggressor = "BUY"
        elif best_bid > 0 and ltp <= best_bid:
            aggressor = "SELL"

        return {
            "symbol": self.symbol,
            "ltp": ltp,
            "volume": v,
            "day_high": self.day_high,
            "day_low": self.day_low,
            "vwap": vwap,
            "sma": round(sma, 2),
            "rsi": rsi,
            "spread": spread,
            "obi": obi,
            "aggressor": aggressor,
            "timestamp": tick.get('timestamp', int(time.time()*1000))
        }

def ensure_topics():
    """Auto-create topics if they don't exist"""
    a = AdminClient({'bootstrap.servers': KAFKA_SERVER})
    # Also ensure the raw ticks topic exists so consumers don't error with UNKNOWN_TOPIC
    topics = ["market.equity.ticks", "market.enriched.ticks", "strategy.signals"]
    new_topics = [NewTopic(t, num_partitions=12, replication_factor=1) for t in topics]
    a.create_topics(new_topics)

def run():
    ensure_topics()
    
    # Consumer: Reads Raw Ticks
    c = Consumer({
        'bootstrap.servers': KAFKA_SERVER,
        'group.id': 'feature-engine-microstructure-v1',
        'auto.offset.reset': 'latest'
    })
    c.subscribe(['market.equity.ticks'])

    # Producer: Sends Enriched Data & Signals
    p = Producer({'bootstrap.servers': KAFKA_SERVER})

    # State Registry
    processors = {}

    logger.info("Feature Engine: Calculating Microstructure (Spread, Aggressor, VWAP)...")

    try:
        while True:
            msg = c.poll(0.1)
            if msg is None: continue
            if msg.error():
                logger.error(f"Kafka Error: {msg.error()}")
                continue

            try:
                raw_tick = json.loads(msg.value().decode('utf-8'))
                sym = raw_tick.get('symbol')

                if sym not in processors:
                    processors[sym] = QuantProcessor(sym)

                # --- 1. CALCULATE ---
                enriched_data = processors[sym].process(raw_tick)
                logger.info(
                    f"ENRICHED {sym} | ltp={enriched_data['ltp']} "
                    f"vwap={enriched_data['vwap']} obi={enriched_data['obi']} "
                    f"agg={enriched_data['aggressor']}"
                )

                # --- 2. PUBLISH ENRICHED DATA (For Persistor) ---
                # This goes to the new topic that your DB listens to
                p.produce('market.enriched.ticks', key=sym, value=json.dumps(enriched_data))

                # --- 3. GENERATE SIGNALS (For Strategy) ---
                # Strategy: Momentum Breakout with Microstructure Confirmation
                # Buy if: Price > VWAP AND Buying Pressure (OBI) is high AND Aggressor is Buyer
                signal = None
                
                # Check conditions
                bullish_structure = (
                    enriched_data['ltp'] > enriched_data['vwap'] and 
                    enriched_data['obi'] > 0.2 and 
                    enriched_data['aggressor'] == 'BUY'
                )
                
                bearish_structure = (
                    enriched_data['ltp'] < enriched_data['vwap'] and 
                    enriched_data['obi'] < -0.2 and 
                    enriched_data['aggressor'] == 'SELL'
                )

                if bullish_structure:
                    signal = "BUY"
                elif bearish_structure:
                    signal = "SELL"

                # Debounce logic (simple) could be added here
                if signal:
                    signal_payload = {
                        "symbol": sym,
                        "action": signal,
                        "price": enriched_data['ltp'],
                        "reason": f"Microstructure: OBI={enriched_data['obi']}, Agg={enriched_data['aggressor']}",
                        "timestamp": enriched_data['timestamp'],
                        "strategy_id": "MICRO_BREAKOUT_V1"
                    }
                    p.produce('strategy.signals', key=sym, value=json.dumps(signal_payload))
                    logger.info(f"🚨 SIGNAL: {signal} {sym} | OBI: {enriched_data['obi']} | Agg: {enriched_data['aggressor']}")

                p.poll(0)

            except Exception as e:
                logger.error(f"Processing Error: {e}")

    except KeyboardInterrupt:
        pass
    finally:
        c.close()

if __name__ == "__main__":
    run()