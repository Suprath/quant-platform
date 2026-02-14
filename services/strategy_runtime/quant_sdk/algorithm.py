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

class QCAlgorithm(ABC):
    """
    Base class for all user algorithms.
    Mirroring QuantConnect's API structure.
    """
    def __init__(self, engine=None):
        self.Engine = engine
        self.Portfolio = {} # Symbol -> Position Object
        self.Time = datetime.now()
        self.IsWarmingUp = False
        self._logger = logging.getLogger("UserAlgorithm")

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

    def Debug(self, message):
        """Send a debug message to the console/log."""
        self._logger.info(f"DEBUG: {message}")

    def Log(self, message):
        """Send a log message."""
        self._logger.info(f"LOG: {message}")
