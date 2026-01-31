import os
import asyncio
import json
from confluent_kafka import Producer
from dotenv import load_dotenv
import upstox_client
from upstox_client.rest import ApiException

load_dotenv()

# Kafka Configuration
conf = {'bootstrap.servers': os.getenv('KAFKA_BOOTSTRAP_SERVERS', 'kafka_bus:9092')}
producer = Producer(conf)

def delivery_report(err, msg):
    if err is not None:
        print(f'Message delivery failed: {err}')

async def stream_market_data():
    print("Initializing Upstox WebSocket Ingestor...")
    
    # In a real scenario, you'd use the Upstox SDK's Feeder class
    # For now, we simulate the loop defined in PDF Page 29
    
    # Topic names from PDF Page 6
    topic = "market.equity.ticks"
    
    while True:
        try:
            # Simulation of data coming from Upstox (Protobuf format decoded to dict)
            # In production, replace this with upstox_client.MarketDataFeeder
            tick_data = {
                "symbol": "NSE_EQ|INE002A01018", # Reliance
                "ltp": 2950.05,
                "v": 100500,
                "cp": 2940.00
            }
            
            # Produce to Kafka
            producer.produce(
                topic, 
                key=tick_data["symbol"], 
                value=json.dumps(tick_data),
                callback=delivery_report
            )
            producer.poll(0)
            
            print(f"Streaming tick: {tick_data['symbol']} @ {tick_data['ltp']}")
            await asyncio.sleep(0.5) # Simulating sub-second ticks
            
        except Exception as e:
            print(f"Stream Error: {e}")
            await asyncio.sleep(5)

if __name__ == "__main__":
    asyncio.run(stream_market_data())