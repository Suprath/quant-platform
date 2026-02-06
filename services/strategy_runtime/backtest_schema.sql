-- Backtest-specific tables (separate from live trading)
CREATE TABLE IF NOT EXISTS backtest_portfolios (
    id SERIAL PRIMARY KEY,
    run_id VARCHAR(50) NOT NULL,
    user_id VARCHAR(50) NOT NULL,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    balance DECIMAL(15, 2) NOT NULL,
    equity DECIMAL(15, 2) DEFAULT 0.0
);

CREATE TABLE IF NOT EXISTS backtest_orders (
    id SERIAL PRIMARY KEY,
    run_id VARCHAR(50) NOT NULL,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    symbol VARCHAR(50) NOT NULL,
    transaction_type VARCHAR(10) NOT NULL,
    quantity INT NOT NULL,
    price DECIMAL(10, 2) NOT NULL,
    pnl DECIMAL(10, 2) DEFAULT 0.0
);

-- positions specific to backtest
CREATE TABLE IF NOT EXISTS backtest_positions (
    id SERIAL PRIMARY KEY,
    portfolio_id INT NOT NULL,
    symbol VARCHAR(50) NOT NULL,
    quantity INT NOT NULL DEFAULT 0,
    avg_price DECIMAL(10, 2) NOT NULL,
    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(portfolio_id, symbol)
);

CREATE INDEX IF NOT EXISTS idx_backtest_run ON backtest_orders(run_id);
CREATE INDEX IF NOT EXISTS idx_backtest_timestamp ON backtest_orders(timestamp);
