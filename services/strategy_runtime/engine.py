import os
import json
import logging
import importlib
import time
from datetime import datetime, timezone, timedelta
import calculations
import timesync
from confluent_kafka import Consumer
from quant_sdk.data import Tick, Slice, FastSlice
from quant_sdk.algorithm import Resolution
from paper_exchange import PaperExchange
from schema import ensure_schema
from db import get_db_connection, DB_CONF

# Logging Setup
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("AlgorithmEngine")

class SubscriptionManager:
    def __init__(self):
        self.Subscriptions = {} # Symbol -> Resolution

    def Add(self, symbol, resolution):
        self.Subscriptions[symbol] = resolution
        logger.info(f"✅ Subscribed to {symbol} ({resolution})")

class SecurityHolding:
    def __init__(self, symbol, quantity=0, avg_price=0):
        self.Symbol = symbol
        self.Quantity = quantity
        self.AveragePrice = avg_price
        
    @property
    def Invested(self):
        return self.Quantity != 0

class AlgorithmEngine:
    # Indian Market Hours (IST)
    MARKET_OPEN_HOUR = 9
    MARKET_OPEN_MINUTE = 15
    SQUARE_OFF_HOUR = 15
    SQUARE_OFF_MINUTE = 20

    def __init__(self, run_id=None, backtest_mode=False, speed="fast", trading_mode="MIS"):
        self.Algorithm = None
        self.SubscriptionManager = SubscriptionManager()
        self.Indicators = {} # Symbol -> [Indicators]
        self.Exchange = None
        self.RunID = run_id
        self.BacktestMode = backtest_mode
        self.Speed = speed  # fast, medium, slow
        self.TradingMode = trading_mode.upper()
        self.KafkaConsumer = None
        self.CurrentSlice = None
        self.UniverseSettings = None # Stores selection function
        self.Leverage = 1.0  # Default: No leverage. User can override via strategy.
        self.ScannerFrequency = None  # Minutes between scanner runs (None = once per day)
        self._squared_off_today = False  # Track if we already squared off today
        self._last_square_off_date = None
        self._last_prices = {}  # Cache: symbol -> last known price
        self.EquityCurve = []   # List of {'timestamp': ts, 'equity': float}
        self.DailyReturns = []  # List of daily % returns
        
        # Connect to DB
        conn = get_db_connection()
        ensure_schema(conn)
        conn.close()
        
        # Init Exchange
        self.Exchange = PaperExchange(DB_CONF, backtest_mode=self.BacktestMode, run_id=self.RunID, trading_mode=self.TradingMode)
        self.IsRunning = False

    def LoadAlgorithm(self, module_name, class_name):
        """Dynamically load user algorithm."""
        try:
            module = importlib.import_module(module_name)
            AlgoClass = getattr(module, class_name)
            self.Algorithm = AlgoClass(engine=self)
            logger.info(f"🧩 Loaded Algorithm: {class_name}")
        except Exception as e:
            logger.error(f"❌ Failed to load algorithm: {e}")
            raise e

    def Initialize(self):
        """Call User Initialize and Setup Kafka."""
        if not self.Algorithm: return
        
        logger.info("⚙️ Initializing Algorithm...")
        self.Algorithm.Initialize()
        
        # Init Portfolio State
        self.SyncPortfolio()
        
        # Setup Kafka
        self.SetupKafka()

    def SetupKafka(self):
        conf = {
            'bootstrap.servers': os.getenv('KAFKA_BOOTSTRAP_SERVERS', 'kafka_bus:9092'),
            'group.id': f'algo-engine-{self.RunID}' if self.BacktestMode else 'algo-engine-live',
            'auto.offset.reset': 'earliest' if self.BacktestMode else 'latest'
        }
        self.KafkaConsumer = Consumer(conf)
        
        # Topic selection
        topic = f'market.enriched.ticks.{self.RunID}' if self.BacktestMode else 'market.enriched.ticks'
        self.KafkaConsumer.subscribe([topic])
        logger.info(f"📡 Subscribed to Kafka Topic: {topic}")

    def AddUniverse(self, selection_function):
        """
        Register a universe selection function.
        """
        self.UniverseSettings = selection_function
        logger.info("🌌 Universe Selection Registered")

    def RegisterIndicator(self, symbol, indicator, resolution):
        """Store indicator to update it automatically."""
        if symbol not in self.Indicators:
            self.Indicators[symbol] = []
        self.Indicators[symbol].append(indicator)

    def SetBacktestData(self, ticks):
        """Set local data for backtesting (bypassing Kafka)."""
        self.LocalData = ticks
        logger.info(f"📁 Loaded {len(ticks)} ticks for Local Backtest")

    # Indian Standard Time offset — delegate to timesync module
    IST = timesync.IST

    def _to_ist(self, time_obj):
        """Convert a datetime to IST. Delegates to timesync module."""
        return timesync.to_ist(time_obj, backtest_mode=self.BacktestMode)

    def _is_market_hours(self, time_obj):
        """Check if current time is within NSE trading hours (9:15 AM - 3:30 PM IST)."""
        return timesync.is_market_open(time_obj, backtest_mode=self.BacktestMode)


    def ProcessTick(self, tick_dict):
        """Standard tick processing (used for LIVE mode)."""
        # 1. Parse Data
        try:
            symbol = tick_dict.get('symbol')
            price = tick_dict.get('ltp', 0)
            volume = tick_dict.get('v', 0) or tick_dict.get('volume', 0)
            
            ts = tick_dict.get('timestamp')
            
            if not symbol or not price: return

            # 2. Create Tick Object
            time_obj = datetime.fromtimestamp(ts / 1000.0) if ts else datetime.now()
            tick = Tick(time_obj, symbol, price, volume)

            # --- MARKET HOURS FILTER (9:15 AM - 3:30 PM IST) ---
            if not self.BacktestMode and not self._is_market_hours(time_obj):
                return

            # Ensure Portfolio has entry
            if symbol not in self.Algorithm.Portfolio:
                self.Algorithm.Portfolio[symbol] = SecurityHolding(symbol)

            self._last_prices[symbol] = price

            # 3. Update Indicators
            if symbol in self.Indicators:
                for ind in self.Indicators[symbol]:
                    ind.Update(time_obj, price)

            # 4. Create Slice
            slice_obj = Slice(time_obj, {symbol: tick})
            self.CurrentSlice = slice_obj
            self.Algorithm.Time = time_obj

            # --- END OF DAY LOGIC & SQUARE-OFF ---
            ist_now = self._to_ist(time_obj)
            h, m = ist_now.hour, ist_now.minute
            today = ist_now.date()
            
            if self._last_square_off_date and self._last_square_off_date != today:
                self.SyncPortfolio()
                equity = self.Algorithm.Portfolio.get('TotalPortfolioValue', 0.0)
                self.EquityCurve.append({'timestamp': ist_now, 'equity': equity})
                self._squared_off_today = False
            
            if self._last_square_off_date is None:
                self._last_square_off_date = today

            if h == self.SQUARE_OFF_HOUR and m >= self.SQUARE_OFF_MINUTE and not self._squared_off_today:
                self._squared_off_today = True
                if self.TradingMode != "CNC":
                    has_positions = any(
                        isinstance(hold, SecurityHolding) and hold.Invested
                        for sym, hold in self.Algorithm.Portfolio.items()
                        if sym not in ('Cash', 'TotalPortfolioValue')
                    )
                    if has_positions:
                        logger.info("⏰ 3:20 PM IST — AUTO SQUARE-OFF: Liquidating all intraday positions")
                        self.Liquidate()
                return

            # Realtime Portfolio Valuation (live mode only)
            if not self.BacktestMode:
                self.CalculatePortfolioValue()

            self.Algorithm.OnData(slice_obj)

        except Exception as e:
            import traceback
            logger.error(f"Error in Event Loop: {e}\n{traceback.format_exc()}")

    # ──────────────────────────────────────────────────────────────
    # BACKTEST FAST PATH — zero allocations, zero timezone math
    # ──────────────────────────────────────────────────────────────

    def ProcessTickFast(self, tick_dict):
        """
        Backtest-only hot path. All per-tick overhead has been eliminated:
        - No datetime.fromtimestamp() (pre-computed in tick dict)
        - No Tick/Slice allocation (reuses cached objects)
        - No to_ist() timezone conversion (pre-computed fields)
        - No per-tick CalculatePortfolioValue (only on trade + day rollover)
        """
        symbol = tick_dict['symbol']
        price  = tick_dict['ltp']

        # ── Reuse cached Tick object ──
        _tick = self._reusable_tick
        _tick.Price = price
        _tick.Value = price
        _tick.Volume = tick_dict['v']
        _tick.Time = tick_dict['_dt']
        _tick.Symbol = symbol

        # ── Reuse cached FastSlice ──
        _slice = self._reusable_slice
        _slice.Time = tick_dict['_dt']
        _slice._data_symbol = symbol
        _slice._data_tick = _tick

        # ── Update state ──
        self._last_prices[symbol] = price
        self.Algorithm.Time = tick_dict['_dt']
        self.CurrentSlice = _slice

        # ── Ensure Portfolio has entry (first tick for this symbol) ──
        if symbol not in self.Algorithm.Portfolio:
            self.Algorithm.Portfolio[symbol] = SecurityHolding(symbol)

        # ── Indicator update (pre-cached list, no dict lookup) ──
        indicators = self._indicator_cache.get(symbol)
        if indicators:
            dt = tick_dict['_dt']
            for ind in indicators:
                ind.Update(dt, price)

        # ── Date rollover check (integer comparison, no datetime) ──
        tick_date = tick_dict['_date_int']
        if tick_date != self._bt_last_date_int:
            self._bt_handle_date_rollover(tick_dict)

        # ── Square-off check (pre-computed ints) ──
        if tick_dict['_hour'] == self.SQUARE_OFF_HOUR and tick_dict['_minute'] >= self.SQUARE_OFF_MINUTE:
            if not self._squared_off_today:
                self._bt_handle_square_off()
                return

        # ── Call user strategy ──
        self.Algorithm.OnData(_slice)

    def _bt_handle_date_rollover(self, tick_dict):
        """Handle date change during backtest. Called at most once per day."""
        self._bt_last_date_int = tick_dict['_date_int']

        if self._last_square_off_date is not None:
            # Log previous day's equity
            self.CalculatePortfolioValue()
            equity = self.Algorithm.Portfolio.get('TotalPortfolioValue', 0.0)
            self.EquityCurve.append({'timestamp': tick_dict['_dt'], 'equity': equity})

        self._last_square_off_date = tick_dict['_dt'].date() if hasattr(tick_dict['_dt'], 'date') else None
        self._squared_off_today = False

    def _bt_handle_square_off(self):
        """Handle auto square-off at 3:20 PM during backtest."""
        self._squared_off_today = True
        if self.TradingMode != "CNC":
            has_positions = any(
                isinstance(hold, SecurityHolding) and hold.Invested
                for sym, hold in self.Algorithm.Portfolio.items()
                if sym not in ('Cash', 'TotalPortfolioValue')
            )
            if has_positions:
                logger.info("⏰ 3:20 PM IST — AUTO SQUARE-OFF: Liquidating all intraday positions")
                self.Liquidate()


    def CalculatePortfolioValue(self):
        """
        Calculate Total Portfolio Value (Equity) in Realtime.
        Delegates to calculations module.
        """
        cash = self.Algorithm.Portfolio.get('Cash', 0.0)

        # Build price map from current slice + cached prices
        price_map = dict(self._last_prices)
        if self.CurrentSlice:
            for sym in list(self.Algorithm.Portfolio.keys()):
                if sym in ('Cash', 'TotalPortfolioValue'):
                    continue
                if self.CurrentSlice.ContainsKey(sym):
                    price_map[sym] = self.CurrentSlice[sym].Price

        equity = calculations.compute_portfolio_value(
            cash, self.Algorithm.Portfolio, price_map
        )
        self.Algorithm.Portfolio['TotalPortfolioValue'] = equity
        return equity

    def Run(self):
        """Main Data Loop."""
        import time as _time
        logger.info(f"🚀 Starting Engine Loop... (Backtest={self.BacktestMode})")
        
        # Initialize Portfolio from DB (First Sync)
        self.SyncPortfolio()
        
        # Inject Initial Equity Point (t=0) for Statistics
        start_ts = datetime.now()
        if self.BacktestMode and getattr(self, 'LocalData', None) and len(self.LocalData) > 0:
            first_tick = self.LocalData[0]
            start_ts = first_tick.get('_dt') or datetime.fromtimestamp(first_tick['timestamp'] / 1000.0)
            start_ts = start_ts - timedelta(seconds=1)
            
        self.EquityCurve.append({'timestamp': start_ts, 'equity': self.Algorithm.Portfolio.TotalPortfolioValue})
        
        # LOCAL DATA MODE (Backtest) ─ Ultra-Fast In-Memory Path
        if getattr(self, 'LocalData', None) is not None:
            delay = 0
            if self.Speed == 'medium': delay = 0.05
            elif self.Speed == 'slow': delay = 0.1

            # ── Open persistent session (zero per-trade connections) ──
            _has_session = self.BacktestMode and hasattr(self.Exchange, 'begin_session')
            _has_tick_count = self.BacktestMode and hasattr(self.Exchange, '_bt_tick_count')
            if _has_session:
                initial_bal = self.Algorithm.Portfolio.get('Cash', 100000.0)
                self.Exchange.begin_session(initial_bal)

            _t0 = _time.time()
            _n  = len(self.LocalData)

            # ── Choose fast path or standard path ──
            if self.BacktestMode and delay == 0:
                # ═══ TURBO BACKTEST PATH ═══
                # Pre-cache indicator lookups (avoid dict.get per tick)
                self._indicator_cache = dict(self.Indicators)
                # Create reusable objects (zero allocation per tick)
                self._reusable_tick = Tick(None, '', 0, 0)
                self._reusable_slice = FastSlice()
                self._bt_last_date_int = 0

                # Local method reference (avoids attribute lookup per tick)
                _process = self.ProcessTickFast
                _exchange = self.Exchange

                for tick in self.LocalData:
                    _process(tick)
                    _exchange._bt_tick_count += 1
            else:
                # Standard path (slow/medium speed, or live mode with local data)
                for tick in self.LocalData:
                    self.ProcessTick(tick)
                    if _has_tick_count:
                        self.Exchange._bt_tick_count += 1
                    if delay > 0: _time.sleep(delay)

            _elapsed = _time.time() - _t0
            _tps = _n / _elapsed if _elapsed > 0 else 0
            logger.info(f"⚡ Tick loop done: {_n:,} ticks in {_elapsed:.2f}s = {_tps:,.0f} ticks/sec")

            # ── Flush all buffered orders + positions to DB in one shot ──
            if _has_session:
                self.Algorithm.Portfolio['Cash'] = self.Exchange._bt_balance
                self.Exchange.flush_session()

            # Finalize Equity Curve
            self.SyncPortfolio()
            equity = self.Algorithm.Portfolio.get('TotalPortfolioValue', 0.0)
            self.EquityCurve.append({'timestamp': datetime.now(), 'equity': equity})
            
            logger.info("✅ Backtest Data Exhausted.")
            return

        # KAFKA MODE
        try:
            self.IsRunning = True
            while self.IsRunning:
                msg = self.KafkaConsumer.poll(0.1)
                if msg is None: continue
                if msg.error():
                    logger.error(f"Kafka Error: {msg.error()}")
                    continue

                data = json.loads(msg.value().decode('utf-8'))
                self.ProcessTick(data)

        except KeyboardInterrupt:
            logger.info("🛑 Stopping Engine...")
        finally:
            self.IsRunning = False
            if self.KafkaConsumer:
                self.KafkaConsumer.close()

    def Stop(self):
        """Stop the engine loop."""
        self.IsRunning = False
        logger.info("🛑 Stopping Engine Loop requested.")

    def SyncPortfolio(self):
        """
        Sync Portfolio state to User Algorithm.
        BACKTEST: reads from in-memory exchange state (zero DB I/O).
        LIVE: reads from DB.
        """
        # ── Fast path for backtest: read from in-memory exchange ──
        if self.BacktestMode and hasattr(self.Exchange, '_bt_balance') and self.Exchange._bt_balance > 0:
            balance   = self.Exchange._bt_balance
            positions = self.Exchange._bt_positions

            self.Algorithm.Portfolio['Cash'] = balance

            # Clear stale in-memory holdings first
            for sym in list(self.Algorithm.Portfolio.keys()):
                if sym not in ('Cash', 'TotalPortfolioValue'):
                    self.Algorithm.Portfolio[sym] = SecurityHolding(sym, 0, 0.0)

            # Apply current positions
            for sym, state in positions.items():
                if state['qty'] != 0:
                    self.Algorithm.Portfolio[sym] = SecurityHolding(sym, state['qty'], state['avg_price'])

            self.CalculatePortfolioValue()
            return

        # ── Standard DB-backed sync (live mode or pre-session backtest) ──
        conn = self.Exchange._get_conn()
        cur  = conn.cursor()
        try:
            table = "backtest_portfolios" if self.BacktestMode else "portfolios"
            if self.BacktestMode:
                cur.execute(f"SELECT balance FROM {table} WHERE user_id=%s AND run_id=%s", ('default_user', self.RunID))
            else:
                cur.execute(f"SELECT balance FROM {table} WHERE user_id=%s", ('default_user',))
            
            row = cur.fetchone()
            if not row:
                self.Algorithm.Portfolio['Cash'] = 100000.0
                self.Algorithm.Portfolio['TotalPortfolioValue'] = 100000.0
            else:
                balance = float(row[0])
                self.Algorithm.Portfolio['Cash'] = balance
                self.Algorithm.Portfolio['TotalPortfolioValue'] = balance

                pos_table = "backtest_positions" if self.BacktestMode else "positions"
                query = f"""
                    SELECT p.symbol, p.quantity, p.avg_price 
                    FROM {pos_table} p
                    JOIN {table} pf ON p.portfolio_id = pf.id
                    WHERE pf.user_id = 'default_user'
                """
                if self.BacktestMode:
                    query += f" AND pf.run_id = '{self.RunID}'"
                cur.execute(query)
                db_symbols = set()
                for sym, qty, avg in cur.fetchall():
                    db_symbols.add(sym)
                    self.Algorithm.Portfolio[sym] = SecurityHolding(sym, int(qty), float(avg))
                for sym in list(self.Algorithm.Portfolio.keys()):
                    if sym not in ('Cash', 'TotalPortfolioValue') and sym not in db_symbols:
                        self.Algorithm.Portfolio[sym] = SecurityHolding(sym, 0, 0.0)

                self.CalculatePortfolioValue()
                logger.info(f"🔄 SyncPortfolio: Cash=₹{self.Algorithm.Portfolio['Cash']:.2f}, Equity=₹{self.Algorithm.Portfolio['TotalPortfolioValue']:.2f}")
        except Exception as e:
            logger.error(f"SyncPortfolio Error: {e}")
        finally:
            if conn: conn.close()

    def SubmitOrder(self, symbol, quantity, order_type="MARKET"):
        """
        Execute order.
        quantity: can be absolute int, or float (percentage) if logic handled here.
        But SetHoldings calls with percentage.
        How do we distinguish? 
        QC uses `SetHoldings(symbol, percent)`. 
        `SubmitOrder` usually takes quantity.
        
        Let's implement `SetHoldings` logic inside `AlgorithmEngine` helper?
        Or make `SubmitOrder` accept `TargetPercent`.
        """
        pass
        
    def SetLeverage(self, leverage):
        """Set intraday leverage multiplier. Default is 1x (no leverage)."""
        self.Leverage = float(leverage)
        logger.info(f"⚙️ Leverage set to {self.Leverage}x")

    def SetScannerFrequency(self, minutes):
        """
        Set how often the scanner should re-evaluate stocks (in minutes).
        Call this in your strategy's Initialize() method.
        Example: self.SetScannerFrequency(30) = re-scan every 30 minutes.
        Default is None = once per day.
        """
        self.ScannerFrequency = int(minutes)
        logger.info(f"⏱️ Scanner frequency set to every {self.ScannerFrequency} minutes")

    def CalculateStatistics(self):
        """Calculate all statistics. Delegates to calculations module."""
        import pandas as pd

        # Baseline capital
        initial_cap = getattr(self, 'InitialCapital', self.Algorithm.Portfolio.get('Cash', 100000.0))
        if initial_cap <= 0:
            initial_cap = 100000.0

        # ── ALWAYS reconstruct equity curve from trade history ──
        # The in-memory EquityCurve only has sparse day-rollover snapshots.
        # For accurate Sharpe/Sortino we need one data point per trade.
        equity_curve = []
        pnl_list = []

        try:
            conn = self.Exchange._get_conn()
            cur = conn.cursor()
            table = "backtest_orders" if self.BacktestMode else "orders"

            # Fetch ALL trades (BUY + SELL) ordered chronologically
            cur.execute(
                f"SELECT timestamp, pnl FROM {table} WHERE run_id=%s ORDER BY timestamp ASC",
                (self.RunID,),
            )
            rows = cur.fetchall()

            # Build equity curve from cumulative PnL
            current_equity = initial_cap
            if rows:
                # Inject baseline point just before the first trade
                equity_curve.append({
                    'timestamp': rows[0][0] - timedelta(seconds=1),
                    'equity': initial_cap
                })
                for ts, pnl_val in rows:
                    trade_pnl = float(pnl_val) if pnl_val is not None else 0.0
                    current_equity += trade_pnl
                    equity_curve.append({'timestamp': ts, 'equity': current_equity})

                    # Collect non-zero PnLs for trade-level metrics
                    if pnl_val is not None and trade_pnl != 0.0:
                        pnl_list.append(trade_pnl)
            else:
                equity_curve.append({'timestamp': datetime.now(), 'equity': initial_cap})

            conn.close()
        except Exception as e:
            logger.error(f"Failed to reconstruct equity curve: {e}")
            # Fallback to sparse in-memory curve
            equity_curve = list(self.EquityCurve) if self.EquityCurve else [
                {'timestamp': datetime.now(), 'equity': initial_cap}
            ]

        logger.info(f"📈 Equity curve: {len(equity_curve)} points, PnL trades: {len(pnl_list)}")

        # Delegate to the calculations module
        stats = calculations.compute_all_statistics(
            equity_curve=equity_curve,
            pnl_list=pnl_list,
            initial_capital=initial_cap,
        )
        return stats

    def SaveStatistics(self):
        """Save computed statistics to DB (works for both backtest and live)."""
        
        try:
            stats = self.CalculateStatistics()
            conn = self.Exchange._get_conn()
            cur = conn.cursor()
            
            # Ensure table exists
            cur.execute("""
                CREATE TABLE IF NOT EXISTS backtest_results (
                    run_id UUID PRIMARY KEY,
                    sharpe_ratio FLOAT,
                    max_drawdown FLOAT,
                    win_rate FLOAT,
                    total_return FLOAT,
                    stats_json JSONB
                );
            """)

            cur.execute("""
                INSERT INTO backtest_results (run_id, sharpe_ratio, max_drawdown, win_rate, total_return, stats_json)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (run_id) DO UPDATE SET
                    sharpe_ratio = EXCLUDED.sharpe_ratio,
                    max_drawdown = EXCLUDED.max_drawdown,
                    win_rate = EXCLUDED.win_rate,
                    total_return = EXCLUDED.total_return,
                    stats_json = EXCLUDED.stats_json
            """, (
                self.RunID, 
                stats['sharpe_ratio'], 
                stats['max_drawdown'], 
                stats['win_rate'], 
                stats['total_return'], 
                json.dumps(stats)
            ))
            
            conn.commit()
            conn.close()
            logger.info(f"📊 Statistics Saved: Sharpe={stats['sharpe_ratio']}, Return={stats['total_return']}%")
        except Exception as e:
            logger.error(f"Failed to save statistics: {e}")

    def SetHoldings(self, symbol, percentage):
        """
        Set holdings for a symbol to a target percentage of portfolio equity.
        percentage: 0.1 = 10% long, -0.1 = 10% short, 0 = flat
        Uses self.Leverage (default 1x, configurable via SetLeverage).
        Returns True if order was executed, False otherwise.
        """
        # 1. Sync Portfolio to get latest Balance (skip in backtest — memory is current)
        if not self.BacktestMode:
            self.SyncPortfolio()
        
        cash = self.Algorithm.Portfolio.get('Cash', 0.0)
        
        # Calculate total equity (cash + position values)
        self.CalculatePortfolioValue()
        total_equity = self.Algorithm.Portfolio.get('TotalPortfolioValue', cash)
        
        # 2. Get Current Price (CurrentSlice first, then cached last price)
        
        # 2. Get Current Price (CurrentSlice first, then cached last price)
        price = None
        if self.CurrentSlice and self.CurrentSlice.ContainsKey(symbol):
            price = self.CurrentSlice[symbol].Price
        elif symbol in self._last_prices:
            price = self._last_prices[symbol]
        
        if not price or price <= 0:
            logger.warning(f"Cannot SetHoldings: No price data for {symbol}")
            return False

        # 3. Calculate Target Quantity
        buying_power = total_equity * self.Leverage
        target_value = buying_power * percentage  # Negative for short
        target_qty = int(target_value / price)
        
        logger.info(f"SetHoldings Calc: BP={buying_power:.2f} Pct={percentage} TgtVal={target_value:.2f} Price={price} Qty={target_qty}")
        
        # 4. Get Current Quantity
        current_holding = self.Algorithm.Portfolio.get(symbol)
        current_qty = current_holding.Quantity if current_holding else 0
        
        order_qty = target_qty - current_qty
        
        if order_qty == 0: return True
        
        action = "BUY" if order_qty > 0 else "SELL"
        
        # 5. For BUY orders: cap quantity to what available cash can afford
        if action == "BUY":
            # Keep a small cash buffer (2%) to avoid edge-case rejections
            usable_cash = cash * 0.98
            # Estimate transaction costs (~0.1%)
            max_affordable_value = usable_cash / 1.001
            max_affordable_qty = int(max_affordable_value / price)
            
            if max_affordable_qty <= 0:
                logger.info(f"⏭️ SetHoldings: Not enough cash for {symbol} (cash=₹{cash:.2f}, price=₹{price:.2f})")
                return False
            
            if abs(order_qty) > max_affordable_qty:
                logger.info(f"📉 SetHoldings: Capping {symbol} from {order_qty} to {max_affordable_qty} shares (limited by cash ₹{cash:.2f})")
                order_qty = max_affordable_qty

        # 6. For SELL/SHORT orders: also cap if opening new short position
        elif action == "SELL":
            # Only check cash if we are reducing cash (Opening Short)
            # Shorting requires blocking 100% margin from Cash
            current_long_qty = max(0, current_qty) # If we are long, selling reduces position, credits cash. No check needed.
            
            # We are selling `abs(order_qty)`. 
            # Part of it might be closing a long (generating cash).
            # Part of it might be opening a short (consuming cash).
            
            qty_to_close_long = min(abs(order_qty), current_long_qty)
            qty_new_short = abs(order_qty) - qty_to_close_long
            
            if qty_new_short > 0:
                # We need cash for the new short portion
                usable_cash = cash * 0.98 # Buffer
                max_short_value = usable_cash / 1.001
                max_short_qty = int(max_short_value / price)
                
                if max_short_qty <= 0:
                     logger.info(f"⏭️ SetHoldings: Not enough cash to Short {symbol} (cash=₹{cash:.2f})")
                     # If we can't short, but we were closing a long, just close the long
                     order_qty = -qty_to_close_long 
                     if order_qty == 0: return False
                
                elif qty_new_short > max_short_qty:
                     logger.info(f"📉 SetHoldings: Capping Short {symbol} to {max_short_qty} (limited by cash)")
                     order_qty = -(qty_to_close_long + max_short_qty)

        # 7. Execute
        signal = {
            "symbol": symbol,
            "action": action,
            "quantity": abs(order_qty),
            "price": price,
            "strategy_id": "USER_ALGO",
            "timestamp": self.Algorithm.Time if self.BacktestMode else None
        }
        
        success = self.Exchange.execute_order(signal)

        if success:
            logger.info(f"✅ Executed SetHoldings: {action} {abs(order_qty)} {symbol}")
            self.SyncPortfolio() # Update state immediately
        
        return success

    def GetLiveStatus(self):
        """
        Return current live statistics with Indian market context.
        Includes: portfolio state, holdings, daily P&L, trade count.
        """
        portfolio = self.Algorithm.Portfolio
        cash = portfolio.get('Cash', 0.0)
        initial_capital = getattr(self, 'InitialCapital', 100000.0)
        
        # Calculate Equity
        equity = cash
        holdings = []
        total_unrealized = 0.0
        
        for symbol, holding in portfolio.items():
            if symbol == 'Cash' or symbol == 'TotalPortfolioValue': continue
            if isinstance(holding, SecurityHolding) and holding.Invested:
                # Get current price
                price = self._last_prices.get(symbol, holding.AveragePrice)
                if self.CurrentSlice and self.CurrentSlice.ContainsKey(symbol):
                     price = self.CurrentSlice[symbol].Price
                
                market_value = holding.Quantity * price
                unrealized_pnl = (price - holding.AveragePrice) * holding.Quantity
                
                equity += market_value
                total_unrealized += unrealized_pnl
                
                holdings.append({
                    "symbol": symbol,
                    "quantity": holding.Quantity,
                    "avg_price": round(holding.AveragePrice, 2),
                    "current_price": round(price, 2),
                    "market_value": round(market_value, 2),
                    "unrealized_pnl": round(unrealized_pnl, 2)
                })
        
        # Daily P&L and trade count from DB
        total_trades = 0
        realized_pnl = 0.0
        try:
            conn = self.Exchange._get_conn()
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*), COALESCE(SUM(pnl), 0) FROM executed_orders WHERE pnl IS NOT NULL AND timestamp::date = CURRENT_DATE")
            row = cur.fetchone()
            if row:
                total_trades = row[0]
                realized_pnl = float(row[1])
            conn.close()
        except Exception as e:
            logger.warning(f"Could not fetch trade stats: {e}")

        total_pnl = equity - initial_capital
                
        return {
            "status": "running" if self.IsRunning else "stopped",
            "cash": round(cash, 2),
            "equity": round(equity, 2),
            "initial_capital": initial_capital,
            "total_pnl": round(total_pnl, 2),
            "total_pnl_pct": round((total_pnl / initial_capital) * 100, 2) if initial_capital > 0 else 0,
            "realized_pnl_today": round(realized_pnl, 2),
            "unrealized_pnl": round(total_unrealized, 2),
            "trades_today": total_trades,
            "holdings": holdings
        }

    def SetInitialCapital(self, capital):
        self.InitialCapital = float(capital)

    def Liquidate(self, symbol=None):
        """
        Close all positions (or a specific symbol).
        Uses cached last-known prices instead of CurrentSlice,
        so it works in backtests where CurrentSlice has only one symbol.
        """
        if symbol:
            # Liquidate single symbol
            self.SyncPortfolio()
            holding = self.Algorithm.Portfolio.get(symbol)
            if isinstance(holding, SecurityHolding) and holding.Invested:
                price = self._last_prices.get(symbol)
                if not price and self.CurrentSlice and self.CurrentSlice.ContainsKey(symbol):
                    price = self.CurrentSlice[symbol].Price
                if not price:
                    price = holding.AveragePrice  # Last resort fallback

                action = "SELL" if holding.Quantity > 0 else "BUY"
                signal = {
                    "symbol": symbol,
                    "action": action,
                    "quantity": abs(holding.Quantity),
                    "price": price,
                    "strategy_id": "USER_ALGO",
                    "timestamp": self.Algorithm.Time if self.BacktestMode else None
                }
                success = self.Exchange.execute_order(signal)
                if success:
                    logger.info(f"✅ Liquidated {symbol}: {action} {abs(holding.Quantity)} @ {price}")
                    self.SyncPortfolio()
        else:
            # Liquidate ALL positions
            self.SyncPortfolio()
            cash_before = self.Algorithm.Portfolio['Cash']
            logger.info(f"💣 Liquidating ALL. Cash Before: ₹{cash_before:.2f}")
            
            symbols_to_close = []
            for sym, holding in self.Algorithm.Portfolio.items():
                if isinstance(holding, SecurityHolding) and holding.Invested:
                    symbols_to_close.append((sym, holding))

            for sym, holding in symbols_to_close:
                price = self._last_prices.get(sym)
                if not price and self.CurrentSlice and self.CurrentSlice.ContainsKey(sym):
                    price = self.CurrentSlice[sym].Price
                if not price:
                    price = holding.AveragePrice  # Last resort fallback

                action = "SELL" if holding.Quantity > 0 else "BUY"
                signal = {
                    "symbol": sym,
                    "action": action,
                    "quantity": abs(holding.Quantity),
                    "price": price,
                    "strategy_id": "USER_ALGO",
                    "timestamp": self.Algorithm.Time if self.BacktestMode else None
                }
                success = self.Exchange.execute_order(signal)
                if success:
                    logger.info(f"✅ Liquidated {sym}: {action} {abs(holding.Quantity)} @ {price}")

            self.SyncPortfolio()
            cash_after = self.Algorithm.Portfolio['Cash']
            logger.info(f"✅ Liquidation Complete. Cash After: ₹{cash_after:.2f} (Diff: {cash_after - cash_before:+.2f})")

if __name__ == "__main__":
    pass
