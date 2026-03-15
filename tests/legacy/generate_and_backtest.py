"""
Orchestrator: Autonomous ETSI Strategy Generation & Backtesting
--------------------------------------------------------------
Usage:
    python generate_and_backtest.py

1. Triggers GodAgent training on T-15 days.
2. Extracts PyTorch weights and generates python strategy code.
3. Saves strategy to Runtime.
4. Triggers Backtest on the target window.
5. Polls for completion and generates a Markdown report.
"""

import sys
import time
import json
import requests
from datetime import datetime

ESTI_URL = "http://localhost:8002"
API_GATEWAY_URL = "http://localhost:8080"

# Target Configuration
BACKTEST_START_DATE = "2024-02-01"
BACKTEST_END_DATE = "2024-03-01"
SYMBOL = "NSE_EQ|INE002A01018"
EPOCHS = 15

def run_orchestrator():
    print("🚀 Starting ETSI Autonomous Orchestrator")
    print("=========================================\n")
    
    # 1. Generate Strategy (Pre-Train on T-15)
    print(f"[1/5] 🧠 Pre-training ESTI GodAgent for {BACKTEST_START_DATE}...")
    try:
        gen_res = requests.post(
            f"{ESTI_URL}/api/v1/esti/generate-strategy",
            json={
                "backtest_start_date": BACKTEST_START_DATE,
                "symbols": [SYMBOL],
                "population_size": 15,
                "epochs": EPOCHS
            },
            timeout=300 # Training takes time
        )
        gen_res.raise_for_status()
        gen_data = gen_res.json()
        strategy_code = gen_data.get("strategy_code")
        print(f"      ✅ AI Strategy Generated successfully! (Learning Window: {gen_data.get('learning_window')})")
    except Exception as e:
        print(f"      ❌ Failed to generate strategy: {e}")
        if hasattr(e, 'response') and e.response is not None:
             print(f"      Response: {e.response.text}")
        sys.exit(1)

    # 2. Save Strategy to Runtime
    strategy_name = f"EtsiAutonomous_{int(time.time())}"
    print(f"\n[2/5] 💾 Saving Strategy '{strategy_name}' to Runtime...")
    try:
        save_res = requests.post(
            f"{API_GATEWAY_URL}/api/v1/strategies/save",
            json={
                "name": strategy_name,
                "code": strategy_code
            },
            timeout=10
        )
        save_res.raise_for_status()
        print("      ✅ Strategy saved!")
    except Exception as e:
        print(f"      ❌ Failed to save strategy: {e}")
        sys.exit(1)

    # 3. Trigger Backtest
    print(f"\n[3/5] 📈 Triggering Backtest ({BACKTEST_START_DATE} to {BACKTEST_END_DATE})...")
    try:
        bt_res = requests.post(
            f"{API_GATEWAY_URL}/api/v1/backtest/run",
            json={
                "strategy_name": strategy_name,
                "strategy_code": strategy_code,
                "symbol": SYMBOL,
                "start_date": BACKTEST_START_DATE,
                "end_date": BACKTEST_END_DATE,
                "initial_cash": 100000.0,
                "speed": "fast"
            },
            timeout=10
        )
        bt_res.raise_for_status()
        run_id = bt_res.json().get("run_id")
        print(f"      ✅ Backtest started! Run ID: {run_id}")
    except Exception as e:
        print(f"      ❌ Failed to start backtest: {e}")
        sys.exit(1)

    # 4. Poll for Completion
    print(f"\n[4/5] ⏳ Polling Backtest Results...")
    stats = {}
    attempts = 0
    while attempts < 60: # 60 seconds timeout
        try:
            stats_res = requests.get(f"{API_GATEWAY_URL}/api/v1/backtest/stats/{run_id}")
            if stats_res.status_code == 200:
                stats_data = stats_res.json()
                if stats_data and isinstance(stats_data, dict) and "Return [%]" in stats_data:
                    stats = stats_data
                    print("      ✅ Backtest complete!")
                    break
        except Exception:
            pass
        time.sleep(1)
        attempts += 1
        sys.stdout.write(".")
        sys.stdout.flush()

    if not stats:
        print("\n      ❌ Backtest timed out or failed to return stats.")
        sys.exit(1)

    # 5. Generate Markdown Report
    print(f"\n[5/5] 📝 Generating Markdown Report...")
    
    report_path = f"esti_report_{strategy_name}.md"
    with open(report_path, "w") as f:
        f.write(f"# ETSI Autonomous Strategy Report\n\n")
        f.write(f"**Strategy Name:** `{strategy_name}`\n")
        f.write(f"**Target Symbol:** `{SYMBOL}`\n")
        f.write(f"**Backtest Period:** `{BACKTEST_START_DATE}` to `{BACKTEST_END_DATE}`\n")
        f.write(f"**AI Learning Window:** `{gen_data.get('learning_window')}` (T-15 Days)\n\n")
        
        f.write(f"## Backtest Performance\n\n")
        f.write(f"| Metric | Value |\n")
        f.write(f"| --- | --- |\n")
        
        display_metrics = [
            "Return [%]",
            "Sharpe Ratio",
            "Max. Drawdown [%]",
            "Win Rate [%]",
            "# Trades",
            "Initial Equity",
            "Final Equity",
            "Total Brokerage"
        ]
        
        for k in display_metrics:
            val = stats.get(k, "N/A")
            f.write(f"| **{k}** | {val} |\n")
            
        f.write(f"\n## Raw AI Neural Weights\n")
        f.write(f"The underlying PyTorch Base64 weights for the ESTIPolicy and SharedBrain have been permanently baked into the `{strategy_name}` algorithm code.\n")
        
    print(f"      ✅ Report saved to: {report_path}")
    print("\n🎉 ETSI Execution Pipeline completed successfully!")

if __name__ == "__main__":
    run_orchestrator()
