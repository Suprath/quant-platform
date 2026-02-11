"""
Parameter Optimizer Service

Optimizes trading strategy parameters for each stock using:
1. 2-week historical data
2. ATR-based dynamic parameter ranges
3. Sharpe Ratio maximization
"""

import os
import sys
import json
import logging
import itertools
import argparse
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
import requests
import urllib.parse

import pandas as pd
import numpy as np
import psycopg2
from dotenv import load_dotenv

load_dotenv()

# Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("ParameterOptimizer")

# Database config
DB_CONFIG = {
    "host": os.getenv("POSTGRES_HOST", "postgres_metadata"),
    "port": os.getenv("POSTGRES_PORT", "5432"),
    "database": os.getenv("POSTGRES_DB", "quant_platform"),
    "user": os.getenv("POSTGRES_USER", "admin"),
    "password": os.getenv("POSTGRES_PASSWORD", "password123"),  # Match docker-compose
}

QUESTDB_URL = os.getenv("QUESTDB_URL", "http://questdb_tsdb:9000")
UPSTOX_TOKEN = os.getenv("UPSTOX_ACCESS_TOKEN", "")

# Fallback params (1.5:1 Risk/Reward ratio)
FALLBACK_PARAMS = {
    "trailing_stop": 0.002,   # 0.2% (wider stop)
    "profit_target": 0.003,   # 0.3% (1.5:1 R:R)
    "cooldown": 30,           # 30 seconds (fast re-entry)
}


class ParameterOptimizer:
    """Optimizes strategy parameters for a given stock."""

    def __init__(self, symbol: str, lookback_days: int = 14):
        self.symbol = symbol
        self.lookback_days = lookback_days
        self.data: Optional[pd.DataFrame] = None

    def fetch_historical_data(self) -> bool:
        """Fetch 2 weeks of 1-min OHLC data from QuestDB."""
        end_date = datetime.now()
        start_date = end_date - timedelta(days=self.lookback_days)

        query = f"""
        SELECT timestamp, open, high, low, close, volume
        FROM ohlc
        WHERE symbol = '{self.symbol}'
          AND timestamp >= '{start_date.strftime('%Y-%m-%dT00:00:00Z')}'
          AND timestamp <= '{end_date.strftime('%Y-%m-%dT23:59:59Z')}'
        ORDER BY timestamp
        """

        try:
            encoded = urllib.parse.urlencode({"query": query})
            resp = requests.get(f"{QUESTDB_URL}/exec?{encoded}", timeout=30)
            if resp.status_code == 200:
                result = resp.json()
                columns = [c["name"] for c in result.get("columns", [])]
                dataset = result.get("dataset", [])
                if dataset:
                    self.data = pd.DataFrame(dataset, columns=columns)
                    self.data["timestamp"] = pd.to_datetime(self.data["timestamp"])
                    logger.info(f"📊 Fetched {len(self.data)} rows for {self.symbol}")
                    return True
                else:
                    logger.warning(f"⚠️ No data found for {self.symbol}")
                    return False
            else:
                logger.error(f"QuestDB error: {resp.status_code} - {resp.text}")
                return False
        except Exception as e:
            logger.error(f"Failed to fetch data: {e}")
            return False

    def calculate_atr(self, period: int = 14) -> float:
        """Calculate Average True Range as percentage of price."""
        if self.data is None or len(self.data) < period:
            return 0.015  # Default 1.5%

        df = self.data.copy()
        df["tr"] = np.maximum(
            df["high"] - df["low"],
            np.maximum(
                abs(df["high"] - df["close"].shift(1)),
                abs(df["low"] - df["close"].shift(1))
            )
        )
        atr = df["tr"].tail(period * 375).mean()  # 375 = 1 day of minute bars
        avg_price = df["close"].tail(period * 375).mean()
        return atr / avg_price if avg_price > 0 else 0.015

    def generate_param_grid(self, atr_pct: float) -> Dict[str, List[float]]:
        """Generate parameter grid based on stock's ATR."""
        # Clamp ATR to reasonable bounds
        atr_pct = max(0.005, min(atr_pct, 0.03))  # 0.5% to 3%

        return {
            "trailing_stop": [atr_pct * 0.3, atr_pct * 0.5, atr_pct * 0.8],
            "profit_target": [atr_pct * 0.5, atr_pct * 1.0, atr_pct * 1.5],
            "cooldown": [30, 60, 120],
        }

    def run_mini_backtest(
        self, trailing_stop: float, profit_target: float, cooldown: int
    ) -> Tuple[float, int, List[float]]:
        """
        Run a simplified backtest with given parameters.
        Returns: (total_pnl, trade_count, pnl_list)
        """
        if self.data is None or len(self.data) < 100:
            return 0.0, 0, []

        df = self.data.copy()
        df["vwap"] = (df["close"] * df["volume"]).cumsum() / df["volume"].cumsum()

        trades = []
        position = None
        last_exit_idx = -999

        for i in range(20, len(df)):
            row = df.iloc[i]
            prev = df.iloc[i - 1]

            # Skip if in cooldown
            if i - last_exit_idx < cooldown // 60:  # Convert seconds to minutes
                continue

            if position is None:
                # Entry: VWAP crossover
                if prev["close"] <= row["vwap"] and row["close"] > row["vwap"]:
                    position = {
                        "type": "LONG",
                        "entry": row["close"],
                        "entry_idx": i,
                        "peak": row["close"],
                    }
                elif prev["close"] >= row["vwap"] and row["close"] < row["vwap"]:
                    position = {
                        "type": "SHORT",
                        "entry": row["close"],
                        "entry_idx": i,
                        "trough": row["close"],
                    }
            else:
                # Exit logic
                if position["type"] == "LONG":
                    position["peak"] = max(position["peak"], row["high"])
                    trailing_stop_price = position["peak"] * (1 - trailing_stop)
                    target_price = position["entry"] * (1 + profit_target)

                    if row["low"] <= trailing_stop_price:
                        # LONG EXIT: Stop Loss
                        exit_price = trailing_stop_price
                        # PnL = (Exit - Entry) / Entry - Costs
                        raw_pnl = (exit_price - position["entry"]) / position["entry"]
                        # Cost: 0.05% on Entry + 0.05% on Exit (approx 0.1% total)
                        net_pnl = raw_pnl - 0.001 
                        trades.append(net_pnl)
                        position = None
                        last_exit_idx = i
                    elif row["high"] >= target_price:
                        # LONG EXIT: Target
                        # When hitting target, we get the target price
                        raw_pnl = profit_target
                        net_pnl = raw_pnl - 0.001
                        trades.append(net_pnl)
                        position = None
                        last_exit_idx = i

                elif position["type"] == "SHORT":
                    position["trough"] = min(position["trough"], row["low"])
                    trailing_stop_price = position["trough"] * (1 + trailing_stop)
                    target_price = position["entry"] * (1 - profit_target)

                    if row["high"] >= trailing_stop_price:
                        # SHORT EXIT: Stop Loss
                        exit_price = trailing_stop_price
                        raw_pnl = (position["entry"] - exit_price) / position["entry"]
                        net_pnl = raw_pnl - 0.001
                        trades.append(net_pnl)
                        position = None
                        last_exit_idx = i
                    elif row["low"] <= target_price:
                        # SHORT EXIT: Target
                        raw_pnl = profit_target
                        net_pnl = raw_pnl - 0.001
                        trades.append(net_pnl)
                        position = None
                        last_exit_idx = i

        total_pnl = sum(trades)
        return total_pnl, len(trades), trades

    def calculate_sharpe(self, pnl_list: List[float]) -> float:
        """Calculate Sharpe Ratio from list of trade returns."""
        if len(pnl_list) < 3:
            return -999.0

        returns = np.array(pnl_list)
        mean_return = np.mean(returns)
        std_return = np.std(returns)

        if std_return == 0:
            return 0.0

        # Annualized Sharpe (assuming ~250 trading days)
        sharpe = (mean_return / std_return) * np.sqrt(250)
        return sharpe

    def optimize(self) -> Dict:
        """Run full optimization and return best params."""
        if not self.fetch_historical_data():
            logger.warning(f"⚠️ Using fallback params for {self.symbol}")
            return FALLBACK_PARAMS.copy()

        atr_pct = self.calculate_atr()
        logger.info(f"📈 {self.symbol} ATR: {atr_pct*100:.2f}%")

        grid = self.generate_param_grid(atr_pct)
        logger.info(f"🔢 Testing {len(list(itertools.product(*grid.values())))} param combinations")

        best_sharpe = -999.0
        best_params = FALLBACK_PARAMS.copy()
        best_stats = {"pnl": 0, "trades": 0}

        for ts, pt, cd in itertools.product(
            grid["trailing_stop"], grid["profit_target"], grid["cooldown"]
        ):
            total_pnl, trade_count, pnl_list = self.run_mini_backtest(ts, pt, cd)
            sharpe = self.calculate_sharpe(pnl_list)

            if sharpe > best_sharpe:
                best_sharpe = sharpe
                best_params = {
                    "trailing_stop": round(ts, 5),
                    "profit_target": round(pt, 5),
                    "cooldown": cd,
                }
                best_stats = {"pnl": total_pnl, "trades": trade_count}

        if best_sharpe > 0:
            logger.info(
                f"✅ Best params: TS={best_params['trailing_stop']*100:.2f}%, "
                f"PT={best_params['profit_target']*100:.2f}%, CD={best_params['cooldown']}s | "
                f"Sharpe={best_sharpe:.2f} | Trades={best_stats['trades']} | P&L={best_stats['pnl']*100:.2f}%"
            )
            return {**best_params, "sharpe_ratio": round(best_sharpe, 4)}
        else:
            logger.warning(f"⚠️ No profitable config found. Using defensive params.")
            return {**FALLBACK_PARAMS, "sharpe_ratio": 0.0}

    def save_to_db(self, params: Dict) -> bool:
        """Save optimized params to Postgres."""
        try:
            conn = psycopg2.connect(**DB_CONFIG)
            cur = conn.cursor()

            cur.execute("""
                INSERT INTO optimized_params (symbol, trailing_stop, profit_target, cooldown_seconds, sharpe_ratio, optimized_at)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (symbol) DO UPDATE SET
                    trailing_stop = EXCLUDED.trailing_stop,
                    profit_target = EXCLUDED.profit_target,
                    cooldown_seconds = EXCLUDED.cooldown_seconds,
                    sharpe_ratio = EXCLUDED.sharpe_ratio,
                    optimized_at = EXCLUDED.optimized_at
            """, (
                self.symbol,
                float(params["trailing_stop"]),  # Convert numpy to Python float
                float(params["profit_target"]),  # Convert numpy to Python float
                int(params["cooldown"]),         # Convert to Python int
                float(params.get("sharpe_ratio", 0)),  # Convert numpy to Python float
                datetime.now()
            ))


            conn.commit()
            cur.close()
            conn.close()
            logger.info(f"💾 Saved params for {self.symbol}")
            return True
        except Exception as e:
            logger.error(f"DB Error: {e}")
            return False


def already_optimized_today(symbol: str) -> bool:
    """Check if stock was already optimized today."""
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        cur = conn.cursor()
        cur.execute("""
            SELECT 1 FROM optimized_params
            WHERE symbol = %s AND DATE(optimized_at) = CURRENT_DATE
        """, (symbol,))
        result = cur.fetchone()
        cur.close()
        conn.close()
        return result is not None
    except Exception as e:
        logger.error(f"DB check error: {e}")
        return False


def ensure_schema():
    """Create optimized_params table if not exists."""
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS optimized_params (
                symbol VARCHAR(50) PRIMARY KEY,
                trailing_stop DECIMAL(8,6),
                profit_target DECIMAL(8,6),
                cooldown_seconds INT,
                sharpe_ratio DECIMAL(8,4),
                optimized_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()
        cur.close()
        conn.close()
        logger.info("✅ Schema verified")
    except Exception as e:
        logger.error(f"Schema error: {e}")


def main():
    parser = argparse.ArgumentParser(description="Optimize strategy parameters")
    parser.add_argument("--symbol", required=True, help="Stock symbol to optimize")
    parser.add_argument("--force", action="store_true", help="Force re-optimization")
    parser.add_argument("--lookback", type=int, default=14, help="Lookback days")
    args = parser.parse_args()

    # Ensure DB schema exists
    ensure_schema()

    # Check if already optimized today
    if not args.force and already_optimized_today(args.symbol):
        logger.info(f"⏭️ {args.symbol} already optimized today. Skipping.")
        return

    # Run optimization
    optimizer = ParameterOptimizer(args.symbol, args.lookback)
    params = optimizer.optimize()

    # Save to DB
    optimizer.save_to_db(params)

    # Output for shell script
    print(json.dumps(params))


if __name__ == "__main__":
    main()
