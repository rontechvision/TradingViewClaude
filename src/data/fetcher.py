import os
import time
import pandas as pd
from datetime import datetime
from pathlib import Path

DATA_DIR = Path("data/csv")


def fetch_crypto(symbol: str, interval: str, start: str, end: str) -> pd.DataFrame:
    import ccxt
    exchange = ccxt.binance()
    since_ms = int(datetime.fromisoformat(start).timestamp() * 1000)
    end_ms = int(datetime.fromisoformat(end).timestamp() * 1000)

    all_ohlcv = []
    while since_ms < end_ms:
        batch = exchange.fetch_ohlcv(symbol, timeframe=interval, since=since_ms, limit=1000)
        if not batch:
            break
        all_ohlcv.extend(batch)
        since_ms = batch[-1][0] + 1
        time.sleep(exchange.rateLimit / 1000)

    df = pd.DataFrame(all_ohlcv, columns=["timestamp", "open", "high", "low", "close", "volume"])
    df = df[df["timestamp"] <= end_ms].drop_duplicates("timestamp").reset_index(drop=True)
    return df


def fetch_stock(symbol: str, interval: str, start: str, end: str) -> pd.DataFrame:
    import yfinance as yf
    raw = yf.download(symbol, start=start, end=end, interval=interval, auto_adjust=True, progress=False)
    raw = raw.reset_index()
    raw.columns = [c.lower() for c in raw.columns]
    raw["timestamp"] = raw["date"].astype("int64") // 10**6
    return raw[["timestamp", "open", "high", "low", "close", "volume"]]


def save_data(df: pd.DataFrame, symbol: str, interval: str, start: str, end: str) -> Path:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    filename = DATA_DIR / f"{symbol}_{interval}_{start}_{end}.csv"
    df.to_csv(filename, index=False)
    return filename
