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
    trading_mode: str = "MIS" # MIS or CNC

class LiveStartRequest(BaseModel):
    strategy_name: str
    capital: float
    trading_mode: str = "MIS"  # MIS (intraday) or CNC (delivery)

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

    mode = request.trading_mode.upper()
    if mode not in ("MIS", "CNC"):
        mode = "MIS"
    engine = AlgorithmEngine(backtest_mode=False, trading_mode=mode)
    ACTIVE_STRATEGY_NAME = request.strategy_name
    
    threading.Thread(target=run_live_thread, args=(engine, request.strategy_name, request.capital), daemon=True).start()
    
    return {"status": "started", "message": f"Started {request.strategy_name} ({mode}) with ₹{request.capital}"}

@app.post("/live/stop")
def stop_live():
    global ACTIVE_ENGINE
    if ACTIVE_ENGINE:
        run_id = getattr(ACTIVE_ENGINE, 'RunID', None)
        ACTIVE_ENGINE.Stop()

        # Compute and save stats for the live session (same pipeline as backtest)
        if run_id:
            try:
                _compute_and_save_stats(run_id)
                logger.info(f"✅ Live session stats saved for {run_id}")
            except Exception as e:
                logger.error(f"Failed to save live stats: {e}")

        return {"status": "stopped", "message": "Strategy stopped. Stats saved."}
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

@app.get("/strategies/ide-projects")
def get_all_ide_projects():
    """Bulk fetch all strategy projects and their files for the React IDE."""
    projects = []
    
    # 1. Look for folders (Packages)
    for d in glob.glob("strategies/*/"):
        pkg_name = os.path.basename(os.path.normpath(d))
        if pkg_name.startswith("backtest_") or pkg_name.startswith("__") or pkg_name == "venv":
            continue
            
        files = []
        for py_file in sorted(glob.glob(os.path.join(d, "*.py"))):
            filename = os.path.basename(py_file)
            id_clean = filename.replace('.py', '').replace('.', '_')
            file_id = f"f_{pkg_name}_{id_clean}"
            try:
                with open(py_file, 'r') as f:
                    content = f.read()
                files.append({
                    "id": file_id,
                    "name": filename,
                    "content": content
                })
            except Exception as e:
                print(f"Error reading {py_file}: {e}")
            
        if files:
            projects.append({
                "id": f"proj_{pkg_name}",
                "name": pkg_name,
                "expanded": False,
                "files": files
            })

    # 2. Look for standalone files
    for f_path in glob.glob("strategies/*.py"):
        filename = os.path.basename(f_path)
        if filename.startswith("backtest_") or filename.startswith("__") or filename == "engine.py":
            continue
            
        pkg_name = filename.replace(".py", "")
        # Check if we already have a folder with the same name (folder takes precedence)
        if any(p["name"] == pkg_name for p in projects):
            continue
            
        try:
            with open(f_path, 'r') as f:
                content = f.read()
            projects.append({
                "id": f"proj_{pkg_name}",
                "name": pkg_name,
                "expanded": False,
                "files": [{
                    "id": f"f_{pkg_name}_main",
                    "name": filename,
                    "content": content
                }]
            })
        except Exception as e:
            print(f"Error reading {f_path}: {e}")
            
    return {"projects": sorted(projects, key=lambda x: x["name"])}

@app.get("/live/status")
def get_live_status():
    global ACTIVE_ENGINE, ACTIVE_STRATEGY_NAME
    if ACTIVE_ENGINE and ACTIVE_ENGINE.IsRunning:
        return {
            "strategy": ACTIVE_STRATEGY_NAME,
            **ACTIVE_ENGINE.GetLiveStatus()
        }
    return {"status": "stopped"}

@app.get("/live/trades")
def get_live_trades():
    """Get today's executed trades for the live session."""
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            SELECT id, timestamp, symbol, transaction_type, quantity, price, pnl, status
            FROM executed_orders 
            WHERE timestamp::date = CURRENT_DATE
            ORDER BY timestamp DESC
            LIMIT 100
        """)
        rows = cur.fetchall()
        trades = []
        for r in rows:
            trades.append({
                "id": r[0],
                "timestamp": str(r[1]),
                "symbol": r[2],
                "side": r[3],
                "quantity": r[4],
                "price": float(r[5]),
                "pnl": float(r[6]) if r[6] else 0,
                "status": r[7]
            })
        conn.close()
        return {"trades": trades, "count": len(trades)}
    except Exception as e:
        logger.error(f"Failed to fetch live trades: {e}")
        return {"trades": [], "count": 0, "error": str(e)}

@app.get("/live/statistics")
def get_live_statistics():
    """Get calculated strategy statistics for the live session."""
    global ACTIVE_ENGINE
    if ACTIVE_ENGINE and ACTIVE_ENGINE.IsRunning:
        try:
            stats = ACTIVE_ENGINE.CalculateStatistics()
            return {"statistics": stats}
        except Exception as e:
            logger.error(f"Failed to calculate live stats: {e}")
            return {"statistics": {}, "error": str(e)}
    return {"statistics": {}, "message": "No live strategy running."}

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
    env['TRADING_MODE'] = request.trading_mode
    
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
        
        # Notify the log file so the frontend knows to stop polling
        from datetime import datetime
        ts = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
        with open(log_file, "a") as outfile:
            if process.returncode != 0:
                # ── Extract full error details from the log ──
                full_error_block = ""
                try:
                    import re as _re
                    with open(log_file, "r") as readfile:
                        lines = readfile.readlines()

                    # Patterns
                    py_err_re   = _re.compile(r'^(ERROR|CRITICAL):[\w.]+:')
                    log_line_re = _re.compile(r'^\d{4}-\d{2}-\d{2}|^(DEBUG|INFO|WARNING|ERROR|CRITICAL):[\w.]+:')
                    ts_err_re   = _re.compile(r'^\d{4}-\d{2}-\d{2}.* - ERROR -')

                    error_chunks = []
                    i = 0
                    while i < len(lines):
                        stripped = lines[i].rstrip()

                        # ── Raw uncaught Python exception ──
                        if stripped == 'Traceback (most recent call last):':
                            tb_lines = [stripped]
                            i += 1
                            while i < len(lines):
                                l = lines[i].rstrip()
                                if l and bool(log_line_re.match(l)):
                                    break
                                tb_lines.append(l)
                                i += 1
                            error_chunks.append('\n'.join(tb_lines))
                            continue

                        # ── Python logger ERROR line ──
                        elif bool(py_err_re.match(stripped)):
                            msg = stripped.split(':', 2)[-1].strip() if stripped.count(':') >= 2 else stripped
                            chunk_lines = [msg]
                            i += 1
                            while i < len(lines):
                                l = lines[i].rstrip()
                                if l and bool(log_line_re.match(l)):
                                    break
                                if l:
                                    chunk_lines.append(l)
                                i += 1
                            error_chunks.append('\n'.join(chunk_lines))
                            continue

                        # ── Timestamped sentinel ERROR line ──
                        elif bool(ts_err_re.match(stripped)):
                            msg = stripped.split(' - ERROR - ', 1)[-1].strip()
                            if not msg.startswith('Backtest Stopped') and not msg.startswith('STRATEGY_ERROR:'):
                                error_chunks.append(msg)

                        i += 1

                    if error_chunks:
                        best = max(error_chunks, key=len)
                        full_error_block = best.strip()

                except Exception as _scan_err:
                    full_error_block = f"Process exited with code {process.returncode}"

                if not full_error_block:
                    full_error_block = f"Process exited with code {process.returncode}"

                # Write as a single parseable line (escape newlines → literal \n for JS parser)
                compact = full_error_block.replace('\n', '\\n')
                outfile.write(f"\n{ts} - ERROR - STRATEGY_ERROR: {compact}\n")
                # Also write the human-readable stopped message
                outfile.write(f"{ts} - ERROR - Backtest Stopped (Error code: {process.returncode})\n")
            else:
                outfile.write(f"\n{ts} - INFO - Backtest Runner Finished.\n")

        # ── Always compute stats from DB after process ends ──
        # The subprocess may have already called SaveStatistics, but we
        # compute them again to be safe (upsert handles duplicates).
        try:
            _compute_and_save_stats(run_id)
        except Exception as e:
            logger.error(f"Stats computation after backtest failed: {e}")
        
    except Exception as e:
        logger.error(f"Backtest Job Failed: {e}")
        if run_id in active_processes:
            del active_processes[run_id]
        
        try:
            from datetime import datetime
            with open(log_file, "a") as outfile:
                outfile.write(f"\n{datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} - ERROR - Backtest Stopped. Exception: {e}\n")
        except:
            pass


def _compute_and_save_stats(run_id: str):
    """
    Compute and persist all financial statistics by reading trade data
    directly from the database. Works regardless of how the backtest ended.
    """
    import calculations, timesync
    from datetime import datetime, timedelta

    conn = get_db_connection()
    conn.autocommit = False

    try:
        cur = conn.cursor()

        # ── Step 1: Get initial capital ──────────────────────────────────────
        # IMPORTANT: if the table doesn't exist, rollback so the connection
        # stays clean for the next query.
        initial_cap = 100000.0
        try:
            cur.execute("SELECT initial_cash FROM backtest_runs WHERE run_id = %s", (run_id,))
            row = cur.fetchone()
            if row and row[0]:
                initial_cap = float(row[0])
        except Exception:
            conn.rollback()   # ← CRITICAL: reset the aborted transaction

        # ── Step 2: Fetch all trades ─────────────────────────────────────────
        cur.execute(
            "SELECT timestamp, pnl FROM backtest_orders WHERE run_id=%s ORDER BY timestamp ASC",
            (run_id,),
        )
        rows = cur.fetchall()

        if not rows:
            logger.warning(f"⚠️ No trades found for {run_id}, cannot compute stats.")
            return

        def _to_dt(val) -> datetime:
            """Normalize any timestamp type to a naive datetime."""
            if isinstance(val, datetime):
                return val.replace(tzinfo=None) if val.tzinfo else val
            if isinstance(val, (int, float)):
                return datetime.utcfromtimestamp(val / 1000.0)
            try:
                return datetime.fromisoformat(str(val))
            except Exception:
                return datetime.utcnow()

        # ── Step 3: Build equity curve ────────────────────────────────────────
        equity_curve = []
        pnl_list     = []
        current_eq   = initial_cap
        first_ts     = _to_dt(rows[0][0])
        last_ts      = _to_dt(rows[-1][0])

        equity_curve.append({'timestamp': first_ts - timedelta(seconds=1), 'equity': initial_cap})
        for raw_ts, pnl_val in rows:
            ts        = _to_dt(raw_ts)
            trade_pnl = float(pnl_val) if pnl_val is not None else 0.0
            current_eq += trade_pnl
            equity_curve.append({'timestamp': ts, 'equity': current_eq})
            if pnl_val is not None and trade_pnl != 0.0:
                pnl_list.append(trade_pnl)

        # ── Step 4: Compute trading days ──────────────────────────────────────
        try:
            trading_days = max(timesync.trading_days_between(first_ts.date(), last_ts.date()), 1)
        except Exception:
            calendar_days = max((last_ts - first_ts).days, 1)
            trading_days  = max(int(calendar_days * 5 / 7), 1)

        logger.info(f"📈 Stats for {run_id}: {len(equity_curve)} equity pts, "
                    f"{len(pnl_list)} PnL entries, {trading_days} trading days "
                    f"({first_ts.date()} → {last_ts.date()})")

        # ── Step 5: Compute all metrics ───────────────────────────────────────
        stats = calculations.compute_all_statistics(
            equity_curve=equity_curve,
            pnl_list=pnl_list,
            initial_capital=initial_cap,
            trading_days=trading_days,
        )
        logger.info(f"📊 Results: Sharpe={stats.get('sharpe_ratio')}, "
                    f"CAGR={stats.get('cagr')}%, MaxDD={stats.get('max_drawdown')}%, "
                    f"WinRate={stats.get('win_rate')}, PF={stats.get('profit_factor')}")

        # ── Step 6: Ensure table exists — use a SEPARATE connection for DDL ────
        # (cannot toggle autocommit inside an open transaction)
        ddl_conn = get_db_connection()
        ddl_conn.autocommit = True
        ddl_cur = ddl_conn.cursor()
        ddl_cur.execute("""
            CREATE TABLE IF NOT EXISTS backtest_results (
                run_id UUID PRIMARY KEY,
                sharpe_ratio FLOAT,
                max_drawdown FLOAT,
                win_rate FLOAT,
                total_return FLOAT,
                stats_json JSONB,
                created_at TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        ddl_conn.close()

        # ── Step 7: Upsert computed stats ─────────────────────────────────────
        # Convert numpy floats → native Python floats before psycopg2 binding
        def _sanitize(v):
            try:
                import numpy as np
                if isinstance(v, (np.floating, np.integer)):
                    return float(v)
                if isinstance(v, np.ndarray):
                    return v.tolist()
            except ImportError:
                pass
            return v

        stats_clean = {k: _sanitize(v) for k, v in stats.items()}

        cur.execute("""
            INSERT INTO backtest_results (run_id, sharpe_ratio, max_drawdown, win_rate, total_return, stats_json)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (run_id) DO UPDATE SET
                sharpe_ratio = EXCLUDED.sharpe_ratio,
                max_drawdown = EXCLUDED.max_drawdown,
                win_rate     = EXCLUDED.win_rate,
                total_return = EXCLUDED.total_return,
                stats_json   = EXCLUDED.stats_json
        """, (
            run_id,
            float(stats_clean['sharpe_ratio']),
            float(stats_clean['max_drawdown']),
            float(stats_clean['win_rate']),
            float(stats_clean['total_return']),
            json.dumps(stats_clean)
        ))
        conn.commit()
        logger.info(f"✅ Stats saved for {run_id}: Sharpe={stats_clean['sharpe_ratio']}, "
                    f"CAGR={stats_clean['cagr']}%, MaxDD={stats_clean['max_drawdown']}%")

    except Exception as e:
        logger.error(f"❌ _compute_and_save_stats failed: {e}", exc_info=True)
        try: conn.rollback()
        except Exception: pass
    finally:
        try: conn.close()
        except Exception: pass

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
            process.terminate()
            try:
                process.wait(timeout=3)
            except:
                process.kill()
            del active_processes[run_id]
            logger.info(f"🛑 Stopped backtest run {run_id} by user request.")
            
            # Append to log
            try:
                with open(f"logs/{run_id}.log", "a") as f:
                    f.write("\n🛑 Backtest Stopped by User.\n")
            except: pass
            
            # ── Compute and save stats from DB trade data ──
            try:
                _compute_and_save_stats(run_id)
            except Exception as e:
                logger.error(f"Failed to compute stats on stop: {e}")
            
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

@app.get("/backtest/status/{run_id}")
def get_backtest_status(run_id: str):
    """Robustly check the status of a backtest run"""
    if run_id in active_processes:
        return {"run_id": run_id, "status": "running"}
    
    log_file = f"logs/{run_id}.log"
    if os.path.exists(log_file):
        try:
            with open(log_file, "r") as f:
                content = f.read()
                if "STRATEGY_ERROR:" in content:
                    return {"run_id": run_id, "status": "failed"}
                if "Backtest Runner Finished" in content or "✅ Backtest Complete" in content:
                    return {"run_id": run_id, "status": "completed"}
                if "Backtest Stopped" in content:
                    return {"run_id": run_id, "status": "stopped"}
        except:
            pass
        return {"run_id": run_id, "status": "finished"} # Default for existing logs

    return {"run_id": run_id, "status": "not_found"}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
