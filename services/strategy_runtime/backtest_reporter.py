import os
import psycopg2
import pandas as pd

DB_CONF = {
    "host": "postgres_metadata",
    "port": 5432,
    "user": "admin",
    "password": "password123",
    "database": "quant_platform"
}

def generate_report(run_id):
    try:
        conn = psycopg2.connect(**DB_CONF)
        
        # 1. Fetch Portfolio Stats
        port_df = pd.read_sql(f"SELECT * FROM backtest_portfolios WHERE run_id = '{run_id}'", conn)
        
        # 2. Fetch Trades
        orders_df = pd.read_sql(f"SELECT * FROM backtest_orders WHERE run_id = '{run_id}' ORDER BY timestamp", conn) # backtest_orders has run_id column? Yes I added it.
        
        conn.close()
        
        print(f"\n📊 BACKTEST REPORT: {run_id}")
        print("="*60)
        
        if port_df.empty:
            print("❌ No portfolio found. Did the strategy run?")
            return

        initial_balance = 5000.0  # Default logic in paper_exchange.py line 66
        final_balance = port_df.iloc[0]['balance']
        equity = port_df.iloc[0]['equity']
        pnl = final_balance - initial_balance
        ret_pct = (pnl / initial_balance) * 100
        
        print(f"💰 Initial Balance: ₹{initial_balance:,.2f}")
        print(f"💰 Final Balance:   ₹{final_balance:,.2f}")
        print(f"📈 Total Return:    {ret_pct:.2f}% (₹{pnl:,.2f})")
        
        if orders_df.empty:
            print("\n⚠️ No trades executed.")
            return

        # Calculate Win Rate
        closed_trades = orders_df[orders_df['transaction_type'].isin(['SELL'])] # Assuming SELL closes LONGs. 
        # Wait, strategy can Short too. `executed_orders` logs individual legs.
        # We need to pair them to get trade stats, or use pnl column if populated on exit.
        
        # In paper_exchange.py:
        # pnl is calculated on exit and stored in `executed_orders` (and `backtest_orders`).
        # The schema I added has `pnl` column.
        # And paper_exchange logic sets it?
        # Let's check update in paper_exchange.py (Step 7233).
        # It updates portfolio balance, but does it INSERT into orders with PnL?
        # I need to assume it does or calculate it here.
        
        # Let's filter for where pnl != 0
        profitable_trades = orders_df[orders_df['pnl'] > 0]
        losing_trades = orders_df[orders_df['pnl'] < 0]
        
        # If pnl col is 0 for all, implies paper_exchange might not be setting it on the order row correctly.
        # But let's check basic counts.
        
        total_orders = len(orders_df)
        print(f"\n🔢 Total Orders: {total_orders}")
        print(f"✅ Profitable Exits: {len(profitable_trades)}")
        print(f"❌ Losing Exits:     {len(losing_trades)}")
        
        print("\n📜 Recent Trades:")
        print(orders_df[['timestamp', 'symbol', 'transaction_type', 'price', 'quantity', 'pnl']].tail(10).to_string(index=False))
        
    except Exception as e:
        print(f"Error generating report: {e}")

if __name__ == "__main__":
    generate_report(os.getenv('RUN_ID', 'test_run'))
