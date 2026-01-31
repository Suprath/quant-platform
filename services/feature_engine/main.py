import os
import json
import pandas as pd
from confluent_kafka import Consumer, Producer
from dotenv import load_dotenv

load_dotenv()

# Kafka Config
bootstrap = os.getenv('KAFKA_BOOTSTRAP_SERVERS', 'kafka_bus:9092')
consumer = Consumer({'bootstrap.servers': bootstrap, 'group.id': 'feature-group', 'auto.offset.reset': 'earliest'})
producer = Producer({'bootstrap.servers': bootstrap})

class TradingLogic:
    def __init__(self):
        self.history = []
        self.last_signal = None

    def check_for_signal(self, symbol, ltp):
        self.history.append(ltp)
        if len(self.history) > 10: self.history.pop(0)
        
        if len(self.history) < 10: return None
        
        sma = sum(self.history) / 10
        
        # Logic: If price drops below SMA, it's a SELL signal
        if ltp < sma and self.last_signal != "SELL":
            self.last_signal = "SELL"
            return {"symbol": symbol, "action": "SELL", "price": ltp, "reason": "Price below SMA"}
        elif ltp > sma and self.last_signal != "BUY":
            self.last_signal = "BUY"
            return {"symbol": symbol, "action": "BUY", "price": ltp, "reason": "Price above SMA"}
        return None

def run():
    consumer.subscribe(['market.equity.ticks'])
    logic = TradingLogic()
    print("Feature Engine analyzing for signals...")

    while True:
        msg = consumer.poll(1.0)
        if msg is None: continue
        
        data = json.loads(msg.value().decode('utf-8'))
        signal = logic.check_for_signal(data['symbol'], data['ltp'])
        
        if signal:
            print(f"🚨 SIGNAL GENERATED: {signal['action']} {signal['symbol']}")
            producer.produce('strategy.signals', value=json.dumps(signal))
            producer.flush()

if __name__ == "__main__":
    run()