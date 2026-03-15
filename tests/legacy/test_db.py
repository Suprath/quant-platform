import psycopg2
import pandas as pd
conn = psycopg2.connect(host="localhost", port=8812, user="admin", password="quest", database="qdb")
query = """SELECT timestamp, symbol, open, high, low, close, volume FROM ohlc WHERE symbol IN ('NEW_SYMBOL_NOT_IN_DB_77') AND timeframe = '1d' AND timestamp >= to_timestamp('2023-01-01T00:00:00.000000Z', 'yyyy-MM-ddTHH:mm:ss.SSSUUUZ')"""
df = pd.read_sql(query, conn)
print("DF type:", type(df))
print("DF empty:", df.empty)
print("DF len:", len(df))
