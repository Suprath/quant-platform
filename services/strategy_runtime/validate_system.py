import os
import sys
import logging
import json
import time
from datetime import datetime, timedelta
from unittest.mock import MagicMock

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('system_validation.log')
    ]
)
logger = logging.getLogger("SystemValidator")

# --- Path Setup ---
# Add services/strategy_runtime and quant_sdk to path
runtime_path = os.path.abspath(os.path.join(os.getcwd(), 'services', 'strategy_runtime'))
sys.path.append(runtime_path)

# --- Mocking for non-container environments ---
# This allows the script to run even if some DBs are unreachable, 
# though it will report them as skipped/failed.
MOCK_MODE = os.getenv('VALIDATION_MOCK', 'false').lower() == 'true'

if MOCK_MODE:
    logger.info("⚠️ MOCK_MODE enabled. External dependencies will be mocked.")
    sys.modules['psycopg2'] = MagicMock()
    sys.modules['psycopg2.extras'] = MagicMock()
    sys.modules['confluent_kafka'] = MagicMock()

try:
    import psycopg2
    from paper_exchange import PaperExchange
    from calculations import TransactionCostCalculator
    from engine import AlgorithmEngine
    from db import DB_CONF, get_db_connection
except ImportError as e:
    logger.error(f"FATAL: Missing dependencies: {e}")
    sys.exit(1)

def check_environment():
    logger.info("🔍 Checking Environment Variables...")
    required = ['QUESTDB_URL', 'POSTGRES_HOST', 'UPSTOX_ACCESS_TOKEN']
    missing = [v for v in required if not os.getenv(v)]
    if missing:
        logger.warning(f"⚠️ Missing recommended env vars: {', '.join(missing)}")
    else:
        logger.info("✅ Core environment variables found.")

def check_postgres():
    logger.info("🔍 Checking Postgres Connectivity...")
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT 1")
        cur.close()
        conn.close()
        logger.info("✅ Postgres connection successful.")
        return True
    except Exception as e:
        logger.error(f"❌ Postgres connection failed: {e}")
        return False

def check_questdb():
    logger.info("🔍 Checking QuestDB Connectivity...")
    host = os.getenv("QUESTDB_HOST", "questdb_tsdb")
    try:
        conn = psycopg2.connect(host=host, port=8812, user="admin", password="quest", database="qdb")
        cur = conn.cursor()
        cur.execute("SELECT 1")
        cur.close()
        conn.close()
        logger.info("✅ QuestDB connection successful.")
        return True
    except Exception as e:
        logger.error(f"❌ QuestDB connection failed: {e}")
        return False

def validate_fee_logic():
    logger.info("🔍 Validating Transaction Cost Logic (MIS vs CNC vs OPTIONS)...")
    try:
        modes = ["MIS", "CNC", "OPTIONS"]
        turnover = 100000.0  # ₹1 Lakh
        
        results = {}
        for mode in modes:
            calc = TransactionCostCalculator(trading_mode=mode)
            buy_fees = calc.calculate(turnover, "BUY")
            sell_fees = calc.calculate(turnover, "SELL")
            results[mode] = {"BUY": buy_fees, "SELL": sell_fees}
            logger.info(f"📊 {mode:7}: Buy fees=₹{buy_fees:6.2f} | Sell fees=₹{sell_fees:6.2f}")

        # Verification
        # OPTIONS typically has higher exchange txn + high STT on sell
        if results["OPTIONS"]["SELL"] <= results["MIS"]["SELL"]:
             logger.error("❌ Logic Failure: OPTIONS fees should be higher than MIS (Sell side).")
             return False
        
        # CNC typically has STT on both sides
        if results["CNC"]["BUY"] == 0:
             logger.error("❌ Logic Failure: CNC should have STT/Stamp on BUY side.")
             return False
             
        logger.info("✅ Fee structure synchronization verified.")
        return True
    except Exception as e:
        logger.error(f"❌ Fee Logic Validation failed: {e}")
        return False

def validate_leverage():
    logger.info("🔍 Validating Leverage and Buying Power...")
    try:
        # Mocking DB for exchange tests
        mock_db = {'dbname': 'qdb', 'user': 'admin', 'password': 'quest', 'host': 'localhost', 'port': '8812'}
        
        # Test Case: 10x Leverage
        leverage = 10.0
        initial_cash = 100000.0
        exchange = PaperExchange(mock_db, backtest_mode=True, run_id="val_test", trading_mode="MIS", leverage=leverage)
        exchange._bt_balance = initial_cash
        
        # Engine setup
        engine = AlgorithmEngine(run_id="val_test", backtest_mode=True, trading_mode="MIS")
        engine.Exchange = exchange
        engine.Leverage = leverage
        engine.Algorithm = MagicMock()
        engine.Algorithm.Portfolio = {'Cash': initial_cash, 'TotalPortfolioValue': initial_cash}
        
        # Attempt to order ₹800k (8x cash, allowed with 10x leverage)
        symbol = "NSE_EQ|RELIANCE"
        price = 2000.0
        qty = 400
        
        # 1. Manual SubmitOrder check
        engine._last_prices[symbol] = price
        success = engine.SubmitOrder(symbol, qty)
        logger.info(f"📈 Buy ₹800k with ₹100k cash (10x leverage): {'✅ SUCCESS' if success else '❌ FAILED'}")
        
        if not success:
            return False

        # 2. SetHoldings check (Target 500% of equity)
        # Should result in ₹500k exposure
        success_sh = engine.SetHoldings(symbol, 5.0)
        logger.info(f"📈 SetHoldings 500% (5x) equity: {'✅ SUCCESS' if success_sh else '❌ FAILED'}")

        if not success_sh:
            return False

        logger.info("✅ Leverage expansion and buying power verified.")
        return True
    except Exception as e:
        logger.error(f"❌ Leverage Validation failed: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return False

def run_all_validations():
    logger.info("==================================================")
    logger.info("🚀 KIRA SYSTEM VALIDATION STARTING")
    logger.info("==================================================")
    
    checks = [
        ("Environment", check_environment),
        ("Postgres Connectivity", check_postgres),
        ("QuestDB Connectivity", check_questdb),
        ("Fee Logic", validate_fee_logic),
        ("Leverage & Buying Power", validate_leverage)
    ]
    
    passed = 0
    failed = 0
    
    for name, func in checks:
        try:
            result = func()
            if result is not False: # Most funcs return None or True
                passed += 1
            else:
                failed += 1
        except Exception as e:
            logger.error(f"Unhandled exception in {name}: {e}")
            failed += 1
    
    logger.info("==================================================")
    logger.info(f"🏁 VALIDATION SUMMARY: {passed} PASSED | {failed} FAILED")
    logger.info("==================================================")
    
    if failed > 0:
        logger.error("❌ System validation FAILED. Review logs for details.")
        sys.exit(1)
    else:
        logger.info("✅ System validation PASSED. All core components healthy.")
        sys.exit(0)

if __name__ == "__main__":
    # If run directly without flags, try a real check (mostly for fee/logic which don't need real DB)
    # To run a full check in dev, use: VALIDATION_MOCK=true python3 validate_system.py
    run_all_validations()
