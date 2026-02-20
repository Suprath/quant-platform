import os
import logging
import psycopg2

logger = logging.getLogger("PaperExchange")

class PaperExchange:
    """
    Indian Intraday Transaction Cost Model (NSE Equity - MIS/Intraday)
    Realistic charges as per Indian regulations:
    """
    # Brokerage: Flat ₹20 per order or 0.03%, whichever is lower (Zerodha model)
    BROKERAGE_FLAT = 20.0
    BROKERAGE_PCT = 0.0003  # 0.03%

    # STT (Securities Transaction Tax): 0.025% on SELL side only (Intraday)
    STT_PCT = 0.00025

    # Exchange Transaction Charges (NSE): 0.00345%
    EXCHANGE_TXN_PCT = 0.0000345

    # SEBI Turnover Fee: 0.0001%
    SEBI_FEE_PCT = 0.000001

    # Stamp Duty: 0.003% on BUY side only
    STAMP_DUTY_PCT = 0.00003

    # GST: 18% on (brokerage + exchange charges)
    GST_PCT = 0.18

    def __init__(self, db_config, backtest_mode=False, run_id=None):
        self.db_config = db_config
        self.backtest_mode = backtest_mode
        self.run_id = run_id
        self.user_id = 'default_user' # Single user for now

    def _get_conn(self):
        return psycopg2.connect(**self.db_config)

    def calculate_transaction_costs(self, turnover, side):
        """
        Calculate realistic Indian intraday transaction costs.
        side: 'BUY' or 'SELL'
        Returns total charges as a positive number.
        """
        brokerage_flat = float(os.getenv('BROKERAGE_FLAT', self.BROKERAGE_FLAT))
        brokerage_pct = float(os.getenv('BROKERAGE_PCT', self.BROKERAGE_PCT))
        
        # 1. Brokerage: min(FLAT, % of turnover)
        brokerage = min(brokerage_flat, turnover * brokerage_pct)

        # 2. STT: 0.025% on SELL side only
        stt = turnover * self.STT_PCT if side == 'SELL' else 0.0

        # 3. Exchange Transaction Charges
        exchange_txn = turnover * self.EXCHANGE_TXN_PCT

        # 4. SEBI Turnover Fee
        sebi_fee = turnover * self.SEBI_FEE_PCT

        # 5. Stamp Duty: 0.003% on BUY side only
        stamp_duty = turnover * self.STAMP_DUTY_PCT if side == 'BUY' else 0.0

        # 6. GST: 18% on (brokerage + exchange charges)
        gst = (brokerage + exchange_txn) * self.GST_PCT

        total = brokerage + stt + exchange_txn + sebi_fee + stamp_duty + gst
        return round(total, 2)

    def calculate_position_size(self, price, balance):
        """
        Calculate position size. Uses 100% of available cash (no artificial leverage).
        """
        if price <= 0:
            return 1
        
        qty = int(balance / price)
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
            
            logger.info(f"💰 Balance Before Trade: ₹{balance:.2f} | Action: {action} {quantity} {symbol} @ {price}")
            
            cost = price * quantity

            if action == 'BUY':
                # Check for SHORT Position to cover
                cur.execute(f"SELECT quantity, avg_price FROM {positions_table} WHERE portfolio_id = %s AND symbol = %s", (pid, symbol))
                pos = cur.fetchone()
                
                if pos and pos[0] < 0:
                    # Closing/Reducing a SHORT (Buying back)
                    current_qty = int(pos[0]) # Negative
                    # quantity is absolute buy amount
                    qty_to_close = min(abs(current_qty), quantity)
                    
                    # original_margin = qty_to_close * avg_price
                    # real logic: We unblock the margin locked at open.
                    # Simplification: Return (Price * Qty) + PnL? 
                    # No. Return (EntryPrice * Qty) + PnL.
                    # PnL = (Entry - Exit) * Qty.
                    # Return = Entry*Qty + (Entry-Exit)*Qty = 2*Entry*Qty - Exit*Qty? No.
                    
                    # Let's stick to the "Balance represents Cash on Hand" model.
                    # If we blocked Cash at Open:
                    # Open 100 @ 100. Balance -= 10000.
                    # Close 100 @ 90. PnL = 1000. Balance += 10000 + 1000 = 11000.
                    # Close 100 @ 110. PnL = -1000. Balance += 10000 - 1000 = 9000.
                    # Formula: Credit = (EntryPrice * Qty) + PnL - Charges.
                    
                    avg_entry = float(pos[1])
                    cost_to_cover = price * qty_to_close
                    charges = self.calculate_transaction_costs(cost_to_cover, 'BUY')
                    
                    gross_pnl = (avg_entry - price) * qty_to_close
                    margin_release = avg_entry * qty_to_close # The cash we locked
                    
                    # BUT wait, if price moved significantly, margin release logic depends on "Mark to Market"?
                    # No, simplified: We locked 'EntryPrice' amount. We return that +/- PnL.
                    credit = margin_release + gross_pnl - charges
                    
                    new_balance = balance + credit
                    cur.execute(f"UPDATE {portfolios_table} SET balance = %s WHERE id = %s", (new_balance, pid))
                    
                    new_qty = current_qty + qty_to_close
                    if new_qty == 0:
                        cur.execute(f"DELETE FROM {positions_table} WHERE portfolio_id = %s AND symbol = %s", (pid, symbol))
                    else:
                        cur.execute(f"UPDATE {positions_table} SET quantity = %s WHERE portfolio_id = %s AND symbol = %s", (new_qty, pid, symbol))
                    
                    logger.info(f"🔵 COVERED {qty_to_close} {symbol} @ {price} | PnL: {gross_pnl:.2f}")
                    
                    if self.backtest_mode:
                        trade_time = signal.get('timestamp') 
                        insert_query = f"INSERT INTO {orders_table} (run_id, symbol, transaction_type, quantity, price, pnl, timestamp) VALUES (%s, %s, %s, %s, %s, %s, %s)"
                        cur.execute(insert_query, (self.run_id, symbol, action, quantity, price, gross_pnl, trade_time))
                    else:
                        insert_query = f"INSERT INTO {orders_table} (strategy_id, symbol, transaction_type, quantity, price, pnl) VALUES (%s, %s, %s, %s, %s, %s)"
                        cur.execute(insert_query, (strategy_id, symbol, action, quantity, price, gross_pnl))
                        
                else:
                    # Opening/Increasing a LONG
                    # STRICT MARGIN: Deduct full cost
                    cost = price * quantity
                    charges = self.calculate_transaction_costs(cost, 'BUY')
                    total_outflow = cost + charges
                    
                    if balance >= total_outflow: 
                        new_balance = balance - total_outflow
                        cur.execute(f"UPDATE {portfolios_table} SET balance = %s WHERE id = %s", (new_balance, pid))

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
                        logger.warning(f"⏭️ Skipping BUY {symbol}: Insufficient cash (need ₹{total_outflow:.2f}, have ₹{balance:.2f})")
                        return False

            elif action == 'SELL':
                # Check for LONG Position to exit
                cur.execute(f"SELECT quantity, avg_price FROM {positions_table} WHERE portfolio_id = %s AND symbol = %s", (pid, symbol))
                pos = cur.fetchone()
                
                if pos and pos[0] > 0:
                    # Closing/Reducing a LONG
                    current_qty = int(pos[0])
                    qty_to_close = min(current_qty, quantity)
                    
                    proceeds = price * qty_to_close
                    charges = self.calculate_transaction_costs(proceeds, 'SELL')
                    
                    new_balance = balance + proceeds - charges
                    cur.execute(f"UPDATE {portfolios_table} SET balance = %s WHERE id = %s", (new_balance, pid))
                    
                    new_qty = current_qty - qty_to_close # Reducing positive
                    if new_qty == 0:
                        cur.execute(f"DELETE FROM {positions_table} WHERE portfolio_id = %s AND symbol = %s", (pid, symbol))
                    else:
                        cur.execute(f"UPDATE {positions_table} SET quantity = %s WHERE portfolio_id = %s AND symbol = %s", (new_qty, pid, symbol))
                        
                    avg_buy_price = float(pos[1])
                    pnl = (price - avg_buy_price) * qty_to_close - charges
                    
                    logger.info(f"🔴 SOLD {qty_to_close} {symbol} @ {price} | PnL: {pnl:.2f}")
                    
                    if self.backtest_mode:
                        trade_time = signal.get('timestamp')
                        insert_query = f"INSERT INTO {orders_table} (run_id, symbol, transaction_type, quantity, price, pnl, timestamp) VALUES (%s, %s, %s, %s, %s, %s, %s)"
                        cur.execute(insert_query, (self.run_id, symbol, action, quantity, price, pnl, trade_time))
                    else:
                        insert_query = f"INSERT INTO {orders_table} (strategy_id, symbol, transaction_type, quantity, price, pnl) VALUES (%s, %s, %s, %s, %s, %s)"
                        cur.execute(insert_query, (strategy_id, symbol, action, quantity, price, pnl))
                else:
                    # Opening/Increasing a SHORT
                    # STRICT MARGIN: Deduct full cost (Block Margin)
                    cost = price * quantity
                    charges = self.calculate_transaction_costs(cost, 'SELL')
                    total_outflow = cost + charges
                    
                    if balance >= total_outflow:
                        new_balance = balance - total_outflow
                        cur.execute(f"UPDATE {portfolios_table} SET balance = %s WHERE id = %s", (new_balance, pid))
                        
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
                        logger.warning(f"⏭️ Skipping SHORT {symbol}: Insufficient cash (need ₹{total_outflow:.2f}, have ₹{balance:.2f})")
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
