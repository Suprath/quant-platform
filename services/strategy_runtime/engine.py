import os
import json
import logging
import importlib
import time
from datetime import datetime
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

            # Ensure Portfolio has entry
            if symbol not in self.Algorithm.Portfolio:
                self.Algorithm.Portfolio[symbol] = SecurityHolding(symbol)

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
            # Only applicable for LIVE mode usually, but useful to test in backtest
            if not self.BacktestMode:
                 # Live logic
                 pass
            elif self.BacktestMode and time_obj.hour == 15 and time_obj.minute >= 20:
                 # Backtest EOD logic
                 pass

            # 6. Call User Code
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
        
    def SetHoldings(self, symbol, percentage):
        """
        Logic for setting holdings to a specific percentage.
        """
        # 1. Sync Portfolio to get latest Balance
        self.SyncPortfolio()
        
        balance = self.Algorithm.Portfolio.get('Cash', 5000.0)
        
        # 2. Get Current Price
        # We need the last tick price for this symbol
        if not self.CurrentSlice or not self.CurrentSlice.ContainsKey(symbol):
            logger.warning(f"Cannot SetHoldings: No data for {symbol}")
            return
            
        price = self.CurrentSlice[symbol].Price
        if price <= 0: return

        # 3. Calculate Target Quantity
        # Leverage is 1.0 by default in SDK usually, but PaperExchange uses 5.0.
        # Let's assume 1.0 for calculation here, PaperExchange adds leverage safety.
        # Wait, if I want 100% allocation, I need to know buying power.
        # PaperExchange: `calculate_position_size` uses 5x leverage.
        
        # Let's match PaperExchange logic:
        buying_power = balance * 5 # 5x Leverage
        target_value = buying_power * percentage
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
                
                market_video = holding.Quantity * price
                unrealized_pnl = (price - holding.AveragePrice) * holding.Quantity
                
                equity += market_video
                
                holdings.append({
                    "symbol": symbol,
                    "quantity": holding.Quantity,
                    "avg_price": holding.AveragePrice,
                    "current_price": price,
                    "market_value": market_video,
                    "unrealized_pnl": unrealized_pnl
                })
                
        initial_capital = 100000.0 # TODO: Store initial capital somewhere or pass it in
        # We can try to fetch initial from DB or assume it based on first run?
        # For now, let's just return what we have. Frontend can calculate PnL % if it knows start capital,
        # or we just return Total PnL = Equity - Initial (if we knew Initial).
        
        return {
            "status": "running" if self.IsRunning else "stopped",
            "cash": cash,
            "equity": equity,
            "holdings": holdings
        }

    def Liquidate(self, symbol=None):
        if symbol:
            self.SetHoldings(symbol, 0)
        else:
            # Liquidate all
            self.SyncPortfolio()
            for sym, holding in self.Algorithm.Portfolio.items():
                 if isinstance(holding, SecurityHolding) and holding.Invested:
                     self.SetHoldings(sym, 0)

if __name__ == "__main__":
    pass
