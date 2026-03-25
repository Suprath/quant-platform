import os
import logging
import json
import asyncio
import math
import psycopg2
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel

from .registry import (
    portfolio_engine, mechanism_classifier, noise_filter, 
    position_sizer, scanner
)
from .portfolio_engine.models import TradeApprovalRequest, PortfolioState
from .learning_loop.trade_recorder import TradeRecorder
from kira_shared.logging.setup import setup_logging
from kira_shared.models.market import FeatureVector, MarketContext
from .backtest_logic import BacktestController

setup_logging()
logger = logging.getLogger("KIRA-TIL")

KNOWN_STOCKS = {
    # NSE
    "NSE_EQ|INE002A01018": "RELIANCE",
    "NSE_EQ|INE040A01034": "HDFCBANK",
    "NSE_EQ|INE467B01029": "TCS",
    "NSE_EQ|INE009A01021": "INFY",
    "NSE_EQ|INE090A01021": "ICICIBANK",
    "NSE_EQ|INE062A01020": "SBIN",
    "NSE_EQ|INE154A01025": "ITC",
    "NSE_EQ|INE669E01016": "BAJFINANCE",
    "NSE_EQ|INE030A01027": "HINDUNILVR",
    "NSE_EQ|INE585B01010": "MARUTI",
    "NSE_EQ|INE917I01010": "AXISBANK",
    "NSE_EQ|INE021A01026": "ASIANPAINT",
    "NSE_EQ|INE075A01022": "WIPRO",
    "NSE_EQ|INE238A01034": "KOTAKBANK",
    "NSE_EQ|INE028A01039": "BAJAJFINSV",
    "NSE_EQ|INE397D01024": "BHARTIARTL",
    "NSE_EQ|INE047A01021": "SUNPHARMA",
    "NSE_EQ|INE326A01037": "ULTRACEMCO",
    "NSE_EQ|INE101A01026": "HCLTECH",
    "NSE_EQ|INE155A01022": "TATAMOTORS",
}

SYMBOL_MAP = {}
for k, v in KNOWN_STOCKS.items():
    prefix = k.split("|")[0] if "|" in k else "NSE_EQ"
    SYMBOL_MAP[f"{prefix}|{v}"] = k
    SYMBOL_MAP[f"{prefix}|{v.upper()}"] = k
    SYMBOL_MAP[v] = k
    SYMBOL_MAP[v.upper()] = k
    SYMBOL_MAP[k] = k

def normalize_symbol(sym):
    if not sym: return sym
    return SYMBOL_MAP.get(sym, SYMBOL_MAP.get(sym.upper(), sym))

app = FastAPI(title="KIRA Trading Intelligence Layer")

# Initialize shared resources
trade_recorder = TradeRecorder()
backtest_controller = BacktestController()


class BacktestRequest(BaseModel):
    symbols: List[str] = []
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    timeframe: str = "5m"
    initial_capital: float = 100000.0
    universe_size: Optional[int] = 10
    trading_days: Optional[int] = 60

@app.get("/health")
async def health():
    return {
        "status": "healthy", 
        "service": "kira-til",
        "components": ["portfolio_engine", "mechanism_classifier", "signal_generator", "learning_loop"]
    }

# --- Signal Generator Endpoints ---

@app.post("/scan")
async def run_market_scan(features_batch: Dict[str, FeatureVector]):
    """Runs a full market scan and returns raw signals."""
    try:
        signals = await scanner.scan(features_batch)
        return {"signals_found": len(signals), "signals": [s.to_dict() for s in signals]}
    except Exception as e:
        logger.error(f"Error during scan: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# --- Integrated Pipeline Endpoint ---

@app.post("/process_features")
async def process_market_features(features_batch: Dict[str, FeatureVector], market_context: MarketContext):
    """
    Full TIL Pipeline: 
    1. Scan for signals
    2. Classify mechanisms for found signals
    3. Validate against portfolio risk
    4. Return actionable decisions
    """
    try:
        # 1. Scan
        raw_signals = await scanner.scan(features_batch)
        portfolio_state = await portfolio_engine.get_state()
        
        decisions = []
        for signal in raw_signals:
            # 2. Classify mechanism
            classified = await mechanism_classifier.classify(signal, features_batch[signal.symbol], market_context)
            
            if not classified.has_mechanism:
                decisions.append({"symbol": signal.symbol, "action": "DISCARD", "reason": "No clear mechanism"})
                continue
            
            # 3. Integrate Noise Filter Confidence
            nf_confidence = await noise_filter.get_confidence(signal.symbol)
            # Combine classifier and noise filter confidence
            combined_confidence = (classified.mechanism_confidence * 0.7) + (nf_confidence * 0.3)
            
            # 4. Integrated Position Sizing
            sizing_result = await position_sizer.get_size(
                symbol=signal.symbol,
                entry_price=signal.entry_price_estimate,
                confidence=combined_confidence,
                current_equity=portfolio_state.total_equity,
                timestamp=market_context.timestamp
            )
            
            if not sizing_result.get("approved", False) or sizing_result.get("shares", 0) <= 0:
                decisions.append({
                    "symbol": signal.symbol, 
                    "action": "REJECT_SIZER", 
                    "reason": sizing_result.get("reason", "Zero size allocation"),
                    "nf_confidence": nf_confidence
                })
                continue
                
            # 5. Final Portfolio Risk/Sector check
            approval_req = TradeApprovalRequest(
                symbol=signal.symbol,
                direction=signal.direction,
                qty=sizing_result["shares"],
                entry_price=signal.entry_price_estimate,
                stop_loss=sizing_result["exit_plan"].get("stop_loss"),
                sector=signal.metadata.get("sector", "UNKNOWN")
            )
            portfolio_check = await portfolio_engine.validate_signal(approval_req)
            
            if not portfolio_check.approved:
                decisions.append({
                    "symbol": signal.symbol, 
                    "action": "REJECT_RISK", 
                    "reason": portfolio_check.reason,
                    "thesis": classified.thesis
                })
                continue
                
            decisions.append({
                "symbol": signal.symbol,
                "action": "EXECUTE",
                "thesis": classified.thesis,
                "confidence": combined_confidence,
                "nf_confidence": nf_confidence,
                "qty": sizing_result["shares"],
                "entry_price": signal.entry_price_estimate,
                "stop_loss": sizing_result["exit_plan"].get("stop_loss")
            })
            
        return {"processed": len(features_batch), "decisions_count": len(decisions), "decisions": decisions}
        
    except Exception as e:
        logger.error(f"Error in integrated pipeline: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# --- Portfolio & Performance Endpoints ---

@app.get("/api/v1/til/portfolio")
async def get_portfolio_state():
    """Returns the current integrated portfolio state."""
    try:
        return await portfolio_engine.get_state()
    except Exception as e:
        logger.error(f"Error fetching portfolio state: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/v1/til/performance")
async def get_historical_performance(run_id: Optional[str] = Query(None)):
    conn = None
    try:
        pg_host = os.getenv("POSTGRES_HOST", "postgres_metadata")
        conn = psycopg2.connect(
            host=pg_host, port=5432, user="admin", password="password123", database="quant_platform"
        )
        cur = conn.cursor()
        
        def safe_float(f, default=0.0):
            try:
                val = float(f)
                return val if math.isfinite(val) else default
            except:
                return default

        EMPTY_SUMMARY = {
            "total_pnl_pct": 0.0, "total_pnl": 0.0, 
            "net_profit": 0.0, 
            "max_drawdown_pct": 0.0, "max_drawdown": 0.0, 
            "current_equity": 0.0, 
            "win_rate": 0.0, "win_rate_pct": 0.0,
            "profit_factor": 0.0, 
            "total_trades": 0, "sharpe_ratio": 0.0, "cagr": 0.0, 
            "expectancy": 0.0, "brokerage": 0.0,
            "mechanism_performance": []
        }

        cur.execute("SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'portfolio_snapshots')")
        if not cur.fetchone()[0]:
            cur.close()
            return {"points": [], "summary": EMPTY_SUMMARY}
            
        # Optimal Query: First, Last (Full), and Sampled (Thin)
        if run_id:
            # Get First and Last IDs and count
            cur.execute("""
                SELECT MIN(id), MAX(id), COUNT(*) 
                FROM portfolio_snapshots 
                WHERE run_id = %s
            """, (run_id,))
            min_id, max_id, total_count = cur.fetchone()
            
            if total_count == 0:
                cur.close()
                return {"points": [], "summary": EMPTY_SUMMARY}
            
            # Fetch First and Last (Full)
            cur.execute("SELECT snapshot_time, heat_pct, full_json FROM portfolio_snapshots WHERE id IN (%s, %s)", (min_id, max_id))
            boundary_rows = cur.fetchall()
            
            # Sampled Points (Thin) - every Nth ID
            stride = max(1, total_count // 500)
            cur.execute(f"""
                SELECT snapshot_time, heat_pct, (full_json->>'total_equity')::float as equity 
                FROM portfolio_snapshots 
                WHERE run_id = %s AND id %% {stride} = 0
                ORDER BY snapshot_time ASC
            """, (run_id,))
            sampled_rows = cur.fetchall()
            
            # Build full_performance_data
            full_performance_data = []
            
            # Process sampled
            for r in sampled_rows:
                full_performance_data.append({
                    "time": r[0].isoformat(), "equity": r[2], "heat": r[1]
                })
                
            # Ensure boundaries are included with full fidelity
            for r in boundary_rows:
                # Handle cases where full_json might be a string or a dict
                f_json = r[2]
                if isinstance(f_json, str):
                    try: f_json = json.loads(f_json)
                    except: f_json = {}
                
                p = {
                    "time": r[0].isoformat(), 
                    "equity": f_json.get("total_equity", 0), 
                    "heat": r[1]
                }
                full_performance_data.append(p)
            
            # De-duplicate and sort
            unique_data = {p["time"]: p for p in full_performance_data}.values()
            full_performance_data = sorted(list(unique_data), key=lambda x: x["time"])
        else:
            # Live mode: Fetch 500 latest
            cur.execute("SELECT snapshot_time, heat_pct, full_json FROM portfolio_snapshots WHERE run_id IS NULL ORDER BY snapshot_time DESC LIMIT 500")
            rows = cur.fetchall()[::-1]
            full_performance_data = []
            for r in rows:
                full_performance_data.append({
                    "time": r[0].isoformat(),
                    "equity": r[2].get("total_equity", 0),
                    "heat": r[1]
                })
            
        if not full_performance_data:
            cur.close()
            return {"points": [], "summary": EMPTY_SUMMARY}

        # Calculate equity metrics...
        start_equity = full_performance_data[0]["equity"]
        current_equity = full_performance_data[-1]["equity"]
        net_profit = current_equity - start_equity
        total_pnl = ((current_equity / start_equity) - 1) * 100 if start_equity > 0 else 0
        
        peak = start_equity
        max_dd = 0
        daily_returns = []
        for i in range(1, len(full_performance_data)):
            prev = full_performance_data[i-1]["equity"]
            curr = full_performance_data[i]["equity"]
            if prev > 0:
                daily_returns.append((curr - prev) / prev)
            if curr > peak: peak = curr
            dd = (peak - curr) / peak * 100 if peak > 0 else 0
            if dd > max_dd: max_dd = dd

        performance_data = full_performance_data

        sharpe_ratio = 0.0
        if len(daily_returns) > 2:
            import statistics
            mean_ret = statistics.mean(daily_returns)
            std_ret = statistics.stdev(daily_returns)
            if std_ret > 0:
                sharpe_ratio = (mean_ret / std_ret) * math.sqrt(252 * (len(daily_returns) / max(1, len(performance_data))))

        # Fetch trades (REUSING CURSOR)
        winning_steps = 0
        losing_steps = 0
        total_gains = 0
        total_losses = 0
        total_trades = 0
        total_brokerage = 0.0
        mechanism_performance = []

        try:
            if run_id:
                cur.execute("SELECT pnl, price, quantity, mechanism FROM backtest_orders WHERE run_id = %s AND pnl IS NOT NULL AND pnl != 0", (run_id,))
            else:
                cur.execute("SELECT pnl, price, quantity, mechanism FROM backtest_orders WHERE run_id IS NULL AND pnl IS NOT NULL AND pnl != 0")
                
            trades = cur.fetchall()
            real_total_trades = len(trades)
            total_trades = real_total_trades # Use this for win rate
            mechanism_map = {}

            for t in trades:
                p_val = float(t[0] or 0)
                price = float(t[1] or 0)
                qty = int(t[2] or 0)
                mech = t[3] or "UNKNOWN"

                if mech not in mechanism_map:
                    mechanism_map[mech] = {"gains": 0.0, "losses": 0.0, "wins": 0, "total": 0, "brokerage": 0.0}
                
                m_stats = mechanism_map[mech]
                m_stats["total"] += 1
                
                if p_val > 0:
                    winning_steps += 1
                    total_gains += p_val
                    m_stats["wins"] += 1
                    m_stats["gains"] += p_val
                elif p_val < 0:
                    losing_steps += 1
                    total_losses += abs(p_val)
                    m_stats["losses"] += abs(p_val)
                    
                b = 20.0 + (price * qty * 0.001) if price > 0 and qty > 0 else 0.0
                total_brokerage += b
                m_stats["brokerage"] += b

            for name, m in mechanism_map.items():
                m_wr = (m["wins"] / m["total"] * 100) if m["total"] > 0 else 0
                m_pnl = m["gains"] - m["losses"]
                mechanism_performance.append({
                    "mechanism": name,
                    "trades": m["total"],
                    "win_rate": round(m_wr, 1),
                    "net_pnl": round(m_pnl, 2),
                    "profit_factor": round(m["gains"] / m["losses"], 2) if m["losses"] > 0 else (round(m["gains"], 2) if m["gains"] > 0 else 0.0)
                })
        except Exception as te:
            logger.error(f"Error fetching backtest orders: {te}")

        # cur.close() removed from here (moved to end of try block)
        
        win_rate = (winning_steps / total_trades * 100) if total_trades > 0 else 0
        profit_factor = (total_gains / total_losses) if total_losses > 0 else (total_gains if total_gains > 0 else 0.0)
        
        # Calculate real total trades (including entries) for the summary "Total Trades" stat
        # but use COMPLETED trades for expectancy
        cur.execute("SELECT COUNT(*) FROM backtest_orders WHERE run_id = %s", (run_id,))
        real_total_count = cur.fetchone()[0]
        
        expectancy = (total_gains - total_losses) / total_trades if total_trades > 0 else 0
        
        import datetime as dt_pkg
        start_date = dt_pkg.datetime.fromisoformat(performance_data[0]["time"])
        end_date = dt_pkg.datetime.fromisoformat(performance_data[-1]["time"])
        days = max(1, (end_date - start_date).days)
        years = days / 252.0
        cagr = ((current_equity / start_equity) ** (1/years) - 1) * 100 if years > 0.05 and start_equity > 0 else total_pnl

        summary_payload = {
            "total_pnl_pct": safe_float(round(total_pnl, 2)),
            "total_pnl": safe_float(round(total_pnl, 2)),
            "net_profit": safe_float(round(net_profit, 2)),
            "max_drawdown_pct": safe_float(round(max_dd, 2)),
            "max_drawdown": safe_float(round(max_dd, 2)),
            "current_equity": safe_float(round(current_equity, 2)),
            "win_rate": safe_float(round(win_rate, 1)),
            "win_rate_pct": safe_float(round(win_rate, 1)),
            "profit_factor": safe_float(round(profit_factor, 2)),
            "total_trades": int(real_total_count),
            "sharpe_ratio": safe_float(round(sharpe_ratio, 2)),
            "cagr": safe_float(round(cagr, 2)),
            "expectancy": safe_float(round(expectancy, 2)),
            "brokerage": safe_float(round(total_brokerage, 2)),
            "mechanism_performance": mechanism_performance
        }
        
        cur.close()
        return {
            "points": performance_data,
            "summary": summary_payload
        }
    except Exception as e:
        logger.error(f"Error fetching performance: {e}")
        return {"points": [], "summary": {
            "total_pnl_pct": 0.0, "total_pnl": 0.0, "net_profit": 0.0, "max_drawdown_pct": 0.0, "max_drawdown": 0.0,
            "current_equity": 0.0, "win_rate": 0.0, "win_rate_pct": 0.0, "profit_factor": 0.0, 
            "total_trades": 0, "sharpe_ratio": 0.0, "cagr": 0.0, 
            "expectancy": 0.0, "brokerage": 0.0, "mechanism_performance": []
        }}
    finally:
        if conn:
            conn.close()

@app.post("/api/v1/til/backtest")
async def trigger_backtest(req: BacktestRequest):
    """Triggers a background backtest run."""
    if backtest_controller.is_running:
        raise HTTPException(status_code=400, detail="A backtest is already in progress.")
        
    try:
        # Resolve defaults if start/end dates are missing
        if not req.start_date or not req.end_date:
            end_dt = datetime.now()
            start_dt = end_dt - timedelta(days=req.trading_days or 60)
            req.start_date = start_dt.strftime("%Y-%m-%d")
            req.end_date = end_dt.strftime("%Y-%m-%d")
        
        # Resolve symbols if missing
        if not req.symbols:
            req.symbols = list(SYMBOL_MAP.keys())[:req.universe_size or 10]

        # Prevent 0-trade runs by resolving human tickers to proper ISIN tokens
        formatted_symbols = [normalize_symbol(s) for s in req.symbols]
        
        # run_backtest now returns a dict with status and run_id
        result = await backtest_controller.run_backtest(
            formatted_symbols, req.start_date, req.end_date, 
            timeframe=req.timeframe, initial_capital=req.initial_capital
        )
        return {
            "status": result["status"], 
            "run_id": result.get("run_id"),
            "mode": "dynamic" if not req.symbols else "manual", 
            "range": f"{req.start_date} to {req.end_date}"
        }
    except Exception as e:
        logger.error(f"Error starting backtest: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/v1/til/backtest/trades/{run_id}")
async def get_backtest_trades(run_id: str):
    """Returns detailed trade log for a given backtest run."""
    conn = None
    try:
        pg_host = os.getenv("POSTGRES_HOST", "postgres_metadata")
        conn = psycopg2.connect(
            host=pg_host, port=5432, user="admin", password="password123", database="quant_platform"
        )
        cur = conn.cursor()
        cur.execute("""
            SELECT timestamp, symbol, transaction_type, quantity, price, pnl, mechanism 
            FROM backtest_orders 
            WHERE run_id = %s 
            ORDER BY timestamp DESC
        """, (run_id,))
        rows = cur.fetchall()
        trades = [
            {
                "time": r[0].isoformat() if r[0] else None,
                "symbol": r[1],
                "type": r[2],
                "qty": int(r[3]),
                "price": float(r[4]),
                "pnl": float(r[5]),
                "mechanism": r[6]
            } for r in rows
        ]
        cur.close()
        return trades
    except Exception as e:
        logger.error(f"Error fetching trades for {run_id}: {e}")
        return []
    finally:
        if conn:
            conn.close()

@app.get("/api/v1/til/backtest/status")
async def get_backtest_status():
    """Returns the current progress of the backtest."""
    return {
        "is_running": backtest_controller.is_running,
        "is_backfilling": backtest_controller.is_backfilling,
        "backfill_progress": backtest_controller.backfill_progress,
        "progress": backtest_controller.progress,
        "current_step": backtest_controller.current_step,
        "total_steps": backtest_controller.total_steps,
        "run_id": backtest_controller.current_simulation_run_id
    }
