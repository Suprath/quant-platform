import os
import logging
import uuid
import subprocess
import threading
import uvicorn
from fastapi import FastAPI, BackgroundTasks, HTTPException
from pydantic import BaseModel
from engine import AlgorithmEngine

# Config
BACKTEST_MODE = os.getenv('BACKTEST_MODE', 'false').lower() == 'true'
RUN_ID = os.getenv('RUN_ID', 'live_run')
# Default to Demo Strategy if not specified
STRATEGY_NAME = os.getenv('STRATEGY_NAME', 'strategies.demo_algo.DemoStrategy')

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("StrategyRuntimeService")

app = FastAPI()

class BacktestRequest(BaseModel):
    strategy_code: str
    symbol: str
    start_date: str
    end_date: str
    initial_cash: float
    strategy_name: str = "CustomStrategy"

def run_live_strategy():
    """Runs the strategy in LIVE mode."""
    logger.info(f"🚀 Starting LIVE Algorithm Engine for {STRATEGY_NAME}")
    try:
        engine = AlgorithmEngine(run_id=RUN_ID, backtest_mode=False)
        # Parse strategy name
        try:
             module_path, class_name = STRATEGY_NAME.rsplit('.', 1)
             engine.LoadAlgorithm(module_path, class_name)
        except Exception as e:
             logger.error(f"Failed to load live strategy: {e}")
             return

        engine.Initialize()
        engine.Run()
    except Exception as e:
        logger.error(f"Live Strategy Error: {e}")

@app.on_event("startup")
def startup_event():
    # Only start live loop if NOT explicitly in backtest mode
    # In docker-compose, strategy_runtime is defined for live trading.
    if not BACKTEST_MODE:
        threading.Thread(target=run_live_strategy, daemon=True).start()

# Global Process Store
active_processes = {} # run_id -> subprocess.Popen

def run_backtest_process(run_id: str, request: BacktestRequest, strategy_file_path: str):
    logger.info(f"🛑 Starting Backtest Job: {run_id}")
    
    # We will invoke backtest_runner.py as a subprocess
    # We need to construct the module path for the strategy file
    # file is at strategies/backtest_{run_id}.py
    # Module name: strategies.backtest_{run_id}
    # Class name: We need to parse it or assume it. 
    # Let's simple regex for "class X(QCAlgorithm)"
    
    import re
    class_name = "UserStrategy" # Default
    try:
        with open(strategy_file_path, 'r') as f:
            content = f.read()
            match = re.search(r'class\s+(\w+)\s*\(\s*QCAlgorithm\s*\)', content)
            if match:
                class_name = match.group(1)
    except:
        pass
        
    strategy_module_name = f"strategies.backtest_{run_id}.{class_name}"
    
    env = os.environ.copy()
    env['RUN_ID'] = run_id
    env['STRATEGY_NAME'] = strategy_module_name
    env['BACKTEST_MODE'] = 'true'
    
    cmd = [
        "python3", "backtest_runner.py",
        "--symbol", request.symbol,
        "--start", request.start_date,
        "--end", request.end_date,
        "--cash", str(request.initial_cash)
    ]
    
    try:
        log_file = f"logs/{run_id}.log"
        os.makedirs("logs", exist_ok=True)
        
        with open(log_file, "w") as outfile:
            # Use Popen instead of run to keep control
            process = subprocess.Popen(
                cmd, 
                env=env, 
                stdout=outfile, 
                stderr=subprocess.STDOUT
            )
            
            # Store process
            active_processes[run_id] = process
            
            # Wait for completion
            process.wait()
            
            # Remove from active processes if natural completion
            if run_id in active_processes:
                del active_processes[run_id]
            
        logger.info(f"✅ Backtest Job {run_id} Completed (Code: {process.returncode})")
        
    except Exception as e:
        logger.error(f"Backtest Job Failed: {e}")
        if run_id in active_processes:
            del active_processes[run_id]

@app.post("/backtest")
def start_backtest(request: BacktestRequest, background_tasks: BackgroundTasks):
    run_id = str(uuid.uuid4())
    
    # Save Strategy Code
    # Ensure strategies directory exists
    os.makedirs("strategies", exist_ok=True)
    strategy_filename = f"backtest_{run_id}.py"
    strategy_path = os.path.join("strategies", strategy_filename)
    
    with open(strategy_path, "w") as f:
        f.write(request.strategy_code)

    # Start Backtest in Background
    background_tasks.add_task(run_backtest_process, run_id, request, strategy_path)
    
    return {"run_id": run_id, "status": "started", "log_url": f"/backtest/logs/{run_id}"}

@app.post("/backtest/stop/{run_id}")
def stop_backtest(run_id: str):
    if run_id in active_processes:
        try:
            process = active_processes[run_id]
            process.terminate() # or kill()
            # Give it a moment to terminate gracefully?
            # process.wait(timeout=5)
            # Remove immediately?
            del active_processes[run_id]
            logger.info(f"🛑 Stopped backtest run {run_id} by user request.")
            
            # Append to log
            try:
                with open(f"logs/{run_id}.log", "a") as f:
                    f.write("\n🛑 Backtest Stopped by User.\n")
            except: pass
            
            return {"status": "stopped", "message": f"Backtest {run_id} stopped."}
        except Exception as e:
             logger.error(f"Failed to stop {run_id}: {e}")
             raise HTTPException(status_code=500, detail=str(e))
    else:
        # It might have finished already
        return {"status": "not_found", "message": "Backtest not running or already finished."}

@app.get("/backtest/logs/{run_id}")
def get_logs(run_id: str):
    """Fetch logs for a backtest run"""
    log_file = f"logs/{run_id}.log"
    if os.path.exists(log_file):
        with open(log_file, "r") as f:
            return {"logs": f.read().splitlines()}
    return {"logs": ["Waiting for logs..."]}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
