import pandas as pd
from datetime import date, timedelta
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "csv"
INTERVALS = ["1h", "4h", "1d"]


def fetch_stock(symbol: str, interval: str, start: str, end: str) -> pd.DataFrame:
    import yfinance as yf

    # yfinance has no 4h timeframe — fetch 1h and resample
    fetch_interval = "1h" if interval == "4h" else interval

    # yfinance end is exclusive; for intraday add 1 day so today's bars are included
    fetch_end = end
    if fetch_interval == "1h":
        fetch_end = (date.fromisoformat(end) + timedelta(days=1)).isoformat()

    raw = yf.download(symbol, start=start, end=fetch_end, interval=fetch_interval,
                      auto_adjust=True, progress=False)
    raw = raw.reset_index()

    # Flatten MultiIndex columns e.g. ("Open", "AAPL") -> "open"
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = [col[0].lower() for col in raw.columns]
    else:
        raw.columns = [c.lower() for c in raw.columns]

    # Intraday uses "datetime"; daily uses "date"
    time_col = "datetime" if "datetime" in raw.columns else "date"
    ts = pd.to_datetime(raw[time_col], utc=True)
    epoch = pd.Timestamp("1970-01-01", tz="UTC")
    raw["timestamp"] = ((ts - epoch).dt.total_seconds() * 1000).astype("int64")

    df = raw[["timestamp", "open", "high", "low", "close", "volume"]].copy()
    df = df.drop_duplicates("timestamp").reset_index(drop=True)

    if interval == "4h":
        df = _resample_4h(df)

    return df


def _resample_4h(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.index = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    resampled = df[["open", "high", "low", "close", "volume"]].resample("4h").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
    ).dropna(subset=["open"])
    # Index dtype is datetime64[ms, UTC] after resample — astype int64 yields ms directly
    resampled["timestamp"] = resampled.index.astype("int64")
    return resampled.reset_index(drop=True)[["timestamp", "open", "high", "low", "close", "volume"]]


def fetch_all_intervals(symbol: str, start: str, end: str) -> dict[str, pd.DataFrame]:
    """Fetch 1h, 4h, and 1d data for a symbol. Returns {interval: DataFrame}."""
    return {iv: fetch_stock(symbol, iv, start, end) for iv in INTERVALS}


def save_data(df: pd.DataFrame, symbol: str, interval: str, start: str, end: str) -> Path:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    filename = DATA_DIR / f"{symbol}_{interval}_{start}_{end}.csv"
    df.to_csv(filename, index=False)
    return filename
