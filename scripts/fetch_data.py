#!/usr/bin/env python3
"""Fetch OHLCV data from Yahoo Finance for 1h, 4h, and 1d intervals and save to data/csv/."""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import argparse
from datetime import date, timedelta
from dateutil.relativedelta import relativedelta
from src.data.fetcher import fetch_stock, save_data, INTERVALS


def main():
    default_end = date.today().isoformat()
    default_start = (date.today() - relativedelta(months=6)).isoformat()

    p = argparse.ArgumentParser(description="Fetch market data to CSV (Yahoo Finance)")
    p.add_argument("--symbol", required=True, help="e.g. BTC-USD, AAPL, SPY")
    p.add_argument("--start", default=default_start, help="YYYY-MM-DD (default: 6 months ago)")
    p.add_argument("--end", default=default_end, help="YYYY-MM-DD (default: today)")
    args = p.parse_args()

    print(f"Fetching {args.symbol} from Yahoo Finance ({args.start} to {args.end})")
    print(f"Intervals: {', '.join(INTERVALS)}\n")

    for interval in INTERVALS:
        print(f"  [{interval}] fetching ...", end=" ", flush=True)
        df = fetch_stock(args.symbol, interval, args.start, args.end)
        path = save_data(df, args.symbol, interval, args.start, args.end)
        print(f"saved {len(df):,} bars -> {path.name}")

    print("\nDone.")


if __name__ == "__main__":
    main()
