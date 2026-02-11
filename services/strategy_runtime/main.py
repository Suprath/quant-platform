import os
import logging
from engine import AlgorithmEngine

# Config
BACKTEST_MODE = os.getenv('BACKTEST_MODE', 'false').lower() == 'true'
RUN_ID = os.getenv('RUN_ID', 'test_run')
# Default to Demo Strategy
STRATEGY_NAME = os.getenv('STRATEGY_NAME', 'strategies.demo_algo.DemoStrategy')

def run():
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    logging.info(f"🚀 Starting Algorithm Engine (Mode: {'BACKTEST' if BACKTEST_MODE else 'LIVE'})")
    
    # Initialize Engine
    engine = AlgorithmEngine(run_id=RUN_ID, backtest_mode=BACKTEST_MODE)
    
    # Load Strategy
    # Strategy Name format: "strategies.demo_algo.DemoStrategy"
    try:
        module_path, class_name = STRATEGY_NAME.rsplit('.', 1)
        logging.info(f"Loading {class_name} from {module_path}...")
        engine.LoadAlgorithm(module_path, class_name)
    except Exception as e:
        logging.error(f"Failed to parse STRATEGY_NAME: {STRATEGY_NAME}. Error: {e}")
        return

    # Initialize Logic
    engine.Initialize()
    
    # Run Event Loop
    engine.Run()

if __name__ == "__main__":
    run()
