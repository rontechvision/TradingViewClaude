import pandas as pd
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parents[2] / "data"
INTERVALS = ["1h", "4h", "1d"]


def _safe_symbol(symbol: str) -> str:
    """BTC/USDT -> BTCUSDT"""
    return symbol.replace("/", "")


def fetch_stock(symbol: str, interval: str, start: str, end: str) -> pd.DataFrame:
    import ccxt

    exchange = ccxt.binance({"enableRateLimit": True})

    since_ms = int(pd.Timestamp(start, tz="UTC").timestamp() * 1000)
    end_ms = int(pd.Timestamp(end, tz="UTC").timestamp() * 1000)

    # Advance end by 1 day for intraday so today's bars are included
    if interval in ("1h", "4h"):
        end_ms = int((pd.Timestamp(end, tz="UTC") + pd.Timedelta(days=1)).timestamp() * 1000)

    all_bars: list = []
    cursor = since_ms

    while cursor < end_ms:
        bars = exchange.fetch_ohlcv(symbol, interval, since=cursor, limit=1000)
        if not bars:
            break
        all_bars.extend(bars)
        last_ts = bars[-1][0]
        if last_ts >= end_ms or last_ts == cursor:
            break
        cursor = last_ts + 1

    df = pd.DataFrame(all_bars, columns=["timestamp", "open", "high", "low", "close", "volume"])
    df = df[df["timestamp"] < end_ms]
    df = df.drop_duplicates("timestamp").reset_index(drop=True)
    return df


def fetch_all_intervals(symbol: str, start: str, end: str) -> dict[str, pd.DataFrame]:
    """Fetch 1h, 4h, and 1d data for a symbol. Returns {interval: DataFrame}."""
    return {iv: fetch_stock(symbol, iv, start, end) for iv in INTERVALS}


def save_data(df: pd.DataFrame, symbol: str, interval: str, start: str, end: str) -> Path:
    sym = _safe_symbol(symbol)
    symbol_dir = DATA_DIR / sym
    symbol_dir.mkdir(parents=True, exist_ok=True)
    filename = symbol_dir / f"{sym}_{interval}_{start}_{end}.csv"
    df.to_csv(filename, index=False)
    return filename


def cleanup_old_files(symbol: str, keep_paths: list[Path]) -> list[Path]:
    """Remove CSV files in data/{SYMBOL}/ that are not in keep_paths. Returns deleted paths."""
    sym = _safe_symbol(symbol)
    symbol_dir = DATA_DIR / sym
    if not symbol_dir.exists():
        return []
    keep_set = {p.resolve() for p in keep_paths}
    deleted = []
    for f in symbol_dir.glob("*.csv"):
        if f.resolve() not in keep_set:
            f.unlink()
            deleted.append(f)
    return deleted
