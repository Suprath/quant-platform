import os
import json
import time
from confluent_kafka import Consumer, Producer
from dotenv import load_dotenv

load_dotenv()

KAFKA_SERVER = os.getenv('KAFKA_BOOTSTRAP_SERVERS', 'kafka_bus:9092')

class SMAStrategy:
    def __init__(self, window=10):
        self.prices = []
        self.window = window
        self.last_signal = None

    def update(self, price):
        self.prices.append(price)
        if len(self.prices) > self.window:
            self.prices.pop(0)
        
        if len(self.prices) < self.window:
            return None, None

        sma = sum(self.prices) / self.window
        
        # Crossover Logic
        signal = None
        if price < (sma - 0.10) and self.last_signal != "SELL":
            signal = "SELL"
        elif price > (sma + 0.10) and self.last_signal != "BUY":
            signal = "BUY"
        
        if signal:
            self.last_signal = signal
        return signal, sma

def run():
    # Producer for Signals
    p = Producer({'bootstrap.servers': KAFKA_SERVER})
    
    # Consumer for Ticks
    c = Consumer({
        'bootstrap.servers': KAFKA_SERVER,
        'group.id': 'feature-engine-v2',
        'auto.offset.reset': 'earliest'
    })
    c.subscribe(['market.equity.ticks'])

    strategy = SMAStrategy()
    print("Feature Engine: Waiting for Kafka...")

    try:
        while True:
            msg = c.poll(1.0)
            if msg is None: continue
            
            try:
                data = json.loads(msg.value().decode('utf-8'))
                symbol = data['symbol']
                price = data['ltp']

                signal, sma = strategy.update(price)

                if signal:
                    payload = {
                        "symbol": symbol,
                        "action": signal,
                        "price": price,
                        "strategy_id": "SMA_CROSSOVER_01",
                        "timestamp": int(time.time() * 1000)
                    }
                    p.produce('strategy.signals', value=json.dumps(payload))
                    p.flush()
                    print(f"🚨 SIGNAL: {signal} for {symbol} at {price} (SMA: {round(sma, 2)})")
                else:
                    if sma:
                        print(f"Monitoring {symbol}: {price} | SMA: {round(sma, 2)}")

            except Exception as e:
                print(f"Processing Error: {e}")
    finally:
        c.close()

if __name__ == "__main__":
    run()