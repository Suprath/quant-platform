import statistics
from collections import deque
from quant_sdk.algorithm import QCAlgorithm

class MomentumScanner(QCAlgorithm):
    """
    Multi-Stock Momentum Strategy
    - Uses AddUniverse to dynamically scan for top momentum stocks
    - Ranks stocks by price momentum (rate of change)
    - Concentrates capital on the strongest 2-3 stocks
    - Uses trailing stop-loss and momentum exit
    """

    def Initialize(self):
        self.SetCash(100000)

        # Enable dynamic stock scanning
        self.AddUniverse(self.SelectStocks)

        # Config
        self.lookback = 15          # Bars for momentum calc
        self.max_positions = 3      # Max concurrent positions
        self.position_size = 0.30   # 30% per position
        self.stop_loss_pct = 0.02   # 2% stop loss
        self.take_profit_pct = 0.04 # 4% take profit (2:1 R/R)

        # State
        self.history = {}       # symbol -> deque of prices
        self.entry_prices = {}  # symbol -> entry price
        self.momentum = {}      # symbol -> momentum score

    def SelectStocks(self, coarse):
        """Scanner picks top stocks — engine handles this automatically."""
        return coarse

    def OnData(self, data):
        for symbol in data.Keys:
            tick = data[symbol]
            price = tick.Price

            # Build price history
            if symbol not in self.history:
                self.history[symbol] = deque(maxlen=self.lookback)
            self.history[symbol].append(price)

            # Need enough history
            if len(self.history[symbol]) < self.lookback:
                continue

            # --- Calculate Momentum Score ---
            prices = list(self.history[symbol])
            roc = (prices[-1] - prices[0]) / prices[0] * 100  # Rate of Change %
            volatility = statistics.stdev(prices) / statistics.mean(prices)  # Normalized vol
            
            # Momentum Score = ROC adjusted for volatility (higher = better)
            # Prefer strong momentum with low volatility
            self.momentum[symbol] = roc / (volatility + 0.001)

            # --- Position Management (Exit Logic) ---
            holding = self.Portfolio.get(symbol)
            qty = holding.Quantity if holding else 0

            if qty > 0 and symbol in self.entry_prices:
                entry = self.entry_prices[symbol]
                pnl_pct = (price - entry) / entry

                # Stop Loss
                if pnl_pct <= -self.stop_loss_pct:
                    self.Liquidate(symbol)
                    self.Log(f"🛑 STOP LOSS {symbol} @ {price:.2f} (Entry: {entry:.2f}, Loss: {pnl_pct*100:.1f}%)")
                    del self.entry_prices[symbol]
                    continue

                # Take Profit
                if pnl_pct >= self.take_profit_pct:
                    self.Liquidate(symbol)
                    self.Log(f"🎯 TAKE PROFIT {symbol} @ {price:.2f} (Entry: {entry:.2f}, Gain: {pnl_pct*100:.1f}%)")
                    del self.entry_prices[symbol]
                    continue

                # Momentum Exit: Close if momentum turns negative
                if roc < 0:
                    self.Liquidate(symbol)
                    self.Log(f"📉 MOMENTUM EXIT {symbol} @ {price:.2f} (ROC: {roc:.2f}%)")
                    if symbol in self.entry_prices:
                        del self.entry_prices[symbol]
                    continue

        # --- Entry Logic: Pick Best Stocks ---
        current_positions = sum(
            1 for s in self.momentum
            if self.Portfolio.get(s) and self.Portfolio[s].Quantity > 0
        )

        if current_positions >= self.max_positions:
            return

        # Rank all symbols by momentum (highest first)
        ranked = sorted(
            self.momentum.items(),
            key=lambda x: x[1],
            reverse=True
        )

        for symbol, score in ranked:
            if current_positions >= self.max_positions:
                break

            # Only enter if momentum is strongly positive
            if score <= 5.0:
                continue

            # Skip if already holding
            holding = self.Portfolio.get(symbol)
            if holding and holding.Quantity > 0:
                continue

            # Need enough data
            if symbol not in self.history or len(self.history[symbol]) < self.lookback:
                continue

            price = self.history[symbol][-1]
            self.SetHoldings(symbol, self.position_size)
            self.entry_prices[symbol] = price
            current_positions += 1
            self.Log(f"🚀 BUY {symbol} @ {price:.2f} (Momentum Score: {score:.1f})")