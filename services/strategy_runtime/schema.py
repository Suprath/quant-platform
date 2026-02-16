import logging

logger = logging.getLogger("StrategySchema")

def ensure_schema(conn):
    """
    Creates necessary tables for Paper Trading and Strategy Execution.
    """
    try:
        cur = conn.cursor()
        
        # 1. Portfolios: Tracks cash and equity
        cur.execute("""
            CREATE TABLE IF NOT EXISTS portfolios (
                id SERIAL PRIMARY KEY,
                user_id VARCHAR(50) UNIQUE NOT NULL,
                balance DECIMAL(15, 2) NOT NULL DEFAULT 100000.00,
                equity DECIMAL(15, 2) NOT NULL DEFAULT 100000.00,
                last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)

        # 2. Positions: Tracks current holdings
        cur.execute("""
            CREATE TABLE IF NOT EXISTS positions (
                id SERIAL PRIMARY KEY,
                portfolio_id INT REFERENCES portfolios(id),
                symbol VARCHAR(50) NOT NULL,
                quantity INT NOT NULL DEFAULT 0,
                avg_price DECIMAL(10, 2) NOT NULL,
                last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(portfolio_id, symbol)
            );
        """)

        # 3. Executed Orders (Trade History)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS executed_orders (
                id SERIAL PRIMARY KEY,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                strategy_id VARCHAR(50),
                symbol VARCHAR(50) NOT NULL,
                transaction_type VARCHAR(10) NOT NULL, -- BUY/SELL
                quantity INT NOT NULL,
                price DECIMAL(10, 2) NOT NULL,
                status VARCHAR(20) DEFAULT 'filled',
                pnl DECIMAL(10, 2) DEFAULT 0.0 -- Realized PnL for SELL orders
            );
        """)

        # 4. Optimized Parameters (Strategy Config)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS optimized_params (
                symbol VARCHAR(50) PRIMARY KEY,
                trailing_stop DECIMAL(8,6),
                profit_target DECIMAL(8,6),
                cooldown_seconds INT,
                sharpe_ratio DECIMAL(8,4),
                optimized_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)

        # --- BACKTEST TABLES (Mirrors of above with Run ID) ---
        
        # 5. Backtest Portfolios
        cur.execute("""
            CREATE TABLE IF NOT EXISTS backtest_portfolios (
                id SERIAL PRIMARY KEY,
                user_id VARCHAR(50) NOT NULL,
                run_id VARCHAR(100) NOT NULL,
                balance DECIMAL(15, 2) NOT NULL DEFAULT 100000.00,
                equity DECIMAL(15, 2) NOT NULL DEFAULT 100000.00,
                last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(user_id, run_id)
            );
        """)

        # 6. Backtest Positions
        cur.execute("""
            CREATE TABLE IF NOT EXISTS backtest_positions (
                id SERIAL PRIMARY KEY,
                portfolio_id INT REFERENCES backtest_portfolios(id) ON DELETE CASCADE,
                symbol VARCHAR(50) NOT NULL,
                quantity INT NOT NULL DEFAULT 0,
                avg_price DECIMAL(10, 2) NOT NULL,
                last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(portfolio_id, symbol)
            );
        """)

        # 7. Backtest Orders
        cur.execute("""
            CREATE TABLE IF NOT EXISTS backtest_orders (
                id SERIAL PRIMARY KEY,
                run_id VARCHAR(100),
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                strategy_id VARCHAR(50),
                symbol VARCHAR(50) NOT NULL,
                transaction_type VARCHAR(10) NOT NULL,
                quantity INT NOT NULL,
                price DECIMAL(10, 2) NOT NULL,
                status VARCHAR(20) DEFAULT 'filled',
                pnl DECIMAL(10, 2) DEFAULT 0.0
            );
        """)

        # 8. Backtest Universe (Scanner Results)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS backtest_universe (
                run_id VARCHAR(100),
                date DATE,
                symbol VARCHAR(50),
                score DECIMAL(10, 4),
                PRIMARY KEY (run_id, date, symbol)
            );
        """)
        
        # Initialize default portfolio if not exists
        cur.execute("INSERT INTO portfolios (user_id, balance, equity) VALUES ('default_user', 100000.00, 100000.00) ON CONFLICT (user_id) DO NOTHING;")

        conn.commit()
        cur.close()
        logger.info("✅ Strategy Runtime Schema Verified.")
        
    except Exception as e:
        logger.error(f"Schema Error: {e}")
        conn.rollback()
