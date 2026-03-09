"""
Enhanced Edge Scanner — Comprehensive Pattern & Insight Extraction Engine.

Extracts all possible insights from OHLCV data:
  Module 1: Regime Classification (Uptrend/Downtrend/Range/HighVol/LowVol)
  Module 2: Temporal Patterns (day-of-week, hourly, gap analysis)
  Module 3: Technical Patterns (15+ patterns with forward returns)
  Module 4: Support/Resistance & Key Levels
  Module 5: Volatility & Risk Profile
  Module 6: Behavioral Fingerprint & Trading Recommendations
"""
import pandas as pd
import numpy as np
from scipy import stats as scipy_stats
import ta
import logging

logger = logging.getLogger("EdgeScanner")


class EdgeScanner:
    def __init__(self, pool):
        self.pool = pool

    def get_connection(self):
        return self.pool.getconn()

    def release_connection(self, conn):
        self.pool.putconn(conn)

    # ──────────────────────────────────────────────────────
    # DATA FETCH
    # ──────────────────────────────────────────────────────
    def fetch_data(self, symbols, timeframe, start_date, end_date):
        conn = self.get_connection()
        try:
            if not symbols:
                return pd.DataFrame()
            symbols_str = "', '".join(symbols)
            ts_start = f"{start_date}T00:00:00.000000Z"
            ts_end = f"{end_date}T23:59:59.999999Z"

            query = f"""
                SELECT timestamp, symbol, open, high, low, close, volume 
                FROM ohlc 
                WHERE symbol IN ('{symbols_str}')
                  AND timeframe = '{timeframe}'
                  AND timestamp >= '{ts_start}'::timestamp
                  AND timestamp <= '{ts_end}'::timestamp
                ORDER BY timestamp ASC;
            """
            
            cur = conn.cursor()
            cur.execute(query)
            rows = cur.fetchall()
            cur.close()

            if not rows:
                return pd.DataFrame()

            df = pd.DataFrame(rows, columns=['timestamp', 'symbol', 'open', 'high', 'low', 'close', 'volume'])
            df['timestamp'] = pd.to_datetime(df['timestamp'])
            for col in ['open', 'high', 'low', 'close', 'volume']:
                df[col] = pd.to_numeric(df[col], errors='coerce')
            return df
        except Exception as e:
            logger.error(f"Error fetching data: {e}")
            return pd.DataFrame()
        finally:
            self.release_connection(conn)

    # ──────────────────────────────────────────────────────
    # MODULE 1: REGIME CLASSIFICATION
    # ──────────────────────────────────────────────────────
    def classify_regimes(self, df):
        """Classify each trading day into a market regime."""
        daily = df.groupby([df['timestamp'].dt.date, 'symbol']).agg(
            open=('open', 'first'), high=('high', 'max'),
            low=('low', 'min'), close=('close', 'last'),
            volume=('volume', 'sum')
        ).reset_index()
        daily.rename(columns={'timestamp': 'date'}, inplace=True)
        daily['date'] = pd.to_datetime(daily['date'])
        daily = daily.sort_values(['symbol', 'date'])

        results = []
        for sym, grp in daily.groupby('symbol'):
            g = grp.copy().reset_index(drop=True)
            if len(g) < 20:
                continue

            g['ema20'] = g['close'].ewm(span=20).mean()
            g['ema20_slope'] = g['ema20'].pct_change(5)  # 5-day slope
            g['atr'] = self._calc_atr(g, 14)
            g['atr_pct'] = g['atr'] / g['close']
            g['avg_atr_pct'] = g['atr_pct'].rolling(20).mean()

            regimes = []
            for i, row in g.iterrows():
                slope = row.get('ema20_slope', 0)
                atr_ratio = row['atr_pct'] / row['avg_atr_pct'] if row['avg_atr_pct'] and row['avg_atr_pct'] > 0 else 1.0

                if atr_ratio > 1.3:
                    regime = "High Volatility"
                elif atr_ratio < 0.7:
                    regime = "Low Volatility"
                elif slope and slope > 0.005:
                    regime = "Uptrend"
                elif slope and slope < -0.005:
                    regime = "Downtrend"
                else:
                    regime = "Range-Bound"
                regimes.append(regime)

            g['regime'] = regimes

            # Regime distribution
            dist = g['regime'].value_counts(normalize=True).to_dict()
            dist = {k: round(v * 100, 1) for k, v in dist.items()}

            # Regime transitions
            transitions = {}
            for i in range(1, len(g)):
                prev_r = g.iloc[i-1]['regime']
                curr_r = g.iloc[i]['regime']
                if prev_r not in transitions:
                    transitions[prev_r] = {}
                transitions[prev_r][curr_r] = transitions[prev_r].get(curr_r, 0) + 1

            # Normalize transitions to percentages
            for from_r in transitions:
                total = sum(transitions[from_r].values())
                transitions[from_r] = {k: round(v/total*100, 1) for k, v in transitions[from_r].items()}

            # Per-regime performance
            g['daily_return'] = g['close'].pct_change() * 100
            regime_perf = {}
            for regime_name in g['regime'].unique():
                rg = g[g['regime'] == regime_name]
                regime_perf[regime_name] = {
                    'days': int(len(rg)),
                    'avg_return': round(float(rg['daily_return'].mean()), 3),
                    'total_return': round(float(rg['daily_return'].sum()), 2),
                    'win_rate': round(float((rg['daily_return'] > 0).mean() * 100), 1),
                    'avg_atr_pct': round(float(rg['atr_pct'].mean() * 100), 2)
                }

            # Current regime
            current_regime = g.iloc[-1]['regime'] if len(g) > 0 else "Unknown"

            results.append({
                'symbol': sym,
                'current_regime': current_regime,
                'distribution': dist,
                'transitions': transitions,
                'regime_performance': regime_perf,
                'total_days': int(len(g))
            })

        return results

    # ──────────────────────────────────────────────────────
    # MODULE 2: TEMPORAL PATTERNS
    # ──────────────────────────────────────────────────────
    def analyze_temporal_patterns(self, df):
        """Day-of-week, hour-of-day, gap analysis, week-of-month."""
        results = []

        for sym, grp in df.groupby('symbol'):
            g = grp.copy().sort_values('timestamp').reset_index(drop=True)
            if len(g) < 20:
                continue

            # Daily aggregation
            daily = g.groupby(g['timestamp'].dt.date).agg(
                open=('open', 'first'), high=('high', 'max'),
                low=('low', 'min'), close=('close', 'last'),
                volume=('volume', 'sum')
            ).reset_index()
            daily.rename(columns={'timestamp': 'date'}, inplace=True)
            daily['date'] = pd.to_datetime(daily['date'])
            daily = daily.sort_values('date')
            daily['daily_return'] = daily['close'].pct_change() * 100
            daily['day_of_week'] = daily['date'].dt.dayofweek  # 0=Mon
            daily['week_of_month'] = (daily['date'].dt.day - 1) // 7 + 1

            # Day-of-week analysis
            day_names = {0: 'Monday', 1: 'Tuesday', 2: 'Wednesday', 3: 'Thursday', 4: 'Friday'}
            dow_analysis = {}
            for dow, name in day_names.items():
                d = daily[daily['day_of_week'] == dow]['daily_return'].dropna()
                if len(d) < 2:
                    continue
                dow_analysis[name] = {
                    'avg_return': round(float(d.mean()), 3),
                    'median_return': round(float(d.median()), 3),
                    'win_rate': round(float((d > 0).mean() * 100), 1),
                    'sample_size': int(len(d)),
                    'std_dev': round(float(d.std()), 3),
                    'best_day': round(float(d.max()), 2),
                    'worst_day': round(float(d.min()), 2)
                }

            # Best and worst days
            best_day = max(dow_analysis, key=lambda x: dow_analysis[x]['avg_return']) if dow_analysis else "N/A"
            worst_day = min(dow_analysis, key=lambda x: dow_analysis[x]['avg_return']) if dow_analysis else "N/A"

            # Hourly analysis (only if intraday data available)
            hourly_analysis = {}
            if len(g) > len(daily) * 2:  # More rows than days = intraday data
                g['hour'] = g['timestamp'].dt.hour
                hourly = g.groupby('hour').apply(
                    lambda x: pd.Series({
                        'avg_return': float(x['close'].pct_change().mean() * 100),
                        'volume_pct': float(x['volume'].sum() / g['volume'].sum() * 100) if g['volume'].sum() > 0 else 0
                    })
                )
                for hour, row in hourly.iterrows():
                    hourly_analysis[f"{int(hour):02d}:00"] = {
                        'avg_return': round(row['avg_return'], 4),
                        'volume_share': round(row['volume_pct'], 1)
                    }

            # Gap analysis
            daily['prev_close'] = daily['close'].shift(1)
            daily['gap_pct'] = ((daily['open'] - daily['prev_close']) / daily['prev_close']) * 100
            gaps = daily.dropna(subset=['gap_pct'])
            gap_ups = gaps[gaps['gap_pct'] > 0.3]
            gap_downs = gaps[gaps['gap_pct'] < -0.3]

            gap_fill_rate_up = 0.0
            if len(gap_ups) > 0:
                gap_fills_up = gap_ups[gap_ups['low'] <= gap_ups['prev_close']]
                gap_fill_rate_up = round(len(gap_fills_up) / len(gap_ups) * 100, 1)

            gap_fill_rate_down = 0.0
            if len(gap_downs) > 0:
                gap_fills_down = gap_downs[gap_downs['high'] >= gap_downs['prev_close']]
                gap_fill_rate_down = round(len(gap_fills_down) / len(gap_downs) * 100, 1)

            gap_analysis = {
                'avg_gap_pct': round(float(gaps['gap_pct'].mean()), 3) if len(gaps) > 0 else 0,
                'gap_up_count': int(len(gap_ups)),
                'gap_down_count': int(len(gap_downs)),
                'gap_up_fill_rate': gap_fill_rate_up,
                'gap_down_fill_rate': gap_fill_rate_down,
                'avg_gap_up_size': round(float(gap_ups['gap_pct'].mean()), 2) if len(gap_ups) > 0 else 0,
                'avg_gap_down_size': round(float(gap_downs['gap_pct'].mean()), 2) if len(gap_downs) > 0 else 0
            }

            # Week-of-month
            wom_analysis = {}
            for w in range(1, 6):
                wr = daily[daily['week_of_month'] == w]['daily_return'].dropna()
                if len(wr) >= 2:
                    wom_analysis[f"Week {w}"] = {
                        'avg_return': round(float(wr.mean()), 3),
                        'win_rate': round(float((wr > 0).mean() * 100), 1),
                        'sample_size': int(len(wr))
                    }

            results.append({
                'symbol': sym,
                'day_of_week': dow_analysis,
                'best_day': best_day,
                'worst_day': worst_day,
                'hourly': hourly_analysis,
                'gap_analysis': gap_analysis,
                'week_of_month': wom_analysis
            })

        return results

    # ──────────────────────────────────────────────────────
    # MODULE 3: TECHNICAL PATTERNS (15+ patterns)
    # ──────────────────────────────────────────────────────
    def detect_patterns(self, df):
        """Extended pattern detection — 15+ patterns using OHLCV."""
        all_results = []

        for sym, grp in df.groupby('symbol'):
            g = grp.copy().sort_values('timestamp').reset_index(drop=True)
            if len(g) < 30:
                continue

            daily = g.groupby(g['timestamp'].dt.date).agg(
                open=('open', 'first'), high=('high', 'max'),
                low=('low', 'min'), close=('close', 'last'),
                volume=('volume', 'sum')
            ).reset_index()
            daily.rename(columns={'timestamp': 'date'}, inplace=True)
            daily['date'] = pd.to_datetime(daily['date'])
            daily = daily.sort_values('date').reset_index(drop=True)

            if len(daily) < 25:
                continue

            # Technical indicators
            daily['rsi'] = ta.momentum.rsi(daily['close'], window=14)
            macd_ind = ta.trend.MACD(daily['close'])
            daily['macd'] = macd_ind.macd()
            daily['macd_signal'] = macd_ind.macd_signal()
            bb = ta.volatility.BollingerBands(daily['close'], window=20, window_dev=2)
            daily['bb_upper'] = bb.bollinger_hband()
            daily['bb_lower'] = bb.bollinger_lband()
            daily['bb_mid'] = bb.bollinger_mavg()
            daily['ema9'] = daily['close'].ewm(span=9).mean()
            daily['ema21'] = daily['close'].ewm(span=21).mean()
            daily['ema50'] = daily['close'].ewm(span=50).mean()
            daily['sma20'] = daily['close'].rolling(20).mean()
            daily['vol_sma20'] = daily['volume'].rolling(20).mean()
            daily['daily_return'] = daily['close'].pct_change()
            daily['fwd_1'] = daily['close'].shift(-1) / daily['close'] - 1  # T+1 return
            daily['fwd_3'] = daily['close'].shift(-3) / daily['close'] - 1
            daily['fwd_5'] = daily['close'].shift(-5) / daily['close'] - 1

            prev_close = daily['close'].shift(1)
            prev_open = daily['open'].shift(1)
            prev_high = daily['high'].shift(1)
            prev_low = daily['low'].shift(1)

            patterns = {}

            # 1. Gap Up Fade
            gap_up = daily['open'] > (prev_close * 1.01)
            fade = daily['close'] < daily['open']
            patterns['Gap Up Fade'] = gap_up & fade

            # 2. Gap Down Recovery
            gap_down = daily['open'] < (prev_close * 0.99)
            recovery = daily['close'] > daily['open']
            patterns['Gap Down Recovery'] = gap_down & recovery

            # 3. Consecutive Up Days (3+)
            up_day = daily['close'] > daily['open']
            patterns['3-Day Bull Run'] = up_day & up_day.shift(1) & up_day.shift(2)

            # 4. Consecutive Down Days (3+)
            down_day = daily['close'] < daily['open']
            patterns['3-Day Bear Run'] = down_day & down_day.shift(1) & down_day.shift(2)

            # 5. Inside Bar Breakout
            inside = (daily['high'] < prev_high) & (daily['low'] > prev_low)
            patterns['Inside Bar'] = inside

            # 6. Oversold Bounce (RSI < 30 + green candle)
            patterns['RSI Oversold Bounce'] = (daily['rsi'] < 30) & (daily['close'] > daily['open'])

            # 7. RSI Overbought Fade (RSI > 70 + red candle)
            patterns['RSI Overbought Fade'] = (daily['rsi'] > 70) & (daily['close'] < daily['open'])

            # 8. MACD Bullish Cross
            macd_cross_up = (daily['macd'] > daily['macd_signal']) & (daily['macd'].shift(1) <= daily['macd_signal'].shift(1))
            patterns['MACD Bullish Cross'] = macd_cross_up

            # 9. MACD Bearish Cross
            macd_cross_dn = (daily['macd'] < daily['macd_signal']) & (daily['macd'].shift(1) >= daily['macd_signal'].shift(1))
            patterns['MACD Bearish Cross'] = macd_cross_dn

            # 10. Bollinger Lower Touch (price touches lower band)
            patterns['BB Lower Touch'] = daily['low'] <= daily['bb_lower']

            # 11. Bollinger Upper Touch
            patterns['BB Upper Touch'] = daily['high'] >= daily['bb_upper']

            # 12. EMA 9/21 Golden Cross
            ema_cross_up = (daily['ema9'] > daily['ema21']) & (daily['ema9'].shift(1) <= daily['ema21'].shift(1))
            patterns['EMA 9/21 Cross Up'] = ema_cross_up

            # 13. Volume Breakout (close > 20-SMA with volume > 2x avg)
            vol_breakout = (daily['close'] > daily['sma20']) & (daily['volume'] > daily['vol_sma20'] * 2)
            patterns['High Volume Breakout'] = vol_breakout

            # 14. Volatility Contraction (VCP — 3 decreasing ranges)
            range_today = daily['high'] - daily['low']
            range_1 = prev_high - prev_low
            range_2 = daily['high'].shift(2) - daily['low'].shift(2)
            patterns['Volatility Contraction'] = (range_today < range_1) & (range_1 < range_2) & (daily['close'] > prev_close)

            # 15. Hammer Candle (small body at top, long lower wick)
            body = abs(daily['close'] - daily['open'])
            lower_wick = pd.DataFrame({'oc_min': daily[['open', 'close']].min(axis=1), 'low': daily['low']})
            lower_wick_len = lower_wick['oc_min'] - lower_wick['low']
            patterns['Hammer'] = (lower_wick_len > body * 2) & (body > 0) & (daily['close'] > daily['open'])

            # 16. Engulfing Bullish
            patterns['Bullish Engulfing'] = (
                (prev_close < prev_open) &  # prev was red
                (daily['close'] > daily['open']) &  # today is green
                (daily['close'] > prev_open) &  # today's close > prev open
                (daily['open'] < prev_close)  # today's open < prev close
            )

            # 17. 20-EMA Pullback in Uptrend
            in_uptrend = daily['close'] > daily['ema50']
            touching_ema20 = abs(daily['low'] - daily['sma20']) / daily['sma20'] < 0.01  # within 1%
            patterns['20-EMA Pullback'] = in_uptrend & touching_ema20 & (daily['close'] > daily['open'])

            # Calculate stats for each pattern
            sym_results = []
            for pat_name, mask in patterns.items():
                mask = mask.fillna(False)
                occurrences = int(mask.sum())
                if occurrences == 0:
                    sym_results.append({
                        'pattern': pat_name, 'occurrences': 0,
                        'win_rate': 0, 'avg_return': 0, 'expectancy': 0,
                        'avg_win': 0, 'avg_loss': 0, 'risk_reward': 0,
                        'consistency': 'N/A', 'history': []
                    })
                    continue

                fwd = daily.loc[mask, 'fwd_1'].dropna()
                if len(fwd) == 0:
                    sym_results.append({
                        'pattern': pat_name, 'occurrences': occurrences,
                        'win_rate': 0, 'avg_return': 0, 'expectancy': 0,
                        'avg_win': 0, 'avg_loss': 0, 'risk_reward': 0,
                        'consistency': 'N/A', 'history': []
                    })
                    continue

                wins = fwd[fwd > 0]
                losses = fwd[fwd < 0]
                win_rate = float((fwd > 0).mean() * 100)
                avg_return = float(fwd.mean() * 100)
                avg_win = float(wins.mean() * 100) if len(wins) > 0 else 0
                avg_loss = float(losses.mean() * 100) if len(losses) > 0 else 0
                expectancy = (win_rate/100 * avg_win) - ((100 - win_rate)/100 * abs(avg_loss))
                risk_reward = abs(avg_win / avg_loss) if avg_loss != 0 else 0

                # Consistency: check first half vs second half
                mid = len(daily) // 2
                mask_h1 = mask.iloc[:mid].sum()
                mask_h2 = mask.iloc[mid:].sum()
                consistency = "Both periods" if mask_h1 > 0 and mask_h2 > 0 else "One period only"

                # History
                hist_rows = daily[mask].tail(30)
                history = []
                for _, row in hist_rows.iterrows():
                    history.append({
                        'date': str(row['date'].date()),
                        'close': round(float(row['close']), 2),
                        'return_pct': round(float(row['fwd_1'] * 100), 2) if pd.notna(row['fwd_1']) else 0
                    })

                sym_results.append({
                    'pattern': pat_name,
                    'occurrences': int(len(fwd)),
                    'win_rate': round(win_rate, 1),
                    'avg_return': round(avg_return, 3),
                    'expectancy': round(expectancy, 3),
                    'avg_win': round(avg_win, 3),
                    'avg_loss': round(avg_loss, 3),
                    'risk_reward': round(risk_reward, 2),
                    'consistency': consistency,
                    'history': history
                })

            # Filter: sort by expectancy, keep patterns with ≥ 3 occurrences
            sym_results.sort(key=lambda x: x['expectancy'], reverse=True)
            all_results.append({
                'symbol': sym,
                'patterns': sym_results,
                'total_patterns_detected': sum(1 for p in sym_results if p['occurrences'] >= 3)
            })

        return all_results

    # ──────────────────────────────────────────────────────
    # MODULE 4: SUPPORT/RESISTANCE & KEY LEVELS
    # ──────────────────────────────────────────────────────
    def detect_key_levels(self, df):
        """Auto-detect support/resistance levels from price clusters."""
        results = []

        for sym, grp in df.groupby('symbol'):
            daily = grp.groupby(grp['timestamp'].dt.date).agg(
                open=('open', 'first'), high=('high', 'max'),
                low=('low', 'min'), close=('close', 'last')
            ).reset_index()
            daily.rename(columns={'timestamp': 'date'}, inplace=True)
            daily = daily.sort_values('date').reset_index(drop=True)

            if len(daily) < 10:
                continue

            current_price = float(daily.iloc[-1]['close'])

            # Find pivot highs and lows (local extremes)
            pivots = []
            for i in range(2, len(daily) - 2):
                # Pivot high
                if daily.iloc[i]['high'] > daily.iloc[i-1]['high'] and daily.iloc[i]['high'] > daily.iloc[i-2]['high'] \
                   and daily.iloc[i]['high'] > daily.iloc[i+1]['high'] and daily.iloc[i]['high'] > daily.iloc[i+2]['high']:
                    pivots.append({'price': float(daily.iloc[i]['high']), 'type': 'resistance', 'date': str(daily.iloc[i]['date'])})
                # Pivot low
                if daily.iloc[i]['low'] < daily.iloc[i-1]['low'] and daily.iloc[i]['low'] < daily.iloc[i-2]['low'] \
                   and daily.iloc[i]['low'] < daily.iloc[i+1]['low'] and daily.iloc[i]['low'] < daily.iloc[i+2]['low']:
                    pivots.append({'price': float(daily.iloc[i]['low']), 'type': 'support', 'date': str(daily.iloc[i]['date'])})

            # Cluster nearby pivots (within 1% of each other)
            if not pivots:
                results.append({'symbol': sym, 'levels': [], 'current_price': current_price, 'nearest_support': None, 'nearest_resistance': None})
                continue

            pivots.sort(key=lambda x: x['price'])
            clusters = []
            used = set()
            for i, p in enumerate(pivots):
                if i in used:
                    continue
                cluster = [p]
                used.add(i)
                for j in range(i+1, len(pivots)):
                    if j in used:
                        continue
                    if abs(pivots[j]['price'] - p['price']) / p['price'] < 0.015:  # 1.5% tolerance
                        cluster.append(pivots[j])
                        used.add(j)

                avg_price = np.mean([c['price'] for c in cluster])
                level_type = 'support' if avg_price < current_price else 'resistance'
                clusters.append({
                    'price': round(float(avg_price), 2),
                    'type': level_type,
                    'touches': len(cluster),
                    'strength': 'Strong' if len(cluster) >= 3 else 'Moderate' if len(cluster) >= 2 else 'Weak',
                    'distance_pct': round((avg_price - current_price) / current_price * 100, 2)
                })

            # Sort by touch count
            clusters.sort(key=lambda x: x['touches'], reverse=True)

            # Nearest support and resistance
            supports = [c for c in clusters if c['price'] < current_price]
            resistances = [c for c in clusters if c['price'] >= current_price]
            nearest_support = max(supports, key=lambda x: x['price']) if supports else None
            nearest_resistance = min(resistances, key=lambda x: x['price']) if resistances else None

            results.append({
                'symbol': sym,
                'levels': clusters[:10],  # Top 10 levels
                'current_price': current_price,
                'nearest_support': nearest_support,
                'nearest_resistance': nearest_resistance
            })

        return results

    # ──────────────────────────────────────────────────────
    # MODULE 5: VOLATILITY & RISK PROFILE
    # ──────────────────────────────────────────────────────
    def analyze_volatility(self, df):
        """ATR, historical volatility, drawdown, risk metrics."""
        results = []

        for sym, grp in df.groupby('symbol'):
            daily = grp.groupby(grp['timestamp'].dt.date).agg(
                open=('open', 'first'), high=('high', 'max'),
                low=('low', 'min'), close=('close', 'last'),
                volume=('volume', 'sum')
            ).reset_index()
            daily.rename(columns={'timestamp': 'date'}, inplace=True)
            daily['date'] = pd.to_datetime(daily['date'])
            daily = daily.sort_values('date').reset_index(drop=True)

            if len(daily) < 14:
                continue

            daily['daily_return'] = daily['close'].pct_change()
            daily['atr'] = self._calc_atr(daily, 14)
            daily['atr_pct'] = daily['atr'] / daily['close'] * 100

            # Historical volatility (annualized)
            hist_vol = float(daily['daily_return'].std() * np.sqrt(252) * 100)

            # Drawdown analysis
            cummax = daily['close'].cummax()
            drawdown = (daily['close'] - cummax) / cummax * 100
            max_dd = float(drawdown.min())
            max_dd_date = str(daily.loc[drawdown.idxmin(), 'date'].date()) if len(daily) > 0 else "N/A"

            # Max consecutive down days
            is_down = daily['daily_return'] < 0
            max_consec_down = 0
            current_streak = 0
            for d in is_down:
                if d:
                    current_streak += 1
                    max_consec_down = max(max_consec_down, current_streak)
                else:
                    current_streak = 0

            # Average daily range
            daily['daily_range_pct'] = (daily['high'] - daily['low']) / daily['close'] * 100
            avg_daily_range = float(daily['daily_range_pct'].mean())

            # Volatility trend (is vol expanding or contracting?)
            if len(daily) >= 20:
                recent_atr = float(daily['atr_pct'].tail(5).mean())
                older_atr = float(daily['atr_pct'].tail(20).head(15).mean())
                vol_trend = "Expanding" if recent_atr > older_atr * 1.1 else "Contracting" if recent_atr < older_atr * 0.9 else "Stable"
            else:
                recent_atr = 0
                older_atr = 0
                vol_trend = "N/A"

            # Buy-and-hold return
            total_return = float((daily.iloc[-1]['close'] / daily.iloc[0]['close'] - 1) * 100)

            # Sharpe ratio (annualized, risk-free rate = 0)
            sharpe = 0
            if daily['daily_return'].std() > 0:
                sharpe = float(daily['daily_return'].mean() / daily['daily_return'].std() * np.sqrt(252))

            results.append({
                'symbol': sym,
                'current_atr': round(float(daily['atr'].iloc[-1]), 2) if pd.notna(daily['atr'].iloc[-1]) else 0,
                'current_atr_pct': round(float(daily['atr_pct'].iloc[-1]), 2) if pd.notna(daily['atr_pct'].iloc[-1]) else 0,
                'historical_volatility': round(hist_vol, 2),
                'avg_daily_range_pct': round(avg_daily_range, 2),
                'max_drawdown': round(max_dd, 2),
                'max_drawdown_date': max_dd_date,
                'max_consecutive_down_days': max_consec_down,
                'volatility_trend': vol_trend,
                'total_return': round(total_return, 2),
                'sharpe_ratio': round(sharpe, 2),
                'trading_days': int(len(daily))
            })

        return results

    # ──────────────────────────────────────────────────────
    # MODULE 6: BEHAVIORAL FINGERPRINT
    # ──────────────────────────────────────────────────────
    def generate_fingerprint(self, regimes, temporal, patterns_data, key_levels, volatility):
        """Synthesize all modules into a stock personality profile with trading recommendations."""
        fingerprints = []

        # Index data by symbol
        regime_map = {r['symbol']: r for r in regimes}
        temporal_map = {t['symbol']: t for t in temporal}
        pattern_map = {p['symbol']: p for p in patterns_data}
        level_map = {l['symbol']: l for l in key_levels}
        vol_map = {v['symbol']: v for v in volatility}

        all_symbols = set(regime_map) | set(temporal_map)

        for sym in all_symbols:
            reg = regime_map.get(sym, {})
            temp = temporal_map.get(sym, {})
            pats = pattern_map.get(sym, {})
            lvls = level_map.get(sym, {})
            vol = vol_map.get(sym, {})

            # Determine personality type
            dist = reg.get('distribution', {})
            current_regime = reg.get('current_regime', 'Unknown')

            trend_pct = dist.get('Uptrend', 0) + dist.get('Downtrend', 0)
            range_pct = dist.get('Range-Bound', 0)
            vol_pct = dist.get('High Volatility', 0)

            if trend_pct > 50:
                if dist.get('Uptrend', 0) > dist.get('Downtrend', 0):
                    personality = "Strong Trend Follower — Bullish Bias"
                else:
                    personality = "Strong Trend Follower — Bearish Bias"
            elif range_pct > 40:
                personality = "Mean Reversion Dominant — Range Trader"
            elif vol_pct > 30:
                personality = "Volatile & Erratic — Requires Wide Stops"
            else:
                personality = "Mixed Regime — Adaptive Strategy Needed"

            # Best strategy recommendation
            best_patterns = pats.get('patterns', [])
            top_pattern = None
            for p in best_patterns:
                if p['occurrences'] >= 3 and p['win_rate'] >= 50:
                    top_pattern = p
                    break

            strategy_rec = "Insufficient pattern data for recommendation"
            if top_pattern:
                strategy_rec = f"Primary: Trade '{top_pattern['pattern']}' setups (Win Rate: {top_pattern['win_rate']}%, Expectancy: {top_pattern['expectancy']:.2f}%)"

            # Best trading days
            best_day = temp.get('best_day', 'N/A')
            worst_day = temp.get('worst_day', 'N/A')

            # Gap behavior
            gap = temp.get('gap_analysis', {})
            gap_insight = "N/A"
            if gap.get('gap_up_fill_rate', 0) > 60:
                gap_insight = f"Gap-up fader — {gap['gap_up_fill_rate']}% of up-gaps fill same day. Fade gap-ups."
            elif gap.get('gap_down_fill_rate', 0) > 60:
                gap_insight = f"Gap-down recoverer — {gap['gap_down_fill_rate']}% of down-gaps fill. Buy gap-downs."
            else:
                gap_insight = "Gaps tend to follow through — trade in gap direction."

            # Position sizing
            atr_pct = vol.get('current_atr_pct', 2)
            if atr_pct > 3:
                size_rec = "Small position (5-8% of capital). Very volatile stock."
            elif atr_pct > 2:
                size_rec = "Moderate position (10-12% of capital)."
            else:
                size_rec = "Standard position (15% of capital). Low volatility."

            # Stop loss recommendation
            stop_rec = f"Hard stop: {round(atr_pct * 1.5, 1)}% below entry (1.5x ATR)"

            # Key levels summary
            ns = lvls.get('nearest_support')
            nr = lvls.get('nearest_resistance')
            level_insight = ""
            if ns:
                level_insight += f"Support: ₹{ns['price']} ({ns['distance_pct']:+.1f}%, {ns['strength']})"
            if nr:
                if level_insight:
                    level_insight += " | "
                level_insight += f"Resistance: ₹{nr['price']} ({nr['distance_pct']:+.1f}%, {nr['strength']})"

            fingerprints.append({
                'symbol': sym,
                'personality': personality,
                'current_regime': current_regime,
                'strategy_recommendation': strategy_rec,
                'best_day': best_day,
                'worst_day': worst_day,
                'gap_behavior': gap_insight,
                'position_sizing': size_rec,
                'stop_loss': stop_rec,
                'key_levels': level_insight,
                'total_return': vol.get('total_return', 0),
                'sharpe_ratio': vol.get('sharpe_ratio', 0),
                'max_drawdown': vol.get('max_drawdown', 0),
                'historical_volatility': vol.get('historical_volatility', 0),
                'top_patterns': [p['pattern'] for p in best_patterns[:3] if p['occurrences'] >= 3],
                'actionable_insights': self._generate_insights(reg, temp, vol, lvls, best_patterns)
            })

        return fingerprints

    def _generate_insights(self, reg, temp, vol, lvls, patterns):
        """Generate plain-English actionable insights."""
        insights = []

        # Regime insight
        current = reg.get('current_regime', '')
        if current == 'Uptrend':
            insights.append("📈 Stock is in an UPTREND. Buy pullbacks to 20-EMA. Avoid shorting — 80%+ of shorts fail in uptrends.")
        elif current == 'Downtrend':
            insights.append("📉 Stock is in a DOWNTREND. Avoid longs or wait for base formation. Short rallies to 20-EMA.")
        elif current == 'Range-Bound':
            insights.append("🔄 Stock is RANGE-BOUND. Buy at support, sell at resistance. Use Bollinger Band fades.")
        elif current == 'High Volatility':
            insights.append("⚡ HIGH VOLATILITY regime. Reduce position size by 50%. Use wider stops. Only trade strong setups.")
        elif current == 'Low Volatility':
            insights.append("😴 LOW VOLATILITY — consolidation phase. Prepare for breakout. Place alerts at range boundaries.")

        # Gap insight
        gap = temp.get('gap_analysis', {})
        if gap.get('gap_up_fill_rate', 0) > 70:
            insights.append(f"🔻 Gap-ups fill {gap['gap_up_fill_rate']}% of the time. Consider fading morning gap-ups.")
        if gap.get('gap_down_fill_rate', 0) > 70:
            insights.append(f"🔺 Gap-downs fill {gap['gap_down_fill_rate']}% of the time. Buy gap-down reversals aggressively.")

        # Best day
        best = temp.get('best_day', '')
        worst = temp.get('worst_day', '')
        if best and best != 'N/A':
            insights.append(f"📅 Best day to trade: {best}. Worst: {worst}. Adjust size accordingly.")

        # Volatility
        vol_trend = vol.get('volatility_trend', '')
        if vol_trend == 'Expanding':
            insights.append("📊 Volatility is EXPANDING. Expect larger moves. Widen stops, reduce size.")
        elif vol_trend == 'Contracting':
            insights.append("📊 Volatility is CONTRACTING. Breakout imminent. Set alerts at range boundaries.")

        # Key levels
        ns = lvls.get('nearest_support')
        nr = lvls.get('nearest_resistance')
        if ns and nr:
            range_pct = abs(nr['price'] - ns['price']) / ns['price'] * 100
            insights.append(f"🎯 Trading range: ₹{ns['price']}-₹{nr['price']} ({range_pct:.1f}% range). Buy near ₹{ns['price']}, target ₹{nr['price']}.")

        # Top pattern
        valid = [p for p in patterns if p['occurrences'] >= 3 and p['win_rate'] >= 55]
        if valid:
            p = valid[0]
            insights.append(f"🏆 Highest-edge pattern: '{p['pattern']}' — {p['win_rate']}% win rate across {p['occurrences']} trades. Expectancy: {p['expectancy']:+.2f}% per trade.")

        return insights

    # ──────────────────────────────────────────────────────
    # ORCHESTRATOR — RUN DEEP SCAN
    # ──────────────────────────────────────────────────────
    def run_deep_scan(self, symbols, timeframe, start_date, end_date):
        """Run all 6 modules and return comprehensive analysis."""
        df = self.fetch_data(symbols, timeframe, start_date, end_date)
        if df.empty or len(df) == 0:
            raise ValueError(f"MISSING_DATA: No historical data found for '{symbols}' in the specified range. Backfill required.")

        df = df.sort_values(by=['symbol', 'timestamp'])

        logger.info(f"📊 Deep scan: {len(df)} rows for {df['symbol'].nunique()} symbols")

        regimes = self.classify_regimes(df)
        temporal = self.analyze_temporal_patterns(df)
        patterns = self.detect_patterns(df)
        key_levels = self.detect_key_levels(df)
        volatility = self.analyze_volatility(df)
        fingerprints = self.generate_fingerprint(regimes, temporal, patterns, key_levels, volatility)

        return {
            'summary': fingerprints,
            'regimes': regimes,
            'temporal': temporal,
            'patterns': patterns,
            'key_levels': key_levels,
            'volatility': volatility,
            'meta': {
                'total_rows': len(df),
                'symbols': list(df['symbol'].unique()),
                'date_range': f"{start_date} to {end_date}",
                'timeframe': timeframe
            }
        }

    # ──────────────────────────────────────────────────────
    # BACKWARD-COMPATIBLE BASIC SCAN
    # ──────────────────────────────────────────────────────
    def run_scan(self, symbols, timeframe, start_date, end_date, patterns, forward_returns_bars):
        """Legacy basic scan — kept for backward compatibility."""
        if not symbols or not patterns:
            return []

        df = self.fetch_data(symbols, timeframe, start_date, end_date)
        if df.empty or len(df) == 0:
            raise ValueError(f"MISSING_DATA: No historical data found for '{symbols}' in the specified range. Backfill required.")

        df = df.sort_values(by=['symbol', 'timestamp'])
        signals = self._detect_basic_patterns(df)
        stats = self._calculate_basic_forward_returns(df, signals, forward_returns_bars, patterns)
        stats.sort(key=lambda x: x['win_rate'], reverse=True)
        return stats

    # ──────────────────────────────────────────────────────
    # HELPERS
    # ──────────────────────────────────────────────────────
    @staticmethod
    def _calc_atr(df, period=14):
        """Calculate Average True Range."""
        high = df['high']
        low = df['low']
        prev_close = df['close'].shift(1)
        tr = pd.concat([
            high - low,
            abs(high - prev_close),
            abs(low - prev_close)
        ], axis=1).max(axis=1)
        return tr.rolling(period).mean()

    def _detect_basic_patterns(self, df):
        """Basic 5-pattern detection (legacy)."""
        signals = pd.DataFrame(index=df.index)
        signals['symbol'] = df['symbol']
        signals['timestamp'] = df['timestamp']
        signals['close'] = df['close']

        prev_close = df.groupby('symbol')['close'].shift(1)
        prev_high = df.groupby('symbol')['high'].shift(1)
        prev_low = df.groupby('symbol')['low'].shift(1)
        prev_prev_high = df.groupby('symbol')['high'].shift(2)
        prev_prev_low = df.groupby('symbol')['low'].shift(2)

        signals['gap_up_fade'] = (df['open'] > prev_close * 1.01) & (df['close'] < df['open'])
        up_day = df['close'] > df['open']
        signals['consecutive_up_days'] = up_day & up_day.groupby(df['symbol']).shift(1) & up_day.groupby(df['symbol']).shift(2)
        signals['inside_bar_breakout'] = ((prev_high < prev_prev_high) & (prev_low > prev_prev_low)) & (df['close'] > prev_high)
        signals['oversold_bounce'] = (df['close'] < df.groupby('symbol')['close'].shift(3) * 0.90) & (df['close'] > df['open'])
        range_today = df['high'] - df['low']
        prev_range = prev_high - prev_low
        prev_prev_range = prev_prev_high - prev_prev_low
        signals['volatility_contraction'] = (range_today < prev_range) & (prev_range < prev_prev_range) & (df['close'] > prev_close)

        return signals

    def _calculate_basic_forward_returns(self, df, signals, forward_returns_bars, patterns):
        """Basic forward return calc (legacy)."""
        results = []
        fwd_returns = {}
        for n in forward_returns_bars:
            shifted = df.groupby('symbol')['close'].shift(-n)
            fwd_returns[n] = (shifted - df['close']) / df['close']

        for pattern in patterns:
            if pattern not in signals.columns:
                continue
            mask = signals[pattern] == True
            if not mask.any():
                results.append({'pattern': pattern, 'occurrences': 0, 'win_rate': 0, 'expected_return': 0, 'history': []})
                continue

            base_n = forward_returns_bars[0]
            fwd = fwd_returns[base_n][mask].dropna()
            win_rate = float((fwd > 0).mean() * 100) if len(fwd) > 0 else 0
            exp_ret = float(fwd.mean() * 100) if len(fwd) > 0 else 0

            hist_rows = signals[mask].copy()
            hist_rows['fwd_return'] = fwd
            hist_rows = hist_rows.dropna(subset=['fwd_return'])
            history = [
                {'timestamp': str(r['timestamp'].date()) if hasattr(r['timestamp'], 'date') else str(r['timestamp']),
                 'symbol': r['symbol'], 'close': float(r['close']),
                 'return_pct': float(r['fwd_return'] * 100)}
                for _, r in hist_rows.iterrows()
            ]

            results.append({
                'pattern': pattern, 'occurrences': len(hist_rows),
                'win_rate': round(win_rate, 2), 'expected_return': round(exp_ret, 2),
                'history': sorted(history, key=lambda x: x['timestamp'], reverse=True)[:50]
            })

        return results
