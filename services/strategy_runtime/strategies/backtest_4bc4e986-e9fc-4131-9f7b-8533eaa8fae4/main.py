from quant_sdk.algorithm import QCAlgorithm
from collections import deque

class AdaptiveTrendRider(QCAlgorithm):
    """
    Concentrated trend-following strategy.
    - Picks top 3 stocks by momentum from the scanner universe
    - Equal-weight allocation (~30% each, leaving 10% cash buffer)
    - Exits when trend reverses (price drops below short-term moving avg)
    - Rotates into new leaders each rebalance
    """

    def Initialize(self):
        self.SetCash(100000)
        self.AddUniverse(self.SelectUniverse)

        # Config
        self.max_positions = 3          # Concentrated: only top 3
        self.allocation_per_stock = 0.30  # 30% each = 90% total, 10% cash buffer
        self.lookback = 10              # 10-bar lookback for trend
        self.exit_lookback = 5          # 5-bar moving avg for exit signal

        # State
        self.price_history = {}         # symbol -> deque of prices
        self.entry_prices = {}          # symbol -> entry price

    def SelectUniverse(self, coarse):
        """Let the scanner handle universe selection."""
        return coarse

    def OnData(self, data):
        # 1. Update price history for all symbols
        for symbol in data.Keys:
            tick = data[symbol]
            price = tick.Price

            if symbol not in self.price_history:
                self.price_history[symbol] = deque(maxlen=self.lookback)
            self.price_history[symbol].append(price)

        # 2. Score all symbols by momentum (% change over lookback)
        scored = []
        for symbol, prices in self.price_history.items():
            if len(prices) < self.lookback:
                continue
            momentum = (prices[-1] - prices[0]) / prices[0]  # Simple return
            scored.append((symbol, momentum, prices[-1]))

        if not scored:
            return

        # 3. Sort by momentum descending — we want the strongest trends
        scored.sort(key=lambda x: x[1], reverse=True)
        top_symbols = [s[0] for s in scored[:self.max_positions] if s[1] > 0]

        # 4. EXIT: Liquidate positions that are no longer in top picks
        #    or whose trend has reversed
        for symbol in list(self.entry_prices.keys()):
            holding = self.Portfolio.get(symbol)
            if not holding or holding.Quantity <= 0:
                if symbol in self.entry_prices:
                    del self.entry_prices[symbol]
                continue

            should_exit = False

            # Not in top picks anymore — rotate out
            if symbol not in top_symbols:
                should_exit = True
                self.Log(f"ROTATE OUT {symbol} (no longer top {self.max_positions})")

            # Trend reversal: price below 5-bar average
            elif symbol in self.price_history and len(self.price_history[symbol]) >= self.exit_lookback:
                prices = list(self.price_history[symbol])
                short_ma = sum(prices[-self.exit_lookback:]) / self.exit_lookback
                current = prices[-1]
                if current < short_ma * 0.995:  # 0.5% below MA = exit
                    should_exit = True
                    self.Log(f"TREND REVERSAL {symbol} @ {current:.2f} < MA({self.exit_lookback})={short_ma:.2f}")

            # Stop loss: -3% from entry
            if symbol in self.entry_prices:
                entry = self.entry_prices[symbol]
                current = self.price_history.get(symbol, deque())
                if current and current[-1] < entry * 0.97:
                    should_exit = True
                    self.Log(f"STOP LOSS {symbol} @ {current[-1]:.2f} (entry: {entry:.2f})")

            if should_exit:
                self.Liquidate(symbol)
                if symbol in self.entry_prices:
                    del self.entry_prices[symbol]

        # 5. ENTER: Buy top symbols we don't already hold
        current_positions = len(self.entry_prices)
        for symbol in top_symbols:
            if current_positions >= self.max_positions:
                break
            if symbol in self.entry_prices:
                continue  # Already holding

            # Allocate
            self.SetHoldings(symbol, self.allocation_per_stock)
            if symbol in self.price_history and len(self.price_history[symbol]) > 0:
                self.entry_prices[symbol] = self.price_history[symbol][-1]
                self.Log(f"BUY {symbol} @ {self.entry_prices[symbol]:.2f} (momentum leader)")
                current_positions += 1