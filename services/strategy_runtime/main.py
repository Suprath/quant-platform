import os
import logging
import uuid
import subprocess
import threading
import uvicorn
from fastapi import FastAPI, BackgroundTasks, HTTPException
from pydantic import BaseModel
from typing import Optional, Dict
from engine import AlgorithmEngine
from db import get_db_connection
import glob
import shutil
import json

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
    project_files: Optional[Dict[str, str]] = None  # {filename: code} for multi-file projects
    speed: str = "fast"  # fast, medium, slow

class LiveStartRequest(BaseModel):
    strategy_name: str
    capital: float

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
ACTIVE_ENGINE = None # Singleton for Live Trading Engine
ACTIVE_STRATEGY_NAME = None

def run_live_thread(engine, strategy_name, capital):
    global ACTIVE_ENGINE
    ACTIVE_ENGINE = engine
    engine.SetInitialCapital(capital)
    
    # Update DB Capital
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        
        # 1. Get Portfolio ID
        cur.execute("SELECT id FROM portfolios WHERE user_id='default_user'")
        row = cur.fetchone()
        
        if row:
            pid = row[0]
            # 2. Clear old positions for a fresh start
            cur.execute("DELETE FROM positions WHERE portfolio_id=%s", (pid,))
            # 3. Reset Balance and Equity
            cur.execute("UPDATE portfolios SET balance=%s, equity=%s WHERE id=%s", (capital, capital, pid))
        else:
            # Create new
            cur.execute("INSERT INTO portfolios (user_id, balance, equity) VALUES ('default_user', %s, %s)", (capital, capital))
            
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"Failed to set capital: {e}")

    try:
        module_path, class_name = strategy_name.rsplit('.', 1)
        engine.LoadAlgorithm(module_path, class_name)
        engine.Initialize()
        engine.Run()
    except Exception as e:
        logger.error(f"Live Thread Error: {e}")
    finally:
        ACTIVE_ENGINE = None

@app.get("/strategies")
def list_strategies():
    """List available strategy files AND project packages in the strategies directory."""
    import re
    strategies = []
    
    # 1. Scan single files
    files = glob.glob("strategies/*.py")
    for f in files:
        if "backtest_" in f: continue
        if "__init__" in f: continue
        
        with open(f, 'r') as file:
            content = file.read()
            matches = re.findall(r'class\s+(\w+)\s*\(\s*QCAlgorithm\s*\)', content)
            
            base_name = os.path.basename(f).replace(".py", "")
            for cls in matches:
                strategies.append({
                    "name": f"{cls} ({base_name})",
                    "value": f"strategies.{base_name}.{cls}",
                    "file": f,
                    "type": "file"
                })
    
    # 2. Scan project packages (directories with __init__.py)
    for d in glob.glob("strategies/*/"):
        pkg_name = os.path.basename(os.path.normpath(d))
        if pkg_name.startswith("backtest_"): continue
        if pkg_name.startswith("__"): continue
        
        # Scan ALL .py files in the package for QCAlgorithm subclasses
        for py_file in glob.glob(os.path.join(d, "*.py")):
            if "__init__" in py_file: continue
            try:
                with open(py_file, 'r') as file:
                    content = file.read()
                    matches = re.findall(r'class\s+(\w+)\s*\(\s*QCAlgorithm\s*\)', content)
                    
                    module_name = os.path.basename(py_file).replace(".py", "")
                    for cls in matches:
                        strategies.append({
                            "name": f"{cls} ({pkg_name}/{module_name})",
                            "value": f"strategies.{pkg_name}.{module_name}.{cls}",
                            "file": py_file,
                            "type": "project",
                            "project": pkg_name
                        })
            except Exception:
                pass
    
    return {"strategies": strategies}

@app.post("/live/start")
def start_live(request: LiveStartRequest):
    global ACTIVE_ENGINE, ACTIVE_STRATEGY_NAME
    
    if ACTIVE_ENGINE and ACTIVE_ENGINE.IsRunning:
        return {"status": "error", "message": "Live strategy already running. Stop it first."}
        
    engine = AlgorithmEngine(backtest_mode=False)
    ACTIVE_STRATEGY_NAME = request.strategy_name
    
    threading.Thread(target=run_live_thread, args=(engine, request.strategy_name, request.capital), daemon=True).start()
    
    return {"status": "started", "message": f"Started {request.strategy_name} with ₹{request.capital}"}

@app.post("/live/stop")
def stop_live():
    global ACTIVE_ENGINE
    if ACTIVE_ENGINE:
        ACTIVE_ENGINE.Stop()
        return {"status": "stopped", "message": "Stopping signal sent."}
    return {"status": "not_running", "message": "No live strategy running."}

    return {"status": "not_running", "message": "No live strategy running."}

class StrategySaveRequest(BaseModel):
    name: str
    code: str

class ProjectSaveRequest(BaseModel):
    project_name: str
    files: Dict[str, str]  # {filename: code}

@app.post("/strategies/save")
def save_strategy(request: StrategySaveRequest):
    """Save a strategy file to the strategies directory."""
    try:
        filename = request.name
        if not filename.endswith(".py"):
            filename += ".py"
        
        if ".." in filename or "\\" in filename:
             raise HTTPException(status_code=400, detail="Invalid filename")

        # Support saving into project subdirs (e.g. "my_project/utils.py")
        filepath = os.path.join("strategies", filename)
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        
        with open(filepath, "w") as f:
            code = request.code
            if "from quant_sdk.algorithm import QCAlgorithm" not in code and "import QCAlgorithm" not in code:
                code = "from quant_sdk.algorithm import QCAlgorithm\n\n" + code
            f.write(code)
            
        return {"status": "saved", "message": f"Strategy {filename} saved successfully."}
    except Exception as e:
        logger.error(f"Failed to save strategy: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/strategies/save-project")
def save_project(request: ProjectSaveRequest):
    """Save a multi-file strategy project as a Python package."""
    try:
        project_name = request.project_name.strip()
        if ".." in project_name or "/" in project_name or "\\" in project_name:
            raise HTTPException(status_code=400, detail="Invalid project name")
        
        project_dir = os.path.join("strategies", project_name)
        os.makedirs(project_dir, exist_ok=True)
        
        saved_files = []
        has_init = False
        main_class = None
        
        import re
        for filename, code in request.files.items():
            if ".." in filename or "/" in filename or "\\" in filename:
                continue
            if not filename.endswith(".py"):
                filename += ".py"
            
            filepath = os.path.join(project_dir, filename)
            with open(filepath, "w") as f:
                f.write(code)
            saved_files.append(filename)
            
            if filename == "__init__.py":
                has_init = True
            
            # Find the main strategy class
            matches = re.findall(r'class\s+(\w+)\s*\(\s*QCAlgorithm\s*\)', code)
            if matches:
                module_name = filename.replace(".py", "")
                main_class = (module_name, matches[0])
        
        # Auto-generate __init__.py if not provided
        if not has_init and main_class:
            init_path = os.path.join(project_dir, "__init__.py")
            with open(init_path, "w") as f:
                f.write(f"from .{main_class[0]} import {main_class[1]}\n")
            saved_files.append("__init__.py")
        elif not has_init:
            # Empty __init__.py
            init_path = os.path.join(project_dir, "__init__.py")
            with open(init_path, "w") as f:
                f.write("")
            saved_files.append("__init__.py")
        
        strategy_path = f"strategies.{project_name}.{main_class[0]}.{main_class[1]}" if main_class else None
        
        return {
            "status": "saved",
            "project": project_name,
            "files": saved_files,
            "strategy_path": strategy_path,
            "message": f"Project '{project_name}' saved with {len(saved_files)} files."
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to save project: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/strategies/project/{project_name}")
def get_project(project_name: str):
    """Get all files in a strategy project."""
    if ".." in project_name or "/" in project_name:
        raise HTTPException(status_code=400, detail="Invalid project name")
    
    project_dir = os.path.join("strategies", project_name)
    if not os.path.isdir(project_dir):
        raise HTTPException(status_code=404, detail=f"Project '{project_name}' not found")
    
    files = {}
    for py_file in sorted(glob.glob(os.path.join(project_dir, "*.py"))):
        filename = os.path.basename(py_file)
        with open(py_file, 'r') as f:
            files[filename] = f.read()
    
    return {"project": project_name, "files": files}

@app.get("/live/status")
def get_live_status():
    global ACTIVE_ENGINE, ACTIVE_STRATEGY_NAME
    if ACTIVE_ENGINE and ACTIVE_ENGINE.IsRunning:
        return {
            "strategy": ACTIVE_STRATEGY_NAME,
            **ACTIVE_ENGINE.GetLiveStatus()
        }
    return {"status": "stopped"}

def run_backtest_process(run_id: str, request: BacktestRequest, strategy_file_path: str):
    logger.info(f"🛑 Starting Backtest Job: {run_id}")
    
    import re
    class_name = "UserStrategy"
    
    if os.path.isdir(strategy_file_path):
        # Multi-file project mode — scan .py files for QCAlgorithm subclass
        module_name = None
        for py_file in glob.glob(os.path.join(strategy_file_path, "*.py")):
            if "__init__" in py_file: continue
            try:
                with open(py_file, 'r') as f:
                    content = f.read()
                    match = re.search(r'class\s+(\w+)\s*\(\s*QCAlgorithm\s*\)', content)
                    if match:
                        class_name = match.group(1)
                        module_name = os.path.basename(py_file).replace(".py", "")
                        break
            except:
                pass
        
        pkg_name = os.path.basename(strategy_file_path)
        if module_name:
            strategy_module_name = f"strategies.{pkg_name}.{module_name}.{class_name}"
        else:
            strategy_module_name = f"strategies.{pkg_name}.{class_name}"
    else:
        # Single-file mode
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
        "--cash", str(request.initial_cash),
        "--speed", request.speed
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
    os.makedirs("strategies", exist_ok=True)
    
    if request.project_files:
        # Multi-file project mode
        project_dir = os.path.join("strategies", f"backtest_{run_id}")
        os.makedirs(project_dir, exist_ok=True)
        
        import re
        main_class = None
        
        for filename, code in request.project_files.items():
            if not filename.endswith(".py"):
                filename += ".py"
            filepath = os.path.join(project_dir, filename)
            with open(filepath, "w") as f:
                f.write(code)
            
            matches = re.findall(r'class\s+(\w+)\s*\(\s*QCAlgorithm\s*\)', code)
            if matches:
                module_name = filename.replace(".py", "")
                main_class = (module_name, matches[0])
        
        # Auto-generate __init__.py
        if main_class:
            init_path = os.path.join(project_dir, "__init__.py")
            if not os.path.exists(init_path):
                with open(init_path, "w") as f:
                    f.write(f"from .{main_class[0]} import {main_class[1]}\n")
        
        strategy_path = project_dir
    else:
        # Single-file mode (legacy)
        strategy_filename = f"backtest_{run_id}.py"
        strategy_path = os.path.join("strategies", strategy_filename)
        
        with open(strategy_path, "w") as f:
            code = request.strategy_code
            if "from quant_sdk.algorithm import QCAlgorithm" not in code and "import QCAlgorithm" not in code:
                code = "from quant_sdk.algorithm import QCAlgorithm\n\n" + code
            f.write(code)

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
