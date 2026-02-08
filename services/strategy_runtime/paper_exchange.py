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
        Calculate position size based on user request: 100% of amount at once.
        Capital: ₹5,000 (standardized)
        """
        if price <= 0:
            return 1
        
        # User requested 100% allocation with 5x Leverage for Phase 8 goal
        LEVERAGE = 5
        qty = int((balance * LEVERAGE) / price)
        return max(1, qty)

    def execute_order(self, signal):
        """
        Executes a Buy/Sell order virtually.
        signal: {symbol, action, price, strategy_id}
        """
        symbol = signal['symbol']
        action = signal['action'].upper()
        price = float(signal['price'])
        strategy_id = signal.get('strategy_id', 'MANUAL')

        # Safety: Never trade Indices
        if "INDEX" in symbol.upper() or "Nifty 50" in symbol:
            logger.warning(f"🚫 Trade rejected: {symbol} is an Index.")
            return False

        conn = self._get_conn()
        cur = conn.cursor()

        # Table names depend on mode
        orders_table = "backtest_orders" if self.backtest_mode else "executed_orders"
        portfolios_table = "backtest_portfolios" if self.backtest_mode else "portfolios"
        positions_table = "backtest_positions" if self.backtest_mode else "positions"
        
        try:
            # 1. Get Portfolio
            if self.backtest_mode:
                cur.execute(f"SELECT id, balance FROM {portfolios_table} WHERE user_id = %s AND run_id = %s", (self.user_id, self.run_id))
            else:
                cur.execute(f"SELECT id, balance FROM {portfolios_table} WHERE user_id = %s", (self.user_id,))
            
            portfolio = cur.fetchone()
            
            # If backtest mode and no portfolio, auto-create one with default balance
            if not portfolio and self.backtest_mode:
                 cur.execute(f"INSERT INTO {portfolios_table} (user_id, run_id, balance) VALUES (%s, %s, 5000) RETURNING id, balance", (self.user_id, self.run_id))
                 portfolio = cur.fetchone()
                 conn.commit()
            
            if not portfolio:
                logger.error("No portfolio found!")
                return False
            
            pid, balance = portfolio
            balance = float(balance)
            
            # Calculate dynamic position size (or use provided quantity for partial exits)
            quantity = int(signal.get('quantity', self.calculate_position_size(price, balance)))

            if action == 'BUY':
                cost = price * quantity
                # Check for SHORT Position to cover
                cur.execute(f"SELECT quantity, avg_price FROM {positions_table} WHERE portfolio_id = %s AND symbol = %s", (pid, symbol))
                pos = cur.fetchone()
                
                if pos and pos[0] < 0:
                    # Closing/Reducing a SHORT
                    current_qty, avg_sell_price = int(pos[0]), float(pos[1])
                    qty_to_close = min(abs(current_qty), quantity)
                    pnl = (avg_sell_price - price) * qty_to_close
                    revenue = price * qty_to_close # Actually cost, but we subtract from balance? No, we add (SellPrice * Qty) then subtract (BuyPrice * Qty)
                    # Simplified: Balance += (AvgSellPrice - price) * qty_to_close? No, that's just PnL.
                    # Correct cash flow: 
                    # When Shorting: Balance += SellPrice * Qty
                    # When Covering: Balance -= BuyPrice * Qty
                    new_balance = balance + pnl # Balance updated by P&L
                    cur.execute(f"UPDATE {portfolios_table} SET balance = %s WHERE id = %s", (new_balance, pid))
                    
                    new_qty = current_qty + quantity
                    if new_qty == 0:
                        cur.execute(f"DELETE FROM {positions_table} WHERE portfolio_id = %s AND symbol = %s", (pid, symbol))
                    else:
                        cur.execute(f"UPDATE {positions_table} SET quantity = %s WHERE portfolio_id = %s AND symbol = %s", (new_qty, pid, symbol))
                    
                    logger.info(f"🔵 COVERED {quantity} {symbol} @ {price} | PnL: {pnl:.2f}")
                    
                    if self.backtest_mode:
                        # Use simulated timestamp for backtest accuracy
                        trade_time = signal.get('timestamp') 
                        insert_query = f"INSERT INTO {orders_table} (run_id, symbol, transaction_type, quantity, price, pnl, timestamp) VALUES (%s, %s, %s, %s, %s, %s, %s)"
                        cur.execute(insert_query, (self.run_id, symbol, action, quantity, price, pnl, trade_time))
                    else:
                        insert_query = f"INSERT INTO {orders_table} (strategy_id, symbol, transaction_type, quantity, price, pnl) VALUES (%s, %s, %s, %s, %s, %s)"
                        cur.execute(insert_query, (strategy_id, symbol, action, quantity, price, pnl))
                else:
                    # Opening/Increasing a LONG
                    if balance * 5 >= cost: # Ensure we have 5x buying power
                        # DO NOT subtract cost from balance. Balance = Total Equity.
                        cur.execute(f"""
                            INSERT INTO {positions_table} (portfolio_id, symbol, quantity, avg_price)
                            VALUES (%s, %s, %s, %s)
                            ON CONFLICT (portfolio_id, symbol) 
                            DO UPDATE SET 
                                avg_price = (({positions_table}.avg_price * {positions_table}.quantity) + (%s * %s)) / ({positions_table}.quantity + %s),
                                quantity = {positions_table}.quantity + %s
                        """, (pid, symbol, quantity, price, price, quantity, quantity, quantity))
                        
                        logger.info(f"🟢 BOUGHT {quantity} {symbol} @ {price}")
                        if self.backtest_mode:
                             trade_time = signal.get('timestamp')
                             insert_query = f"INSERT INTO {orders_table} (run_id, symbol, transaction_type, quantity, price, timestamp) VALUES (%s, %s, %s, %s, %s, %s)"
                             cur.execute(insert_query, (self.run_id, symbol, action, quantity, price, trade_time))
                        else:
                             insert_query = f"INSERT INTO {orders_table} (strategy_id, symbol, transaction_type, quantity, price) VALUES (%s, %s, %s, %s, %s)"
                             cur.execute(insert_query, (strategy_id, symbol, action, quantity, price))
                    else:
                        logger.warning(f"❌ Insufficient Funds (Leveraged) for {symbol}. Req: {cost}, Bal: {balance}")
                        return False

            elif action == 'SELL':
                # Check for LONG Position to exit
                cur.execute(f"SELECT quantity, avg_price FROM {positions_table} WHERE portfolio_id = %s AND symbol = %s", (pid, symbol))
                pos = cur.fetchone()
                
                if pos and pos[0] > 0:
                    # Closing/Reducing a LONG
                    current_qty, avg_buy_price = int(pos[0]), float(pos[1])
                    qty_to_close = min(current_qty, quantity)
                    pnl = (price - avg_buy_price) * qty_to_close
                    new_balance = balance + pnl # Balance updated only by P&L
                    cur.execute(f"UPDATE {portfolios_table} SET balance = %s WHERE id = %s", (new_balance, pid))
                    
                    new_qty = current_qty - quantity
                    if new_qty == 0:
                        cur.execute(f"DELETE FROM {positions_table} WHERE portfolio_id = %s AND symbol = %s", (pid, symbol))
                    else:
                        cur.execute(f"UPDATE {positions_table} SET quantity = %s WHERE portfolio_id = %s AND symbol = %s", (new_qty, pid, symbol))
                        
                    logger.info(f"🔴 SOLD {quantity} {symbol} @ {price} | PnL: {pnl:.2f}")
                    if self.backtest_mode:
                        trade_time = signal.get('timestamp')
                        insert_query = f"INSERT INTO {orders_table} (run_id, symbol, transaction_type, quantity, price, pnl, timestamp) VALUES (%s, %s, %s, %s, %s, %s, %s)"
                        cur.execute(insert_query, (self.run_id, symbol, action, quantity, price, pnl, trade_time))
                    else:
                        insert_query = f"INSERT INTO {orders_table} (strategy_id, symbol, transaction_type, quantity, price, pnl) VALUES (%s, %s, %s, %s, %s, %s)"
                        cur.execute(insert_query, (strategy_id, symbol, action, quantity, price, pnl))
                else:
                    # Opening/Increasing a SHORT
                    if balance * 5 >= cost: # Leverage check
                        # Store short as negative quantity. Avg price is the sell price.
                        cur.execute(f"""
                            INSERT INTO {positions_table} (portfolio_id, symbol, quantity, avg_price)
                            VALUES (%s, %s, %s, %s)
                            ON CONFLICT (portfolio_id, symbol) 
                            DO UPDATE SET 
                                avg_price = (({positions_table}.avg_price * ABS({positions_table}.quantity)) + (%s * %s)) / (ABS({positions_table}.quantity) + %s),
                                quantity = {positions_table}.quantity - %s
                        """, (pid, symbol, -quantity, price, price, quantity, quantity, quantity))
                        
                        logger.info(f"🔻 SHORTED {quantity} {symbol} @ {price}")
                        if self.backtest_mode:
                            trade_time = signal.get('timestamp')
                            insert_query = f"INSERT INTO {orders_table} (run_id, symbol, transaction_type, quantity, price, timestamp) VALUES (%s, %s, %s, %s, %s, %s)"
                            cur.execute(insert_query, (self.run_id, symbol, action, quantity, price, trade_time))
                        else:
                            insert_query = f"INSERT INTO {orders_table} (strategy_id, symbol, transaction_type, quantity, price) VALUES (%s, %s, %s, %s, %s)"
                            cur.execute(insert_query, (strategy_id, symbol, action, quantity, price))
                    else:
                        logger.warning(f"❌ Insufficient Funds (Leveraged) for {symbol}. Req: {cost}, Bal: {balance}")
                        return False

            conn.commit()
            return True

        except Exception as e:
            logger.error(f"Order Execution Error: {e}")
            conn.rollback()
            return False
        finally:
            cur.close()
            conn.close()
