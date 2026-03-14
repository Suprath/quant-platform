from abc import ABC, abstractmethod
from datetime import datetime
from enum import Enum
import logging


class Resolution(Enum):
    Tick = 0
    Second = 1
    Minute = 2
    Hour = 3
    Daily = 4

class OrderType(Enum):
    Market = 0
    Limit = 1
    StopMarket = 2
    StopLimit = 3

class PortfolioManager(dict):
    """
    Manages Portfolio State with helper properties.
    Behaves like a dictionary but provides .Cash, .TotalPortfolioValue, etc.
    """
    def __init__(self):
        super().__init__()
        self['Cash'] = 100000.0
        self['TotalPortfolioValue'] = 100000.0

    @property
    def Cash(self):
        return self.get('Cash', 0.0)

    @property
    def TotalPortfolioValue(self):
        return self.get('TotalPortfolioValue', 0.0)

    @property
    def TotalHoldingsValue(self):
        return self.TotalPortfolioValue - self.Cash

    @property
    def Invested(self):
        """Returns True if we have any holdings."""
        return self.TotalHoldingsValue > 0
    
    @property
    def MarginRemaining(self):
        return self.Cash # Simplified for now

    @property
    def ActiveUniverse(self):
        """Returns the list of symbols selected for the current trading day."""
        if self.Engine:
            return self.Engine.ActiveUniverse
        return []

class TimeRules:
    @staticmethod
    def At(hour, minute):
         from datetime import time
         return time(hour, minute)

class DateRules:
    @staticmethod
    def EveryDay():
         return "EveryDay"

class ScheduleManager:
    def __init__(self):
        self._events = []

    def On(self, date_rule, time_rule, callback):
        self._events.append({
             'date_rule': date_rule,
             'time': time_rule,
             'callback': callback,
             'last_triggered': None
        })

class OptionChainProvider:
    """
    Provides access to Option Chains from the API Gateway.
    """
    def __init__(self, algorithm):
        self.algorithm = algorithm
        self._base_url = "http://api_gateway:8000/api/v1"
        self._expiries_cache = {}
        self._contracts_cache = {}

    def GetExpiries(self, underlying_symbol):
        import requests
        try:
            # Tell the API Gateway what our 'current' date is for historical testing
            current_date_str = self.algorithm.Time.strftime('%Y-%m-%d')
            cache_key = f"{underlying_symbol}_{current_date_str}"
            
            if cache_key in self._expiries_cache:
                return self._expiries_cache[cache_key]
                
            url = f"{self._base_url}/options/expiries/{underlying_symbol}?as_of={current_date_str}"
            resp = requests.get(url, timeout=5)
            if resp.status_code == 200:
                data = resp.json()
                # Server already filtered them, we just need to parse back to datetime.date
                expiries = []
                from datetime import datetime
                for exp_str in data.get("expiries", []):
                    exp_date = datetime.strptime(exp_str, "%Y-%m-%d").date()
                    expiries.append(exp_date)
                sorted_expiries = sorted(expiries)
                self._expiries_cache[cache_key] = sorted_expiries
                return sorted_expiries
            return []
        except Exception as e:
            self.algorithm.Debug(f"OptionChainProvider failed to get expiries: {e}")
            return []

    def GetOptionContractList(self, underlying_symbol, expiry_date):
        import requests
        try:
            from datetime import datetime
            if isinstance(expiry_date, datetime):
                expiry_str = expiry_date.strftime("%Y-%m-%d")
            else:
                expiry_str = str(expiry_date) # handle date objects
                
            cache_key = f"{underlying_symbol}_{expiry_str}"
            if cache_key in self._contracts_cache:
                return self._contracts_cache[cache_key]
                
            url = f"{self._base_url}/options/chain/{underlying_symbol}?expiry={expiry_str}"
            resp = requests.get(url, timeout=5)
            if resp.status_code == 200:
                contracts = resp.json().get("contracts", [])
                parsed_contracts = [OptionContract(c) for c in contracts]
                self._contracts_cache[cache_key] = parsed_contracts
                return parsed_contracts
            return []
        except Exception as e:
            self.algorithm.Debug(f"OptionChainProvider failed to get chain: {e}")
            return []

class ExpiryWrapper:
    __slots__ = ['_date', 'days_to_expiry']
    def __init__(self, date_obj):
        self._date = date_obj
        self.days_to_expiry = 0

class OptionContract:
    __slots__ = ['Symbol', 'Strike', 'Right', '_exp_date', 'Expiry']
    def __init__(self, data):
        self.Symbol = data.get("instrument_token")
        self.Strike = float(data.get("strike", 0))
        self.Right = 'Call' if data.get("option_type") == 'CE' else 'Put'
        
        # Fast string slice parsing instead of slow strptime
        exp_str = data.get("expiry", "2026-01-01")
        from datetime import date
        try:
            self._exp_date = date(int(exp_str[:4]), int(exp_str[5:7]), int(exp_str[8:10]))
        except ValueError:
            self._exp_date = date.today()
        self.Expiry = ExpiryWrapper(self._exp_date)
        
    def update_date(self, current_date):
        self.Expiry.days_to_expiry = (self._exp_date - current_date).days

    def __repr__(self):
        return f"<{self.Symbol} {self.Strike} {self.Right}>"

class QCAlgorithm(ABC):
    """
    Base class for all user algorithms.
    Mirroring QuantConnect's API structure.
    """
    def __init__(self, engine=None):
        self.Engine = engine
        self.Portfolio = PortfolioManager() # Replaced raw dict with Manager
        self.Time = datetime.now()
        self.IsWarmingUp = False
        self._logger = logging.getLogger("UserAlgorithm")
        self.TimeRules = TimeRules()
        self.DateRules = DateRules()
        self.Schedule = ScheduleManager()
        self.OptionChainProvider = OptionChainProvider(self)

    @property
    def ActiveUniverse(self):
        """Returns the list of symbols selected for the current trading day."""
        if self.Engine:
            return self.Engine.ActiveUniverse
        return []

    def Initialize(self):
        """
        Initialise the data and resolution required, as well as the cash and start-end dates for your algorithm.
        All algorithms must implement this method.
        """
        pass

    @abstractmethod
    def OnData(self, data):
        """
        OnData event is the primary entry point for your algorithm. Each new data point will be pumped in here.
        
        :param data: Slice object keyed by symbol containing the stock data
        """
        pass

    def OptionChain(self, underlying_symbol):
        """
        Fetches the active Option Chain (all strikes) for the nearest 3 expiries.
        Returns a list of OptionContract objects that can be filtered dynamically.
        """
        chain = []
        current_date = self.Time.date() if getattr(self, 'Time', None) else datetime.now().date()
        
        # 1. Get Expiries
        expiries = self.OptionChainProvider.GetExpiries(underlying_symbol)
        
        # 2. For each expiry (limit to nearest 3 to avoid massive API overheads in backtests)
        for expiry in expiries[:3]:
            cached_contracts = self.OptionChainProvider.GetOptionContractList(underlying_symbol, expiry)
            for c in cached_contracts:
                c.update_date(current_date)
                chain.append(c)
                
        return chain

    # --- Configuration Methods ---
    def SetStartDate(self, year, month, day):
        """Set the start date for backtesting."""
        # Logic handled by Engine, but we store it for metadata
        pass

    def SetEndDate(self, year, month, day):
        """Set the end date for backtesting."""
        pass

    def SetCash(self, starting_cash):
        """Set the starting capital for the strategy."""
        if self.Engine:
            self.Engine.SetCash(starting_cash)

    def AddEquity(self, symbol, resolution=Resolution.Minute):
        """
        Add a stock to the algorithm.
        """
        if self.Engine:
             self.Engine.SubscriptionManager.Add(symbol, resolution)

    def AddUniverse(self, selection_function):
        """
        Add a dynamic universe of stocks.
        selection_function: A function that takes a list of coarse data and returns a list of symbols.
        """
        if self.Engine:
            self.Engine.AddUniverse(selection_function)

    # --- Indicator Helpers ---
    def SMA(self, symbol, period, resolution=Resolution.Minute):
        """Creates a Simple Moving Average indicator."""
        from .indicators import SimpleMovingAverage # Local import to avoid circular dependency
        sma = SimpleMovingAverage(f"SMA({period})", period)
        if self.Engine:
            self.Engine.RegisterIndicator(symbol, sma, resolution)
        return sma

    def EMA(self, symbol, period, resolution=Resolution.Minute):
        """Creates an Exponential Moving Average indicator."""
        from .indicators import ExponentialMovingAverage # Local import to avoid circular dependency
        ema = ExponentialMovingAverage(f"EMA({period})", period)
        if self.Engine:
            self.Engine.RegisterIndicator(symbol, ema, resolution)
        return ema

    def RSI(self, symbol, period, resolution=Resolution.Minute):
        """Creates a Relative Strength Index (RSI) indicator."""
        from .indicators import RelativeStrengthIndex # Local import to avoid circular dependency
        rsi = RelativeStrengthIndex(f"RSI({period})", period)
        if self.Engine:
            self.Engine.RegisterIndicator(symbol, rsi, resolution)
        return rsi

    # --- Trading Methods ---
    def SetHoldings(self, symbol, percentage, liquidate_existing_holdings=False):
        """
        Sets the holdings of a particular symbol to a percentage of total equity.
        """
        if self.Engine:
            # Call the engine's SetHoldings helper directly
            if hasattr(self.Engine, 'SetHoldings'):
                self.Engine.SetHoldings(symbol, percentage)

    def MarketOrder(self, symbol, quantity):
        """
        Place a market order for a specific quantity.
        quantity: positive for BUY, negative for SELL.
        """
        if self.Engine:
            return self.Engine.SubmitOrder(symbol, quantity, "MARKET")
        return False

    def Buy(self, symbol, quantity):
        """
        Buy a specific quantity of a symbol.
        """
        return self.MarketOrder(symbol, abs(quantity))

    def Sell(self, symbol, quantity):
        """
        Sell a specific quantity of a symbol.
        """
        return self.MarketOrder(symbol, -abs(quantity))

    def Liquidate(self, symbol=None):
        """
        Liquidates the specified symbol, or all if None.
        """
        if self.Engine:
             self.Engine.Liquidate(symbol)

    def SetLeverage(self, leverage):
        """Set intraday leverage multiplier. Default is 1x."""
        if self.Engine:
            self.Engine.SetLeverage(leverage)

    def SetScannerFrequency(self, minutes):
        """
        Set how often the scanner should re-evaluate stocks (in minutes).
        Call in Initialize(). Example: self.SetScannerFrequency(30)
        Default = once per day.
        """
        if self.Engine:
            self.Engine.SetScannerFrequency(minutes)

    # --- KIRA INTEGRATION HELPERS ---
    def GetKiraConfidence(self, symbol):
        """
        Fetches signal confidence from KIRA. 
        Automatically includes self.Time for backtest synchronization.
        """
        # --- PHASE 9: Memory-Efficient Chunked Reading ---
        # If in backtest mode and NoiseData is pre-loaded by engine, use it (zero latency)
        if self.Engine and self.Engine.BacktestMode:
            if symbol in self.Engine.NoiseData:
                return self.Engine.NoiseData[symbol]
        
        # Fallback to API Gateway (Live mode or if missing from cache)
        import requests
        try:
            # Sync with current algorithm time to avoid lookahead bias
            ts = self.Time.isoformat()
            url = f"http://api_gateway:8000/api/v1/kira/noise-filter/confidence/{symbol}?timestamp={ts}"
            resp = requests.get(url, timeout=2)
            if resp.status_code == 200:
                return resp.json().get("confidence", 0)
        except Exception as e:
            self.Debug(f"SDK KIRA Error (NF): {e}")
        return 0

    def GetKiraPositionSize(self, symbol, price, risk_pct=0.01):
        """
        Computes risk-adjusted quantity via KIRA Position Sizer Service.
        """
        import requests
        import uuid
        try:
            # Prepare Request payload
            payload = {
                "request_id": str(uuid.uuid4()),
                "symbol": symbol,
                "strategy_id": getattr(self, 'Name', 'KiraIntegratedStrategy'),
                "signal_type": "MOMENTUM",
                "direction": "BUY",
                "entry_price": float(price),
                "confidence_score": self.GetKiraConfidence(symbol),
                "current_equity": float(self.Portfolio.TotalPortfolioValue),
                "timestamp": self.Time.isoformat() if hasattr(self, 'Time') else None
            }

            # Call API Gateway
            # Note: We use the internal service name 'api_gateway' as seen in Docker Compose
            url = "http://api_gateway:8000/api/v1/kira/position-sizer/size"
            resp = requests.post(url, json=payload, timeout=2)
            
            if resp.status_code == 200:
                data = resp.json()
                return data.get("shares", 0)
            else:
                self.Debug(f"Position Sizer API Error: {resp.status_code} - {resp.text}")
        
        except Exception as e:
            self.Debug(f"SDK Position Sizer Error: {e}")
        
        # Fallback to zero to avoid unmanaged risk if service is down
        return 0


    def Debug(self, message):
        """Send a debug message to the console/log."""
        if getattr(self, '_turbo_mode', False):
            return
        self._logger.info(f"DEBUG: {message}")

    def Log(self, message):
        """Send a log message."""
        if getattr(self, '_turbo_mode', False):
            return
        self._logger.info(f"LOG: {message}")
