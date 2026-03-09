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

    def GetExpiries(self, underlying_symbol):
        import requests
        try:
            # Tell the API Gateway what our 'current' date is for historical testing
            current_date_str = self.algorithm.Time.strftime('%Y-%m-%d')
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
                return sorted(expiries)
            return []
        except Exception as e:
            self.algorithm.Debug(f"OptionChainProvider failed to get expiries: {e}")
            return []

    def GetOptionContractList(self, underlying_symbol, expiry_date):
        import requests
        try:
            if isinstance(expiry_date, datetime):
                expiry_str = expiry_date.strftime("%Y-%m-%d")
            else:
                expiry_str = str(expiry_date) # handle date objects
                
            url = f"{self._base_url}/options/chain/{underlying_symbol}?expiry={expiry_str}"
            resp = requests.get(url, timeout=5)
            if resp.status_code == 200:
                return resp.json().get("contracts", [])
            return []
        except Exception as e:
            self.algorithm.Debug(f"OptionChainProvider failed to get chain: {e}")
            return []

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

    @abstractmethod
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
        pass

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

    # --- Trading Methods ---
    def SetHoldings(self, symbol, percentage, liquidate_existing_holdings=False):
        """
        Sets the holdings of a particular symbol to a percentage of total equity.
        """
        if self.Engine:
            # Call the engine's SetHoldings helper directly
            if hasattr(self.Engine, 'SetHoldings'):
                self.Engine.SetHoldings(symbol, percentage)
            else:
                self.Engine.SubmitOrder(symbol, percentage, "PERCENT")

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
