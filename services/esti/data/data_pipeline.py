"""
DataPipeline — API-Based Data Fetching from Existing Platform

Fetches OHLC data exclusively through the API gateway:
    http://api_gateway:8000/api/v1/market/ohlc

Data is stored in QuestDB as 1-minute candles only.
This pipeline:
    1. Fetches 1m data in paginated chunks (API limit 10,000 rows/request)
    2. Resamples 1m → daily bars for training
    3. Caches processed data
"""

import time
from datetime import datetime, timedelta
import requests
import pandas as pd
import numpy as np
from typing import Optional
from config import setup_logger, API_GATEWAY_URL, DEFAULT_SYMBOLS, SYMBOL_NAMES

logger = setup_logger("esti.data.pipeline")

# API gateway caps at 10,000 rows per request
API_ROW_LIMIT = 10000
# A full NSE trading day has ~375 1-minute candles; fetch ~25 days per chunk
CHUNK_DAYS = 25


class DataPipeline:
    """
    Efficient data ingestion through the existing API gateway.

    Data Flow:
        API Gateway (1m candles) → Paginated Fetch → Resample to Daily → Cache → Feature Engineering

    Caches fetched data in memory to avoid repeated API calls during training epochs.
    """

    def __init__(self, api_base_url: str = API_GATEWAY_URL):
        self.api_base_url = api_base_url
        self._cache: dict[str, pd.DataFrame] = {}
        self._cache_metadata: dict[str, dict] = {}

        logger.info(f"📡 DataPipeline initialised | api_base={api_base_url}")

    # ──────────────────────────────────────────
    #  Single chunk fetch (≤ 10,000 rows)
    # ──────────────────────────────────────────

    def _fetch_chunk(
        self,
        symbol: str,
        start_date: str,
        end_date: str,
    ) -> Optional[pd.DataFrame]:
        """Fetch a single chunk of 1m OHLC data (≤10k rows)."""
        url = f"{self.api_base_url}/api/v1/market/ohlc"
        params = {
            "symbol": symbol,
            "start_date": start_date,
            "end_date": end_date,
            "timeframe": "1m",
            "limit": API_ROW_LIMIT,
        }

        try:
            response = requests.get(url, params=params, timeout=30)
            if response.status_code != 200:
                logger.error(
                    f"❌ Chunk fetch failed | status={response.status_code} "
                    f"| {symbol} | {start_date}→{end_date}"
                )
                return None

            data = response.json()
            candles = data.get("candles", [])
            if not candles:
                return None

            df = pd.DataFrame(candles)
            df["timestamp"] = pd.to_datetime(df["timestamp"])
            return df

        except requests.exceptions.ConnectionError:
            logger.error(
                f"❌ Cannot connect to API gateway at {self.api_base_url} "
                f"— is the platform running?"
            )
            return None
        except Exception as e:
            logger.error(f"❌ Chunk fetch error: {type(e).__name__}: {e}")
            return None

    # ──────────────────────────────────────────
    #  Paginated fetch (handles >10k rows)
    # ──────────────────────────────────────────

    def fetch_ohlc(
        self,
        symbol: str,
        start_date: str,
        end_date: str,
        use_cache: bool = True,
    ) -> Optional[pd.DataFrame]:
        """
        Fetch all 1m OHLC candles for a symbol by paginating in time chunks.
        Then resample to daily bars.

        Args:
            symbol:     Instrument key e.g. "NSE_EQ|INE002A01018"
            start_date: "YYYY-MM-DD"
            end_date:   "YYYY-MM-DD"
            use_cache:  Return cached data if available

        Returns:
            DataFrame with daily OHLC columns [timestamp, open, high, low, close, volume]
        """
        cache_key = f"{symbol}|{start_date}|{end_date}|daily"

        if use_cache and cache_key in self._cache:
            df = self._cache[cache_key]
            logger.debug(
                f"📦 Cache hit: {SYMBOL_NAMES.get(symbol, symbol)} "
                f"| {len(df)} daily bars"
            )
            return df

        name = SYMBOL_NAMES.get(symbol, symbol)
        logger.info(
            f"🌐 Fetching OHLC: {name} | {start_date} → {end_date} | "
            f"paginated 1m → daily resample"
        )

        # Paginate by date chunks
        all_chunks = []
        dt_start = datetime.strptime(start_date, "%Y-%m-%d")
        dt_end = datetime.strptime(end_date, "%Y-%m-%d")
        t0 = time.time()

        current = dt_start
        chunk_num = 0
        while current < dt_end:
            chunk_end = min(current + timedelta(days=CHUNK_DAYS), dt_end)
            chunk_start_str = current.strftime("%Y-%m-%d")
            chunk_end_str = chunk_end.strftime("%Y-%m-%d")

            chunk_df = self._fetch_chunk(symbol, chunk_start_str, chunk_end_str)
            if chunk_df is not None and len(chunk_df) > 0:
                all_chunks.append(chunk_df)
                chunk_num += 1

            current = chunk_end + timedelta(days=1)
            # Small delay between API calls
            time.sleep(0.05)

        elapsed = time.time() - t0

        if not all_chunks:
            logger.warning(
                f"⚠️  No 1m candles returned for {name} | {start_date} → {end_date} | "
                f"Has data been backfilled?"
            )
            return None

        # Combine all chunks
        raw_df = pd.concat(all_chunks, ignore_index=True)
        raw_df = raw_df.drop_duplicates(subset=["timestamp"]).sort_values("timestamp")

        logger.info(
            f"    📥 Fetched {len(raw_df):,} 1m candles in {chunk_num} chunks | {elapsed:.1f}s"
        )

        # Resample 1m → daily
        daily_df = self._resample_to_daily(raw_df)

        if daily_df is None or len(daily_df) == 0:
            logger.warning(f"⚠️  Resampling produced 0 daily bars for {name}")
            return None

        # Cache the daily data
        self._cache[cache_key] = daily_df
        self._cache_metadata[cache_key] = {
            "fetched_at": time.time(),
            "rows": len(daily_df),
            "symbol": symbol,
            "raw_1m_rows": len(raw_df),
        }

        logger.info(
            f"✅ {name}: {len(raw_df):,} 1m candles → {len(daily_df)} daily bars | {elapsed:.1f}s"
        )
        return daily_df

    # ──────────────────────────────────────────
    #  Resample 1m → daily
    # ──────────────────────────────────────────

    def _resample_to_daily(self, df: pd.DataFrame) -> Optional[pd.DataFrame]:
        """Resample 1-minute OHLC data into daily bars."""
        try:
            df = df.copy()
            df = df.set_index("timestamp")

            daily = df.resample("1D").agg({
                "open": "first",
                "high": "max",
                "low": "min",
                "close": "last",
                "volume": "sum",
            }).dropna()

            daily = daily.reset_index()
            daily = daily.rename(columns={"timestamp": "timestamp"})

            # Remove weekends/holidays (no trading data)
            daily = daily[daily["volume"] > 0].reset_index(drop=True)

            logger.debug(f"    Resampled to {len(daily)} daily bars")
            return daily

        except Exception as e:
            logger.error(f"❌ Resample error: {type(e).__name__}: {e}")
            return None

    # ──────────────────────────────────────────
    #  Bulk data fetching for training
    # ──────────────────────────────────────────

    def fetch_training_data(
        self,
        symbols: list[str] = None,
        start_date: str = "2024-01-01",
        end_date: str = "2025-01-01",
        timeframe: str = "1d",
    ) -> dict[str, pd.DataFrame]:
        """
        Fetch OHLC data for multiple symbols — used at training start.
        Note: `timeframe` is accepted for API compat but data is always
        resampled from 1m to daily (only 1m exists in QuestDB).

        Returns:
            {symbol: DataFrame} dict with daily bar DataFrames
        """
        symbols = symbols or DEFAULT_SYMBOLS
        logger.info(
            f"📊 Fetching training data | symbols={len(symbols)} "
            f"| {start_date} → {end_date} | 1m → daily resample"
        )

        results = {}
        for i, symbol in enumerate(symbols, 1):
            name = SYMBOL_NAMES.get(symbol, symbol)
            logger.info(f"    [{i}/{len(symbols)}] Fetching {name}...")
            df = self.fetch_ohlc(symbol, start_date, end_date)
            if df is not None and len(df) > 10:
                results[symbol] = df
            else:
                logger.warning(f"    ⚠️  Skipping {name} — insufficient data")

            # Delay between symbols
            if i < len(symbols):
                time.sleep(0.2)

        logger.info(
            f"📊 Training data ready | {len(results)}/{len(symbols)} symbols loaded "
            f"| total daily bars: {sum(len(df) for df in results.values()):,}"
        )
        return results

    # ──────────────────────────────────────────
    #  Stock discovery (via API gateway)
    # ──────────────────────────────────────────

    def get_available_stocks(self) -> list[dict]:
        """Query the API gateway for available backfilled stocks."""
        url = f"{self.api_base_url}/api/v1/backfill/stocks"
        try:
            response = requests.get(url, timeout=10)
            if response.status_code == 200:
                stocks = response.json()
                logger.info(f"📋 Available stocks: {len(stocks) if isinstance(stocks, list) else 'unknown'}")
                return stocks if isinstance(stocks, list) else []
            else:
                logger.warning(f"⚠️  Could not list stocks: {response.status_code}")
                return []
        except Exception as e:
            logger.error(f"❌ Stock list fetch error: {e}")
            return []

    def trigger_backfill(
        self,
        start_date: str,
        end_date: str,
        stocks: list[str] = None,
    ) -> bool:
        """Trigger a data backfill via the API gateway if training data is missing."""
        url = f"{self.api_base_url}/api/v1/backfill/start"
        payload = {"start_date": start_date, "end_date": end_date}
        if stocks:
            payload["stocks"] = stocks

        logger.info(f"🔄 Triggering backfill | {start_date} → {end_date}")
        try:
            response = requests.post(url, json=payload, timeout=10)
            if response.status_code == 200:
                logger.info(f"✅ Backfill triggered successfully: {response.json()}")
                return True
            else:
                logger.error(f"❌ Backfill trigger failed: {response.status_code} {response.text}")
                return False
        except Exception as e:
            logger.error(f"❌ Backfill trigger error: {e}")
            return False

    # ──────────────────────────────────────────
    #  Cache management
    # ──────────────────────────────────────────

    def clear_cache(self):
        """Clear all cached data."""
        count = len(self._cache)
        self._cache.clear()
        self._cache_metadata.clear()
        logger.info(f"🗑️  Cache cleared ({count} entries)")

    def get_cache_stats(self) -> dict:
        """Return cache statistics."""
        total_rows = sum(len(df) for df in self._cache.values())
        return {
            "cached_datasets": len(self._cache),
            "total_cached_rows": total_rows,
            "symbols": list(set(m["symbol"] for m in self._cache_metadata.values())),
        }
