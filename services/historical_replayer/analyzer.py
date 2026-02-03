import os
import psycopg2
import logging
import argparse
from datetime import datetime
import json
import numpy as np

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger("BacktestAnalyzer")

DB_CONF = {
    "host": "postgres_metadata",
    "port": 5432,
    "user": "admin",
    "password": "password123",
    "database": "quant_platform"
}

def get_db_conn():
    return psycopg2.connect(**DB_CONF)

def analyze_backtest(run_id):
    """
    Generate performance report for a backtest run
    """
    conn = get_db_conn()
    cur = conn.cursor()
    
    # Fetch all orders for this run
    cur.execute("""
        SELECT timestamp, symbol, transaction_type, quantity, price, pnl
        FROM backtest_orders
        WHERE run_id = %s
        ORDER BY timestamp ASC
    """, (run_id,))
    
    orders = cur.fetchall()
    cur.close()
    conn.close()
    
    if not orders:
        logger.error(f"❌ No backtest data found for run_id: {run_id}")
        return None
    
    logger.info(f"📊 Analyzing {len(orders)} orders...")
    
    # Calculate metrics
    total_trades = len([o for o in orders if o[2] == 'SELL'])  # Count SELL orders
    winning_trades = len([o for o in orders if o[2] == 'SELL' and o[5] > 0])
    losing_trades = len([o for o in orders if o[2] == 'SELL' and o[5] < 0])
    
    total_pnl = sum([o[5] for o in orders if o[2] == 'SELL'])
    win_rate = (winning_trades / total_trades * 100) if total_trades > 0 else 0
    
    # Extract realized P&L series for Sharpe calculation
    pnl_series = [o[5] for o in orders if o[2] == 'SELL']
    
    sharpe_ratio = 0
    if len(pnl_series) > 1:
        returns = np.array(pnl_series)
        sharpe_ratio = (returns.mean() / returns.std()) * np.sqrt(252) if returns.std() > 0 else 0
    
    # Calculate max drawdown
    cumulative_pnl = []
    running_total = 0
    for o in orders:
        if o[2] == 'SELL':
            running_total += o[5]
            cumulative_pnl.append(running_total)
    
    max_drawdown = 0
    if cumulative_pnl:
        peak = cumulative_pnl[0]
        for val in cumulative_pnl:
            if val > peak:
                peak = val
            drawdown = peak - val
            if drawdown > max_drawdown:
                max_drawdown = drawdown
    
    # Build report
    report = {
        "run_id": run_id,
        "total_orders": len(orders),
        "total_trades": total_trades,
        "winning_trades": winning_trades,
        "losing_trades": losing_trades,
        "win_rate": round(win_rate, 2),
        "total_pnl": round(total_pnl, 2),
        "sharpe_ratio": round(sharpe_ratio, 3),
        "max_drawdown": round(max_drawdown, 2),
        "generated_at": datetime.now().isoformat()
    }
    
    return report

def generate_markdown_report(report):
    """
    Generate Markdown report from metrics
    """
    md = f"""# Backtest Results - {report['run_id']}

## Summary
- **Total Orders**: {report['total_orders']}
- **Total Completed Trades**: {report['total_trades']}
- **Win Rate**: {report['win_rate']}%
- **Total P&L**: ₹{report['total_pnl']}

## Performance Metrics
| Metric | Value |
|--------|-------|
| Winning Trades | {report['winning_trades']} |
| Losing Trades | {report['losing_trades']} |
| **Sharpe Ratio** | {report['sharpe_ratio']} |
| **Max Drawdown** | ₹{report['max_drawdown']} |

## Interpretation
### Win Rate: {report['win_rate']}%
{'✅ **Good**: Above 50%' if report['win_rate'] > 50 else '⚠️ **Needs Improvement**: Below 50%'}

### Sharpe Ratio: {report['sharpe_ratio']}
{'✅ **Excellent**: > 1.0 (Good risk-adjusted returns)' if report['sharpe_ratio'] > 1.0 else '⚠️ **Poor**: < 1.0 (High risk for the returns)'}

### Max Drawdown: ₹{report['max_drawdown']}
Peak-to-trough decline during the backtest period.

---
*Generated: {report['generated_at']}*
"""
    return md

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Analyze backtest results')
    parser.add_argument('--run-id', type=str, required=True, help='Backtest run ID')
    parser.add_argument('--output', type=str, default='backtest_results', help='Output directory')
    
    args = parser.parse_args()
    
    logger.info(f"📈 Analyzing backtest: {args.run_id}")
    
    report = analyze_backtest(args.run_id)
    
    if report:
        # Save JSON
        json_path = f"{args.output}/{args.run_id}.json"
        os.makedirs(args.output, exist_ok=True)
        with open(json_path, 'w') as f:
            json.dump(report, f, indent=2)
        logger.info(f"💾 Saved JSON: {json_path}")
        
        # Save Markdown
        md_report = generate_markdown_report(report)
        md_path = f"{args.output}/{args.run_id}.md"
        with open(md_path, 'w') as f:
            f.write(md_report)
        logger.info(f"📄 Saved Report: {md_path}")
        
        # Print summary
        print("\n" + "="*60)
        print(f"  BACKTEST SUMMARY: {args.run_id}")
        print("="*60)
        print(f"  Total P&L: ₹{report['total_pnl']}")
        print(f"  Win Rate: {report['win_rate']}%")
        print(f"  Sharpe Ratio: {report['sharpe_ratio']}")
        print(f"  Max Drawdown: ₹{report['max_drawdown']}")
        print("="*60 + "\n")
