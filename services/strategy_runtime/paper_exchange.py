import logging
import psycopg2

logger = logging.getLogger("PaperExchange")

class PaperExchange:
    def __init__(self, db_config, backtest_mode=False, run_id=None):
        self.db_config = db_config
        self.backtest_mode = backtest_mode
        self.run_id = run_id
        self.user_id = 'default_user' # Single user for now

    def _get_conn(self):
        return psycopg2.connect(**self.db_config)

    def calculate_position_size(self, price, balance):
        """
        Calculate position size for intraday trading with ₹20,000 capital.
        Risk: 1% per trade (₹200 max loss)
        """
        risk_per_trade = balance * 0.01  # 1% risk
        # For simplicity: invest 10% of capital per position
        # This allows up to 10 concurrent positions
        max_investment = balance * 0.10
        
        if price == 0:
            return 1
        
        qty = int(max_investment / price)
        return max(1, min(qty, 10))  # Min 1, Max 10 shares per trade

    def execute_order(self, signal):
        """
        Executes a Buy/Sell order virtually.
        signal: {symbol, action, price, strategy_id}
        """
        symbol = signal['symbol']
        action = signal['action'].upper()
        price = float(signal['price'])
        strategy_id = signal.get('strategy_id', 'MANUAL')

        conn = self._get_conn()
        cur = conn.cursor()

        # Table names depend on mode
        orders_table = "backtest_orders" if self.backtest_mode else "executed_orders"
        portfolios_table = "backtest_portfolios" if self.backtest_mode else "portfolios"
        
        try:
            # 1. Get Portfolio
            if self.backtest_mode:
                cur.execute(f"SELECT id, balance FROM {portfolios_table} WHERE user_id = %s AND run_id = %s", (self.user_id, self.run_id))
            else:
                cur.execute(f"SELECT id, balance FROM {portfolios_table} WHERE user_id = %s", (self.user_id,))
            
            portfolio = cur.fetchone()
            
            # If backtest mode and no portfolio, auto-create one with default balance
            if not portfolio and self.backtest_mode:
                 cur.execute(f"INSERT INTO {portfolios_table} (user_id, run_id, balance) VALUES (%s, %s, 20000) RETURNING id, balance", (self.user_id, self.run_id))
                 portfolio = cur.fetchone()
                 conn.commit()
            
            if not portfolio:
                logger.error("No portfolio found!")
                return False
            
            pid, balance = portfolio
            balance = float(balance)
            
            # Calculate dynamic position size
            quantity = self.calculate_position_size(price, balance)

            if action == 'BUY':
                cost = price * quantity
                if balance >= cost:
                    # Update Cash
                    new_balance = balance - cost
                    cur.execute(f"UPDATE {portfolios_table} SET balance = %s WHERE id = %s", (new_balance, pid))
                    
                    # Update Position (Upsert)
                    # NOTE: We keep using the 'positions' table but this shouldn't conflict with live as it's separate container/DB user
                    cur.execute("""
                        INSERT INTO positions (portfolio_id, symbol, quantity, avg_price)
                        VALUES (%s, %s, %s, %s)
                        ON CONFLICT (portfolio_id, symbol) 
                        DO UPDATE SET 
                            avg_price = ((positions.avg_price * positions.quantity) + (%s * %s)) / (positions.quantity + %s),
                            quantity = positions.quantity + %s
                    """, (pid, symbol, quantity, price, price, quantity, quantity, quantity))

                    logger.info(f"🟢 BOUGHT {quantity} {symbol} @ {price}")
                else:
                    logger.warning(f"❌ Insufficient Funds for {symbol}. Req: {cost}, Bal: {balance}")
                    return False

            elif action == 'SELL':
                # Check Position
                cur.execute("SELECT quantity, avg_price FROM positions WHERE portfolio_id = %s AND symbol = %s", (pid, symbol))
                pos = cur.fetchone()
                
                if pos and pos[0] >= quantity:
                    current_qty, avg_buy_price = pos
                    current_qty = int(current_qty)
                    avg_buy_price = float(avg_buy_price)

                    # Calc PnL
                    revenue = price * quantity
                    pnl = (price - avg_buy_price) * quantity
                    
                    # Update Cash
                    new_balance = balance + revenue
                    cur.execute(f"UPDATE {portfolios_table} SET balance = %s WHERE id = %s", (new_balance, pid))

                    # Update Position
                    new_qty = current_qty - quantity
                    if new_qty == 0:
                        cur.execute("DELETE FROM positions WHERE portfolio_id = %s AND symbol = %s", (pid, symbol))
                    else:
                        cur.execute("UPDATE positions SET quantity = %s WHERE portfolio_id = %s AND symbol = %s", (new_qty, pid, symbol))

                    logger.info(f"🔴 SOLD {quantity} {symbol} @ {price} | PnL: {pnl:.2f}")

                    # Log PnL to trade history specifically
                    if self.backtest_mode:
                        cur.execute("""
                            INSERT INTO backtest_orders (run_id, symbol, transaction_type, quantity, price, pnl)
                            VALUES (%s, %s, %s, %s, %s, %s)
                        """, (self.run_id, symbol, action, quantity, price, pnl))
                    else:
                        cur.execute("""
                            INSERT INTO executed_orders (strategy_id, symbol, transaction_type, quantity, price, pnl)
                            VALUES (%s, %s, %s, %s, %s, %s)
                        """, (strategy_id, symbol, action, quantity, price, pnl))
                    
                    conn.commit()
                    return True
                else:
                    logger.warning(f"❌ No Position to Sell for {symbol}")
                    return False

            # Log Trade (General - BUY)
            if action == 'BUY':
                if self.backtest_mode:
                    cur.execute("""
                        INSERT INTO backtest_orders (run_id, symbol, transaction_type, quantity, price)
                        VALUES (%s, %s, %s, %s, %s)
                    """, (self.run_id, symbol, action, quantity, price))
                else:
                    cur.execute("""
                        INSERT INTO executed_orders (strategy_id, symbol, transaction_type, quantity, price)
                        VALUES (%s, %s, %s, %s, %s)
                    """, (strategy_id, symbol, action, quantity, price))

            conn.commit()
            return True

        except Exception as e:
            logger.error(f"Order Execution Error: {e}")
            conn.rollback()
            return False
        finally:
            cur.close()
            conn.close()
