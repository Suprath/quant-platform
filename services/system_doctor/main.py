import os
import psycopg2
import requests
import json
import time
import socket
from confluent_kafka.admin import AdminClient
from termcolor import colored

# Configuration
POSTGRES_HOST = "postgres_metadata"
QUESTDB_HOST = "questdb_tsdb"
KAFKA_HOST = "kafka_bus:9092"
API_HOST = "http://api_gateway:8000"

def print_status(component, status, message=""):
    if status == "PASS":
        print(f"{colored('[PASS]', 'green')} {component:<20} : {message}")
    else:
        print(f"{colored('[FAIL]', 'red')} {component:<20} : {message}")

def check_postgres():
    try:
        conn = psycopg2.connect(
            host=POSTGRES_HOST, port=5432, user="admin", password="password123", database="quant_platform"
        )
        cur = conn.cursor()
        
        # Check Instruments Table
        cur.execute("SELECT count(*) FROM instruments;")
        inst_count = cur.fetchone()[0]
        
        # Check Trades Table
        cur.execute("SELECT count(*) FROM executed_orders;")
        trade_count = cur.fetchone()[0]
        
        print_status("PostgreSQL", "PASS", f"Connected. Instruments: {inst_count}, Trades: {trade_count}")
        conn.close()
        return True
    except Exception as e:
        print_status("PostgreSQL", "FAIL", str(e))
        return False

def check_questdb():
    try:
        conn = psycopg2.connect(
            host=QUESTDB_HOST, port=8812, user="admin", password="quest", database="qdb"
        )
        cur = conn.cursor()
        
        # Check Ticks
        cur.execute("SELECT count(*) FROM ticks;")
        tick_count = cur.fetchone()[0]
        
        # Check Greeks
        try:
            cur.execute("SELECT count(*) FROM option_greeks;")
            greek_count = cur.fetchone()[0]
        except:
            greek_count = "Table Missing"

        print_status("QuestDB", "PASS", f"Connected. Ticks: {tick_count}, Greeks: {greek_count}")
        conn.close()
        return True
    except Exception as e:
        print_status("QuestDB", "FAIL", str(e))
        return False

def check_kafka():
    try:
        conf = {'bootstrap.servers': KAFKA_HOST, 'socket.timeout.ms': 2000}
        admin = AdminClient(conf)
        metadata = admin.list_topics(timeout=3)
        
        topics = list(metadata.topics.keys())
        required = ['market.equity.ticks', 'market.option.greeks', 'strategy.signals']
        
        missing = [t for t in required if t not in topics]
        
        if missing:
            print_status("Kafka", "FAIL", f"Missing Topics: {missing}")
            return False # <--- FIXED: Now returns False on error
        else:
            print_status("Kafka", "PASS", f"Brokers Online. Topics Verified.")
            return True
    except Exception as e:
        print_status("Kafka", "FAIL", str(e))
        return False

def check_api_gateway():
    try:
        # 1. Health Check
        r = requests.get(f"{API_HOST}/")
        if r.status_code == 200:
            # 2. Data Check
            r2 = requests.get(f"{API_HOST}/api/v1/trades")
            if r2.status_code == 200:
                print_status("API Gateway", "PASS", "Responding 200 OK")
            else:
                print_status("API Gateway", "FAIL", f"Trade Endpoint Error: {r2.status_code}")
        else:
            print_status("API Gateway", "FAIL", f"Health Check Error: {r.status_code}")
    except Exception as e:
        print_status("API Gateway", "FAIL", "Connection Refused (Is container running?)")

def run_diagnostics():
    print(colored("\n--- 🏥 QUANT PLATFORM SYSTEM DOCTOR ---", "cyan", attrs=['bold']))
    
    pg_ok = check_postgres()
    qdb_ok = check_questdb()
    kafka_ok = check_kafka()
    check_api_gateway()
    
    print(colored("-" * 40, "cyan"))
    
    if pg_ok and qdb_ok and kafka_ok:
        print(colored("✅ SYSTEM STATUS: HEALTHY", "green", attrs=['bold']))
        print("Ready for Market Open.")
    else:
        print(colored("❌ SYSTEM STATUS: DEGRADED", "red", attrs=['bold']))
        print("Check logs of failing components.")
    print("\n")

if __name__ == "__main__":
    # Small delay to ensure networking is resolved if running via compose run
    time.sleep(1)
    run_diagnostics()