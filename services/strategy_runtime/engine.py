import os
import json
import logging
import importlib
import time
from datetime import datetime, timezone, timedelta
from confluent_kafka import Consumer
from quant_sdk.data import Tick, Slice
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

    def __init__(self, run_id=None, backtest_mode=False):
        self.Algorithm = None
        self.SubscriptionManager = SubscriptionManager()
        self.Indicators = {} # Symbol -> [Indicators]
        self.Exchange = None
        self.RunID = run_id
        self.BacktestMode = backtest_mode
        self.KafkaConsumer = None
        self.CurrentSlice = None
        self.UniverseSettings = None # Stores selection function
        self.Leverage = 1.0  # Default: No leverage. User can override via strategy.
        self.ScannerFrequency = None  # Minutes between scanner runs (None = once per day)
        self._squared_off_today = False  # Track if we already squared off today
        self._last_square_off_date = None
        self._last_prices = {}  # Cache: symbol -> last known price
        
        # Connect to DB
        conn = get_db_connection()
        ensure_schema(conn)
        conn.close()
        
        # Init Exchange
        self.Exchange = PaperExchange(DB_CONF, backtest_mode=self.BacktestMode, run_id=self.RunID)
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

    # Indian Standard Time offset
    IST = timezone(timedelta(hours=5, minutes=30))

    def _to_ist(self, time_obj):
        """Convert a naive/UTC datetime to IST for market hours checks."""
        if time_obj.tzinfo is None:
            # Assume UTC (Docker containers default to UTC)
            return time_obj.replace(tzinfo=timezone.utc).astimezone(self.IST)
        return time_obj.astimezone(self.IST)

    def _is_market_hours(self, time_obj):
        """Check if current time is within NSE trading hours (9:15 AM - 3:30 PM IST)."""
        ist = self._to_ist(time_obj)
        h, m = ist.hour, ist.minute
        market_open = h > self.MARKET_OPEN_HOUR or (h == self.MARKET_OPEN_HOUR and m >= self.MARKET_OPEN_MINUTE)
        market_close = h < 15 or (h == 15 and m <= 30)
        return market_open and market_close

    def _should_square_off(self, time_obj):
        """Check if it's time for mandatory intraday square-off (3:20 PM IST)."""
        ist = self._to_ist(time_obj)
        today = ist.date()
        if self._last_square_off_date == today:
            return False  # Already squared off today
        h, m = ist.hour, ist.minute
        return h == self.SQUARE_OFF_HOUR and m >= self.SQUARE_OFF_MINUTE

    def ProcessTick(self, tick_dict):
        # 1. Parse Data
        try:
            symbol = tick_dict.get('symbol')
            price = tick_dict.get('ltp', 0)
            volume = tick_dict.get('v', 0) # 'v' or 'volume'
            if not volume: volume = tick_dict.get('volume', 0)
            
            ts = tick_dict.get('timestamp')
            
            if not symbol or not price: return

            # 2. Create Tick Object
            time_obj = datetime.fromtimestamp(ts / 1000.0) if ts else datetime.now()
            tick = Tick(time_obj, symbol, price, volume)

            # --- MARKET HOURS FILTER (9:15 AM - 3:30 PM IST) ---
            # Only apply in LIVE mode. Backtest data is already curated.
            if not self.BacktestMode and not self._is_market_hours(time_obj):
                return  # Skip pre/post-market ticks

            # Ensure Portfolio has entry
            if symbol not in self.Algorithm.Portfolio:
                self.Algorithm.Portfolio[symbol] = SecurityHolding(symbol)

            # Cache last known price for each symbol (used by Liquidate)
            self._last_prices[symbol] = price

            # 3. Update Indicators
            if symbol in self.Indicators:
                for ind in self.Indicators[symbol]:
                    ind.Update(time_obj, price)

            # 4. Create Slice
            slice_obj = Slice(time_obj, {symbol: tick})
            self.CurrentSlice = slice_obj
            
            # 5. Inject Time
            self.Algorithm.Time = time_obj

            # --- INTRADAY SQUARE-OFF (3:20 PM IST) ---
            # Indian rule: ALL intraday positions must be closed by 3:20 PM.
            if self._should_square_off(time_obj):
                self.SyncPortfolio()
                has_positions = any(
                    isinstance(h, SecurityHolding) and h.Invested
                    for sym, h in self.Algorithm.Portfolio.items()
                    if sym not in ('Cash', 'TotalPortfolioValue')
                )
                if has_positions:
                    logger.info("⏰ 3:20 PM IST — AUTO SQUARE-OFF: Liquidating all intraday positions")
                    self.Liquidate()
                self._last_square_off_date = self._to_ist(time_obj).date()
                return  # No new trades after square-off

            # 6. Reset square-off flag for new day
            ist_now = self._to_ist(time_obj)
            today = ist_now.date()
            if self._last_square_off_date and self._last_square_off_date != today:
                self._last_square_off_date = None

            # 7. Call User Code
            self.Algorithm.OnData(slice_obj)

        except Exception as e:
            logger.error(f"Error in Event Loop: {e}")

    def Run(self):
        """Main Data Loop."""
        logger.info("🚀 Starting Engine Loop...")
        
        # LOCAL DATA MODE
        if getattr(self, 'LocalData', None) is not None:
            for tick in self.LocalData:
                self.ProcessTick(tick)
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
        """Sync Portfolio state from DB to User Algorithm."""
        conn = self.Exchange._get_conn()
        cur = conn.cursor()
        
        # 1. Get Balance
        table = "backtest_portfolios" if self.BacktestMode else "portfolios"
        if self.BacktestMode:
            cur.execute(f"SELECT balance FROM {table} WHERE user_id=%s AND run_id=%s", ('default_user', self.RunID))
        else:
            cur.execute(f"SELECT balance FROM {table} WHERE user_id=%s", ('default_user',))
        
        row = cur.fetchone()
        if not row:
            # Create if missing (Engine should handle this init really)
            self.Algorithm.Portfolio['Cash'] = 5000.0 
            self.Algorithm.Portfolio['TotalPortfolioValue'] = 5000.0
        else:
            balance = float(row[0])
            self.Algorithm.Portfolio['Cash'] = balance
            self.Algorithm.Portfolio['TotalPortfolioValue'] = balance # Approximation

        # 2. Get Positions
        pos_table = "backtest_positions" if self.BacktestMode else "positions"
        # Need Portfolio ID first? Yes.
        # Simplified: Just fetch all positions for user? No, relational.
        # PaperExchange has logic to find PID. we duplicate or reuse.
        # Reusing exchange logic is hard as it's inside `execute_order`.
        # Let's just query with join
        
        query = f"""
            SELECT p.symbol, p.quantity, p.avg_price 
            FROM {pos_table} p
            JOIN {table} pf ON p.portfolio_id = pf.id
            WHERE pf.user_id = 'default_user' 
        """
        if self.BacktestMode:
            query += f" AND pf.run_id = '{self.RunID}'"
            
        cur.execute(query)
        rows = cur.fetchall()
        
        for r in rows:
            sym, qty, avg = r[0], int(r[1]), float(r[2])
            security = SecurityHolding(sym, qty, avg)
            self.Algorithm.Portfolio[sym] = security
            
            # Update Total Value (Cash + Equity)
            # We need current price for equity value. 
            # If we don't have it, use avg_price or last tick
            # For now, approximate with Avg Price (or 0 if new)
            # Correct way: use last known Ltp from Tick
            pass

        conn.close()

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

    def SetHoldings(self, symbol, percentage):
        """
        Set holdings for a symbol to a target percentage of portfolio equity.
        percentage: 0.1 = 10% long, -0.1 = 10% short, 0 = flat
        Uses self.Leverage (default 1x, configurable via SetLeverage).
        """
        # 1. Sync Portfolio to get latest Balance
        self.SyncPortfolio()
        
        cash = self.Algorithm.Portfolio.get('Cash', 0.0)
        
        # Calculate total equity (cash + position values)
        total_equity = cash
        for sym, holding in self.Algorithm.Portfolio.items():
            if sym in ('Cash', 'TotalPortfolioValue'): continue
            if isinstance(holding, SecurityHolding) and holding.Invested:
                total_equity += abs(holding.Quantity) * holding.AveragePrice
        
        # 2. Get Current Price (CurrentSlice first, then cached last price)
        price = None
        if self.CurrentSlice and self.CurrentSlice.ContainsKey(symbol):
            price = self.CurrentSlice[symbol].Price
        elif symbol in self._last_prices:
            price = self._last_prices[symbol]
        
        if not price or price <= 0:
            logger.warning(f"Cannot SetHoldings: No price data for {symbol}")
            return

        # 3. Calculate Target Quantity
        # buying_power = equity * leverage
        buying_power = total_equity * self.Leverage
        target_value = buying_power * percentage  # Negative for short
        target_qty = int(target_value / price)
        
        # 4. Get Current Quantity
        current_holding = self.Algorithm.Portfolio.get(symbol)
        current_qty = current_holding.Quantity if current_holding else 0
        
        order_qty = target_qty - current_qty
        
        if order_qty == 0: return
        
        action = "BUY" if order_qty > 0 else "SELL"
        
        # 5. Execute
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

    def GetLiveStatus(self):
        """
        Return current live statistics.
        """
        portfolio = self.Algorithm.Portfolio
        cash = portfolio.get('Cash', 0.0)
        
        # Calculate Equity
        equity = cash
        holdings = []
        
        for symbol, holding in portfolio.items():
            if symbol == 'Cash' or symbol == 'TotalPortfolioValue': continue # specific keys
            if isinstance(holding, SecurityHolding) and holding.Invested:
                # Get current price
                price = holding.AveragePrice # Default
                if self.CurrentSlice and self.CurrentSlice.ContainsKey(symbol):
                     price = self.CurrentSlice[symbol].Price
                
                market_value = holding.Quantity * price
                unrealized_pnl = (price - holding.AveragePrice) * holding.Quantity
                
                equity += market_value
                
                holdings.append({
                    "symbol": symbol,
                    "quantity": holding.Quantity,
                    "avg_price": holding.AveragePrice,
                    "current_price": price,
                    "market_value": market_value,
                    "unrealized_pnl": unrealized_pnl
                })
                
        return {
            "status": "running" if self.IsRunning else "stopped",
            "cash": cash,
            "equity": equity,
            "initial_capital": getattr(self, 'InitialCapital', 100000.0),
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

if __name__ == "__main__":
    pass
