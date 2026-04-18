#!/usr/bin/env python3
"""Fetch OHLCV data from Binance (crypto) or yfinance (stocks) and save to data/csv/."""
import argparse
from src.data.fetcher import fetch_crypto, fetch_stock, save_data

CRYPTO_SUFFIXES = ("USDT", "BTC", "ETH", "BUSD")


def main():
    p = argparse.ArgumentParser(description="Fetch market data to CSV")
    p.add_argument("--symbol", required=True, help="e.g. BTCUSDT or AAPL")
    p.add_argument("--interval", default="1h", help="e.g. 1m 5m 15m 1h 4h 1d")
    p.add_argument("--start", required=True, help="YYYY-MM-DD")
    p.add_argument("--end", required=True, help="YYYY-MM-DD")
    args = p.parse_args()

    is_crypto = any(args.symbol.upper().endswith(s) for s in CRYPTO_SUFFIXES)
    print(f"Fetching {'crypto' if is_crypto else 'stock'} data for {args.symbol} ({args.interval}) "
          f"{args.start} → {args.end} ...")

    df = fetch_crypto(args.symbol, args.interval, args.start, args.end) if is_crypto \
        else fetch_stock(args.symbol, args.interval, args.start, args.end)

    path = save_data(df, args.symbol, args.interval, args.start, args.end)
    print(f"Saved : {path}")
    print(f"Rows  : {len(df):,}")
    print(f"Range : {df['timestamp'].iloc[0]} → {df['timestamp'].iloc[-1]}")


if __name__ == "__main__":
    main()
