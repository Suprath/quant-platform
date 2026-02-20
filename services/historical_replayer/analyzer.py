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
    
    # Fetch initial cash
    cur.execute("SELECT balance, equity FROM backtest_portfolios WHERE run_id = %s", (run_id,))
    row = cur.fetchone()
    # Use equity as the initial point for stats if balance was modified
    initial_cash = float(row[1]) if row and row[1] else 100000.0
    
    # Calculate daily P&L
    from collections import defaultdict
    daily_pnl_map = defaultdict(float)
    for o in orders:
        if o[2] == 'SELL' and o[5] is not None:
            # Assuming o[0] is a datetime object or can be parsed
            try:
                day = o[0].date() if hasattr(o[0], 'date') else datetime.fromisoformat(str(o[0])).date()
                daily_pnl_map[day] += float(o[5])
            except:
                pass
    
    # Calculate Equity Curve (Daily)
    sorted_days = sorted(daily_pnl_map.keys())
    current_equity = initial_cash
    equity_curve = [initial_cash]
    for d in sorted_days:
        current_equity += daily_pnl_map[d]
        equity_curve.append(current_equity)
        
    df_equity = np.array(equity_curve)
    # returns = [ (E_day1/E_start)-1, (E_day2/E_day1)-1, ... ]
    returns = np.diff(df_equity) / df_equity[:-1]
    
    sharpe_ratio = 0
    if len(returns) > 1:
        # Standard Daily Annualization
        std_dev = returns.std()
        if std_dev > 0.00001:
            # Sharpe = (Mean Return / Std Dev) * sqrt(252)
            # Subtracting a daily risk-free rate (~0.0002 for 6% annual)
            rf_daily = 0.06 / 252
            sharpe_ratio = ((returns.mean() - rf_daily) / std_dev) * np.sqrt(252)
            # Cap at 10 for display sanity on short backtests
            sharpe_ratio = max(-10.0, min(10.0, sharpe_ratio))
    
    # Calculate max drawdown %
    max_drawdown_pct = 0
    if len(df_equity) > 0:
        peaks = np.maximum.accumulate(df_equity)
        drawdowns = (df_equity - peaks) / peaks
        max_drawdown_pct = abs(drawdowns.min() * 100)
    
    # Build report
    report = {
        "run_id": run_id,
        "total_orders": len(orders),
        "total_trades": total_trades,
        "winning_trades": winning_trades,
        "losing_trades": losing_trades,
        "win_rate": round(win_rate, 2),
        "total_pnl": round(total_pnl, 2),
        "total_return": round((total_pnl / initial_cash) * 100, 2),
        "sharpe_ratio": round(sharpe_ratio, 2),
        "max_drawdown": round(total_pnl - (df_equity.min() - initial_cash), 2),
        "max_drawdown_pct": round(max_drawdown_pct, 2),
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
- **Total Net P&L**: ₹{report['total_pnl']}
- **Total Return**: {report['total_return']}%

## Performance Metrics
| Metric | Value |
|--------|-------|
| Winning Trades | {report['winning_trades']} |
| Losing Trades | {report['losing_trades']} |
| **Sharpe Ratio** | {report['sharpe_ratio']} |
| **Max Drawdown (₹)** | ₹{report['max_drawdown']} |
| **Max Drawdown (%)** | {report['max_drawdown_pct']}% |

## Interpretation
### Win Rate: {report['win_rate']}%
{'✅ **Good**: Above 50%' if report['win_rate'] > 50 else '⚠️ **Needs Improvement**: Below 50%'}

### Sharpe Ratio: {report['sharpe_ratio']}
{'✅ **Excellent**: > 1.0 (Good risk-adjusted returns)' if report['sharpe_ratio'] > 1.0 else '⚠️ **Poor**: < 1.0 (High risk for the returns)'}

### Max Drawdown: {report['max_drawdown_pct']}%
Peak-to-trough decline as a percentage of your highest capital point.

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
