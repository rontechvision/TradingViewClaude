#!/usr/bin/env python3
"""Fetch OHLCV data from Binance for 1h, 4h, and 1d intervals and save to data/{SYMBOL}/."""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import argparse
from datetime import date
from dateutil.relativedelta import relativedelta
from src.data.fetcher import fetch_stock, save_data, cleanup_old_files, INTERVALS


def main():
    default_end = date.today().isoformat()
    default_start = (date.today() - relativedelta(months=6)).isoformat()

    p = argparse.ArgumentParser(description="Fetch market data to CSV (Binance)")
    p.add_argument("--symbol", nargs="+", required=True, help="e.g. BTC/USDT ETH/USDT")
    p.add_argument("--start", default=default_start, help="YYYY-MM-DD (default: 6 months ago)")
    p.add_argument("--end", default=default_end, help="YYYY-MM-DD (default: today)")
    args = p.parse_args()

    for symbol in args.symbol:
        print(f"\nFetching {symbol} from Binance ({args.start} to {args.end})")
        print(f"Intervals: {', '.join(INTERVALS)}")

        saved_paths = []
        success = True

        for interval in INTERVALS:
            print(f"  [{interval}] fetching ...", end=" ", flush=True)
            try:
                df = fetch_stock(symbol, interval, args.start, args.end)
                path = save_data(df, symbol, interval, args.start, args.end)
                saved_paths.append(path)
                print(f"saved {len(df):,} bars -> {path}")
            except Exception as e:
                print(f"FAILED: {e}")
                success = False
                break

        if success and saved_paths:
            deleted = cleanup_old_files(symbol, saved_paths)
            if deleted:
                print(f"  Removed {len(deleted)} old file(s): {[f.name for f in deleted]}")

    print("\nDone.")


if __name__ == "__main__":
    main()
