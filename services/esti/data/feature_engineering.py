"""
Feature Engineering — Technical Indicators & State Vector Construction

Transforms raw OHLC data into a 20-dimensional state vector for ESTIPolicy input.
All operations are vectorised with pandas/numpy for efficiency.
"""

import numpy as np
import pandas as pd
from config import setup_logger, STATE_DIM

logger = setup_logger("esti.data.features")


class FeatureEngineering:
    """
    Compute technical indicators and construct the state vector.

    State Vector (20-dim default):
        [returns, sma20_ratio, sma50_ratio, ema12_ratio,
         volatility_20, rsi_14, macd, macd_signal, macd_hist,
         bb_position, volume_ratio, obv_change,
         high_low_range, close_open_range,
         returns_5d, returns_10d, returns_20d,
         vol_regime, trend_regime, momentum_regime]
    """

    def __init__(self, state_dim: int = STATE_DIM):
        self.state_dim = state_dim
        logger.info(f"🔧 FeatureEngineering initialised | state_dim={state_dim}")

    def compute_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Add all technical indicator columns to the OHLC DataFrame.

        Args:
            df: DataFrame with columns [timestamp, open, high, low, close, volume]

        Returns:
            DataFrame with additional feature columns (NaN rows at start are dropped)
        """
        if len(df) < 50:
            logger.warning(f"⚠️  Only {len(df)} rows — need ≥50 for reliable features")

        df = df.copy()

        # ── Returns ──
        df["returns"] = df["close"].pct_change()
        df["returns_5d"] = df["close"].pct_change(5)
        df["returns_10d"] = df["close"].pct_change(10)
        df["returns_20d"] = df["close"].pct_change(20)

        # ── Moving Averages (ratios to close) ──
        df["sma20"] = df["close"].rolling(20).mean()
        df["sma50"] = df["close"].rolling(50).mean()
        df["ema12"] = df["close"].ewm(span=12, adjust=False).mean()

        df["sma20_ratio"] = df["close"] / df["sma20"] - 1
        df["sma50_ratio"] = df["close"] / df["sma50"] - 1
        df["ema12_ratio"] = df["close"] / df["ema12"] - 1

        # ── Volatility ──
        df["volatility_20"] = df["returns"].rolling(20).std()

        # ── RSI (14-period) ──
        df["rsi_14"] = self._rsi(df["close"], 14) / 100.0  # Normalise to [0, 1]

        # ── MACD (12, 26, 9) ──
        ema12 = df["close"].ewm(span=12, adjust=False).mean()
        ema26 = df["close"].ewm(span=26, adjust=False).mean()
        df["macd"] = (ema12 - ema26) / df["close"]  # Normalise by price
        df["macd_signal"] = df["macd"].ewm(span=9, adjust=False).mean()
        df["macd_hist"] = df["macd"] - df["macd_signal"]

        # ── Bollinger Bands ──
        bb_mid = df["close"].rolling(20).mean()
        bb_std = df["close"].rolling(20).std()
        bb_upper = bb_mid + 2 * bb_std
        bb_lower = bb_mid - 2 * bb_std
        bb_range = bb_upper - bb_lower
        df["bb_position"] = np.where(
            bb_range > 0,
            (df["close"] - bb_lower) / bb_range,
            0.5,
        )

        # ── Volume ──
        df["volume_ratio"] = df["volume"] / df["volume"].rolling(20).mean()
        df["volume_ratio"] = df["volume_ratio"].clip(0, 5)  # Cap outliers

        # ── OBV change ──
        obv_sign = np.sign(df["returns"]).fillna(0)
        df["obv"] = (obv_sign * df["volume"]).cumsum()
        df["obv_change"] = df["obv"].pct_change(5)

        # ── Price range features ──
        df["high_low_range"] = (df["high"] - df["low"]) / df["close"]
        df["close_open_range"] = (df["close"] - df["open"]) / df["close"]

        # ── Regime detection (simple) ──
        vol_mean = df["volatility_20"].rolling(60).mean()
        df["vol_regime"] = np.where(df["volatility_20"] > vol_mean, 1.0, 0.0)

        df["trend_regime"] = np.where(
            df["sma20"] > df["sma50"], 1.0,
            np.where(df["sma20"] < df["sma50"], -1.0, 0.0),
        )

        df["momentum_regime"] = np.where(
            df["rsi_14"] > 0.7, 1.0,
            np.where(df["rsi_14"] < 0.3, -1.0, 0.0),
        )

        # Drop NaN rows from warmup period
        initial_len = len(df)
        df = df.dropna().reset_index(drop=True)

        logger.info(
            f"📐 Features computed | {initial_len} → {len(df)} rows "
            f"(dropped {initial_len - len(df)} warmup rows)"
        )
        return df

    def get_state_vector(self, features_df: pd.DataFrame, idx: int) -> np.ndarray:
        """
        Extract the state vector at a specific row index.

        Returns:
            numpy array of shape (state_dim,)
        """
        feature_cols = [
            "returns", "sma20_ratio", "sma50_ratio", "ema12_ratio",
            "volatility_20", "rsi_14", "macd", "macd_signal", "macd_hist",
            "bb_position", "volume_ratio", "obv_change",
            "high_low_range", "close_open_range",
            "returns_5d", "returns_10d", "returns_20d",
            "vol_regime", "trend_regime", "momentum_regime",
        ]

        row = features_df.iloc[idx]
        state = np.array([row[col] for col in feature_cols[:self.state_dim]], dtype=np.float32)

        # Replace any remaining NaN/inf with 0
        state = np.nan_to_num(state, nan=0.0, posinf=0.0, neginf=0.0)
        return state

    def get_all_state_vectors(self, features_df: pd.DataFrame) -> np.ndarray:
        """
        Extract state vectors for all rows.

        Returns:
            numpy array of shape (n_rows, state_dim)
        """
        feature_cols = [
            "returns", "sma20_ratio", "sma50_ratio", "ema12_ratio",
            "volatility_20", "rsi_14", "macd", "macd_signal", "macd_hist",
            "bb_position", "volume_ratio", "obv_change",
            "high_low_range", "close_open_range",
            "returns_5d", "returns_10d", "returns_20d",
            "vol_regime", "trend_regime", "momentum_regime",
        ]

        cols = feature_cols[:self.state_dim]
        states = features_df[cols].values.astype(np.float32)
        states = np.nan_to_num(states, nan=0.0, posinf=0.0, neginf=0.0)

        logger.debug(f"Extracted {len(states)} state vectors | dim={self.state_dim}")
        return states

    # ──────────────────────────────────────────
    #  Private helpers
    # ──────────────────────────────────────────

    @staticmethod
    def _rsi(prices: pd.Series, period: int = 14) -> pd.Series:
        """Relative Strength Index."""
        delta = prices.diff()
        gain = delta.where(delta > 0, 0.0)
        loss = -delta.where(delta < 0, 0.0)

        avg_gain = gain.rolling(window=period, min_periods=period).mean()
        avg_loss = loss.rolling(window=period, min_periods=period).mean()

        rs = avg_gain / avg_loss.replace(0, np.finfo(float).eps)
        return 100 - (100 / (1 + rs))
