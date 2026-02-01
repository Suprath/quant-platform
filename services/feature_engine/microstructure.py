class MicrostructureCalculator:
    def __init__(self):
        self.day_high = 0.0
        self.day_low = float('inf')
        self.total_volume = 0

    def process_tick(self, ltp, ltq, depth):
        """
        Calculates Spread, Aggressor, and Day High/Low
        depth format expected: {'buy': [{'price': 100, 'qty': 50}...], 'sell': [...]}
        """
        # 1. Update Session Stats
        if ltp > self.day_high: self.day_high = ltp
        if ltp < self.day_low: self.day_low = ltp
        self.total_volume += ltq

        # 2. Calculate Spread
        # Spread = Best Ask - Best Bid
        spread = 0.0
        best_bid = 0.0
        best_ask = 0.0

        if depth:
            bids = depth.get('buy', [])
            asks = depth.get('sell', [])
            
            if bids and asks:
                best_bid = bids[0].get('price', 0)
                best_ask = asks[0].get('price', 0)
                spread = round(best_ask - best_bid, 2)

        # 3. Determine Aggressor Side
        # If Trade Price >= Ask -> Buyer was aggressive (Bullish)
        # If Trade Price <= Bid -> Seller was aggressive (Bearish)
        aggressor = "NEUTRAL"
        if best_ask > 0 and ltp >= best_ask:
            aggressor = "BUY"
        elif best_bid > 0 and ltp <= best_bid:
            aggressor = "SELL"

        return {
            "day_high": self.day_high,
            "day_low": self.day_low,
            "total_volume": self.total_volume,
            "spread": spread,
            "aggressor": aggressor
        }