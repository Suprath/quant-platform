import os
import logging
import psycopg2
import psycopg2.extras
from calculations import TransactionCostCalculator
from db import get_db_connection, release_db_connection

logger = logging.getLogger("PaperExchange")


class PaperExchange:
    """
    High-Performance Indian Market Paper Exchange.

    BACKTEST MODE (Ultra-Fast):
    - Persistent DB connection — opened once, reused for all trades.
    - In-memory portfolio state — zero DB reads during simulation loop.
    - Batched order writes — all trades buffered in RAM, flushed once at end.
    - Result: ~50x faster than naive per-trade connection open/close.

    LIVE MODE:
    - Opens a fresh connection per trade (safe for multithreaded live trading).
    """

    # Indian Market Fee Constants
    BROKERAGE_FLAT   = 20.0
    BROKERAGE_PCT    = 0.0003
    STT_PCT          = 0.00025
    EXCHANGE_TXN_PCT = 0.0000345
    SEBI_FEE_PCT     = 0.000001
    STAMP_DUTY_PCT   = 0.00003
    GST_PCT          = 0.18

    def __init__(self, db_config, backtest_mode=False, run_id=None, trading_mode="MIS", leverage=1.0):
        self.db_config    = db_config
        self.backtest_mode = backtest_mode
        self.run_id       = run_id
        self.trading_mode = trading_mode.upper()
        self.leverage     = float(leverage)
        self.user_id      = 'default_user'
        self._cost_calculator = TransactionCostCalculator(trading_mode=self.trading_mode)

        # ── Backtest-only in-memory state ──────────────────────────────────
        # Eliminates ALL per-tick DB reads during simulation.
        self._bt_conn        = None   # Persistent connection (backtest only)
        self._bt_cur         = None   # Persistent cursor  (backtest only)
        self._bt_pid         = None   # Portfolio DB id
        self._bt_balance     = 0.0   # Cash balance (in RAM)
        self._bt_positions   = {}     # {symbol: {'qty': int, 'avg_price': float}}
        self._bt_order_buf   = []     # Buffered order rows — flushed once at end
        self._bt_trade_count = 0
        self._bt_tick_count  = 0
        self._bt_start_ts    = None

    # ──────────────────────────────────────────────────────────────────────
    # Session Management (backtest)
    # ──────────────────────────────────────────────────────────────────────

    def begin_session(self, initial_balance: float):
        """Initialize the persistent connection and load starting state."""
        import time
        self._bt_start_ts = time.time()

        self._bt_conn = get_db_connection()
        self._bt_conn.autocommit = False
        self._bt_cur  = self._bt_conn.cursor()

        # Get/create portfolio id
        self._bt_cur.execute(
            "SELECT id, balance FROM backtest_portfolios WHERE user_id=%s AND run_id=%s",
            (self.user_id, self.run_id)
        )
        row = self._bt_cur.fetchone()
        if row:
            self._bt_pid     = row[0]
            self._bt_balance = float(row[1])
        else:
            self._bt_cur.execute(
                "INSERT INTO backtest_portfolios (user_id, run_id, balance, equity) VALUES (%s,%s,%s,%s) RETURNING id, balance",
                (self.user_id, self.run_id, initial_balance, initial_balance)
            )
            row = self._bt_cur.fetchone()
            self._bt_pid     = row[0]
            self._bt_balance = float(row[1])
            self._bt_conn.commit()

        # Load existing positions (if any)
        self._bt_cur.execute(
            "SELECT symbol, quantity, avg_price FROM backtest_positions WHERE portfolio_id=%s",
            (self._bt_pid,)
        )
        for sym, qty, avg in self._bt_cur.fetchall():
            self._bt_positions[sym] = {'qty': int(qty), 'avg_price': float(avg)}

        logger.info(f"⚡ Backtest session opened — Balance: ₹{self._bt_balance:,.2f}, "
                    f"Existing positions: {len(self._bt_positions)}")

    def flush_session(self):
        """
        Flush all buffered orders + final portfolio state to DB in one transaction.
        Called ONCE at the end of the backtest.
        """
        import time
        if not self._bt_conn:
            return

        try:
            elapsed = time.time() - (self._bt_start_ts or time.time())
            tps = self._bt_tick_count / elapsed if elapsed > 0 else 0
            logger.info(f"💾 Flushing session — {self._bt_trade_count} trades, "
                        f"{self._bt_tick_count:,} ticks, {tps:,.0f} ticks/sec")

            # 1. Batch-insert all buffered orders
            if self._bt_order_buf:
                psycopg2.extras.execute_values(
                    self._bt_cur,
                    """INSERT INTO backtest_orders
                       (run_id, symbol, transaction_type, quantity, price, pnl, timestamp)
                       VALUES %s""",
                    self._bt_order_buf,
                    template="(%s,%s,%s,%s,%s,%s,%s)"
                )

            # 2. Persist final cash balance
            self._bt_cur.execute(
                "UPDATE backtest_portfolios SET balance=%s, equity=%s WHERE id=%s",
                (self._bt_balance, self._bt_balance, self._bt_pid)
            )

            # 3. Persist final positions
            self._bt_cur.execute(
                "DELETE FROM backtest_positions WHERE portfolio_id=%s",
                (self._bt_pid,)
            )
            if self._bt_positions:
                pos_rows = [
                    (self._bt_pid, sym, state['qty'], state['avg_price'])
                    for sym, state in self._bt_positions.items()
                    if state['qty'] != 0
                ]
                if pos_rows:
                    psycopg2.extras.execute_values(
                        self._bt_cur,
                        "INSERT INTO backtest_positions (portfolio_id, symbol, quantity, avg_price) VALUES %s",
                        pos_rows
                    )

            self._bt_conn.commit()
            logger.info(f"✅ Session flushed — Final balance: ₹{self._bt_balance:,.2f}")

        except Exception as e:
            logger.error(f"Flush error: {e}")
            self._bt_conn.rollback()
            raise
        finally:
            if self._bt_cur:  self._bt_cur.close()
            if self._bt_conn: 
                self._bt_conn.rollback() # Ensure transaction is ended
                release_db_connection(self._bt_conn)
            self._bt_cur = self._bt_conn = None

    # ──────────────────────────────────────────────────────────────────────
    # Internal helpers
    # ──────────────────────────────────────────────────────────────────────

    def _get_conn(self):
        """Return a connection from the pool."""
        return get_db_connection()

    def calculate_transaction_costs(self, turnover, side):
        return self._cost_calculator.calculate(turnover, side)

    def calculate_position_size(self, price, balance):
        if price <= 0:
            return 1
        # Use leverage for position sizing
        buying_power = balance * self.leverage
        return max(1, int(buying_power / price))

    def get_balance(self):
        """Return current cash balance (in-memory for backtest, DB for live)."""
        if self.backtest_mode:
            return self._bt_balance
        conn = self._get_conn()
        try:
            cur  = conn.cursor()
            cur.execute("SELECT balance FROM portfolios WHERE user_id=%s", (self.user_id,))
            row = cur.fetchone()
            return float(row[0]) if row else 0.0
        finally:
            release_db_connection(conn)

    def get_positions(self):
        """Return positions dict (in-memory for backtest)."""
        if self.backtest_mode:
            return {sym: s for sym, s in self._bt_positions.items() if s['qty'] != 0}
        # Live: read from DB
        conn = self._get_conn()
        try:
            cur  = conn.cursor()
            cur.execute(
                """SELECT p.symbol, p.quantity, p.avg_price
                   FROM positions p JOIN portfolios pf ON p.portfolio_id = pf.id
                   WHERE pf.user_id=%s""",
                (self.user_id,)
            )
            result = {row[0]: {'qty': int(row[1]), 'avg_price': float(row[2])} for row in cur.fetchall()}
            return result
        finally:
            release_db_connection(conn)

    # ──────────────────────────────────────────────────────────────────────
    # Order Execution
    # ──────────────────────────────────────────────────────────────────────

    def execute_order(self, signal):
        """
        Execute a BUY or SELL order.
        In backtest mode: pure in-memory arithmetic. No DB I/O during simulation.
        In live mode: single DB connection per order (thread-safe).
        """
        symbol      = signal['symbol']
        action      = signal['action'].upper()
        price       = float(signal['price'])
        strategy_id = signal.get('strategy_id', 'MANUAL')

        # Normalize timestamp: tick dicts carry ms epoch ints; Postgres needs datetime
        raw_ts = signal.get('timestamp')
        if isinstance(raw_ts, (int, float)):
            from datetime import datetime as _dt
            trade_time = _dt.utcfromtimestamp(raw_ts / 1000.0)
        elif raw_ts is None:
            from datetime import datetime as _dt
            trade_time = _dt.utcnow()
        else:
            trade_time = raw_ts

        # Safety: Never trade Indices
        if "INDEX" in symbol.upper() or "Nifty 50" in symbol:
            logger.warning(f"🚫 Trade rejected: {symbol} is an Index.")
            return False

        if self.backtest_mode:
            return self._execute_backtest(symbol, action, price, trade_time, strategy_id, signal)
        else:
            return self._execute_live(symbol, action, price, trade_time, strategy_id, signal)

    def _execute_backtest(self, symbol, action, price, trade_time, strategy_id, signal):
        """
        100% in-memory order execution for backtest mode.
        Zero DB reads. Writes buffered and flushed once at end.
        """
        balance   = self._bt_balance
        positions = self._bt_positions

        quantity = int(signal.get('quantity', self.calculate_position_size(price, balance)))

        if action == 'BUY':
            pos = positions.get(symbol, {'qty': 0, 'avg_price': 0.0})

            if pos['qty'] < 0:
                # Cover short
                qty_to_close  = min(abs(pos['qty']), quantity)
                avg_entry     = pos['avg_price']
                cost_to_cover = price * qty_to_close
                charges       = self.calculate_transaction_costs(cost_to_cover, 'BUY')
                gross_pnl     = (avg_entry - price) * qty_to_close
                credit        = avg_entry * qty_to_close + gross_pnl - charges

                self._bt_balance += credit
                new_qty = pos['qty'] + qty_to_close
                if new_qty == 0:
                    positions.pop(symbol, None)
                else:
                    positions[symbol] = {'qty': new_qty, 'avg_price': avg_entry}

                self._bt_order_buf.append((self.run_id, symbol, action, quantity, price, gross_pnl, trade_time))

            else:
                # Open / add to LONG
                cost        = price * quantity
                charges     = self.calculate_transaction_costs(cost, 'BUY')
                total_outflow = cost + charges

                # If leverage is 1.0, strictly enforce balance. 
                # If leverage > 1.0, we rely on the Engine's SetHoldings/SubmitOrder pre-flight checks 
                # as pure balance-based buying power is inaccurate with multiple positions.
                if self.leverage == 1.0 and balance < total_outflow:
                    logger.warning(f"⏩ Trade rejected: Insufficient funds for {quantity} {symbol} @ {price} (Need ₹{total_outflow:,.2f}, Have ₹{balance:,.2f})")
                    return False

                self._bt_balance -= total_outflow
                if symbol in positions and positions[symbol]['qty'] > 0:
                    old_qty = positions[symbol]['qty']
                    old_avg = positions[symbol]['avg_price']
                    new_qty = old_qty + quantity
                    new_avg = (old_avg * old_qty + price * quantity) / new_qty
                    positions[symbol] = {'qty': new_qty, 'avg_price': new_avg}
                else:
                    positions[symbol] = {'qty': quantity, 'avg_price': price}

                self._bt_order_buf.append((self.run_id, symbol, action, quantity, price, None, trade_time))

        elif action == 'SELL':
            pos = positions.get(symbol, {'qty': 0, 'avg_price': 0.0})

            if pos['qty'] > 0:
                # Close / reduce LONG
                qty_to_close = min(pos['qty'], quantity)
                proceeds     = price * qty_to_close
                charges      = self.calculate_transaction_costs(proceeds, 'SELL')
                avg_buy      = pos['avg_price']
                pnl          = (price - avg_buy) * qty_to_close - charges

                self._bt_balance += proceeds - charges
                new_qty = pos['qty'] - qty_to_close
                if new_qty == 0:
                    positions.pop(symbol, None)
                else:
                    positions[symbol] = {'qty': new_qty, 'avg_price': avg_buy}

                self._bt_order_buf.append((self.run_id, symbol, action, quantity, price, pnl, trade_time))

            else:
                # Open SHORT
                cost          = price * quantity
                charges       = self.calculate_transaction_costs(cost, 'SELL')
                total_outflow = cost + charges

                # If leverage is 1.0, strictly enforce balance.
                if self.leverage == 1.0 and balance < total_outflow:
                    logger.warning(f"⏩ Trade rejected: Insufficient funds to Short {quantity} {symbol} @ {price} (Need ₹{total_outflow:,.2f}, Have ₹{balance:,.2f})")
                    return False

                self._bt_balance -= total_outflow
                if symbol in positions and positions[symbol]['qty'] < 0:
                    old_qty = abs(positions[symbol]['qty'])
                    old_avg = positions[symbol]['avg_price']
                    new_qty = old_qty + quantity
                    new_avg = (old_avg * old_qty + price * quantity) / new_qty
                    positions[symbol] = {'qty': -new_qty, 'avg_price': new_avg}
                else:
                    positions[symbol] = {'qty': -quantity, 'avg_price': price}

                self._bt_order_buf.append((self.run_id, symbol, action, quantity, price, None, trade_time))

        self._bt_trade_count += 1
        return True

    def _execute_live(self, symbol, action, price, trade_time, strategy_id, signal):
        """Live mode: one DB connection per trade (thread-safe)."""
        conn = self._get_conn()
        cur  = conn.cursor()
        orders_table    = "executed_orders"
        portfolios_table = "portfolios"
        positions_table  = "positions"

        try:
            cur.execute(f"SELECT id, balance FROM {portfolios_table} WHERE user_id=%s", (self.user_id,))
            portfolio = cur.fetchone()
            if not portfolio:
                logger.error("No live portfolio found!")
                return False

            pid, balance = portfolio
            balance  = float(balance)
            quantity = int(signal.get('quantity', self.calculate_position_size(price, balance)))

            logger.info(f"💰 Balance: ₹{balance:.2f} | {action} {quantity} {symbol} @ {price}")

            if action == 'BUY':
                cur.execute(f"SELECT quantity, avg_price FROM {positions_table} WHERE portfolio_id=%s AND symbol=%s", (pid, symbol))
                pos = cur.fetchone()
                if pos and pos[0] < 0:
                    qty_to_close = min(abs(int(pos[0])), quantity)
                    avg_entry    = float(pos[1])
                    charges      = self.calculate_transaction_costs(price * qty_to_close, 'BUY')
                    gross_pnl    = (avg_entry - price) * qty_to_close
                    credit       = avg_entry * qty_to_close + gross_pnl - charges
                    cur.execute(f"UPDATE {portfolios_table} SET balance=%s WHERE id=%s", (balance + credit, pid))
                    new_qty = int(pos[0]) + qty_to_close
                    if new_qty == 0:
                        cur.execute(f"DELETE FROM {positions_table} WHERE portfolio_id=%s AND symbol=%s", (pid, symbol))
                    else:
                        cur.execute(f"UPDATE {positions_table} SET quantity=%s WHERE portfolio_id=%s AND symbol=%s", (new_qty, pid, symbol))
                    cur.execute(f"INSERT INTO {orders_table} (strategy_id,symbol,transaction_type,quantity,price,pnl) VALUES (%s,%s,%s,%s,%s,%s)",
                                (strategy_id, symbol, action, quantity, price, gross_pnl))
                else:
                    cost = price * quantity
                    charges = self.calculate_transaction_costs(cost, 'BUY')
                    buying_power = balance * self.leverage
                    if buying_power < cost + charges:
                        logger.warning(f"Insufficient buying power for BUY {symbol}")
                        return False
                    cur.execute(f"UPDATE {portfolios_table} SET balance=%s WHERE id=%s", (balance - cost - charges, pid))
                    cur.execute(f"""INSERT INTO {positions_table} (portfolio_id,symbol,quantity,avg_price)
                                    VALUES (%s,%s,%s,%s)
                                    ON CONFLICT (portfolio_id,symbol) DO UPDATE SET
                                        avg_price=({positions_table}.avg_price*{positions_table}.quantity+%s*%s)/({positions_table}.quantity+%s),
                                        quantity={positions_table}.quantity+%s""",
                                (pid, symbol, quantity, price, price, quantity, quantity, quantity))
                    cur.execute(f"INSERT INTO {orders_table} (strategy_id,symbol,transaction_type,quantity,price) VALUES (%s,%s,%s,%s,%s)",
                                (strategy_id, symbol, action, quantity, price))

            elif action == 'SELL':
                cur.execute(f"SELECT quantity, avg_price FROM {positions_table} WHERE portfolio_id=%s AND symbol=%s", (pid, symbol))
                pos = cur.fetchone()
                if pos and pos[0] > 0:
                    qty_to_close = min(int(pos[0]), quantity)
                    proceeds  = price * qty_to_close
                    charges   = self.calculate_transaction_costs(proceeds, 'SELL')
                    pnl       = (price - float(pos[1])) * qty_to_close - charges
                    cur.execute(f"UPDATE {portfolios_table} SET balance=%s WHERE id=%s", (balance + proceeds - charges, pid))
                    new_qty = int(pos[0]) - qty_to_close
                    if new_qty == 0:
                        cur.execute(f"DELETE FROM {positions_table} WHERE portfolio_id=%s AND symbol=%s", (pid, symbol))
                    else:
                        cur.execute(f"UPDATE {positions_table} SET quantity=%s WHERE portfolio_id=%s AND symbol=%s", (new_qty, pid, symbol))
                    cur.execute(f"INSERT INTO {orders_table} (strategy_id,symbol,transaction_type,quantity,price,pnl) VALUES (%s,%s,%s,%s,%s,%s)",
                                (strategy_id, symbol, action, quantity, price, pnl))
                else:
                    cost = price * quantity
                    charges = self.calculate_transaction_costs(cost, 'SELL')
                    buying_power = balance * self.leverage
                    if buying_power < cost + charges:
                        logger.warning(f"Insufficient buying power for SHORT {symbol}")
                        return False
                    cur.execute(f"UPDATE {portfolios_table} SET balance=%s WHERE id=%s", (balance - cost - charges, pid))
                    cur.execute(f"""INSERT INTO {positions_table} (portfolio_id,symbol,quantity,avg_price)
                                    VALUES (%s,%s,%s,%s)
                                    ON CONFLICT (portfolio_id,symbol) DO UPDATE SET
                                        avg_price=({positions_table}.avg_price*ABS({positions_table}.quantity)+%s*%s)/(ABS({positions_table}.quantity)+%s),
                                        quantity={positions_table}.quantity-%s""",
                                (pid, symbol, -quantity, price, price, quantity, quantity, quantity))
                    cur.execute(f"INSERT INTO {orders_table} (strategy_id,symbol,transaction_type,quantity,price) VALUES (%s,%s,%s,%s,%s)",
                                (strategy_id, symbol, action, quantity, price))

            conn.commit()
            return True

        except Exception as e:
            logger.error(f"Live Order Error: {e}")
            conn.rollback()
            return False
        finally:
            cur.close()
            conn.close()
