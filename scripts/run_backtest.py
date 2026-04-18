#!/usr/bin/env python3
"""Run a backtest for a strategy against a CSV data file."""
import argparse
import importlib
from src.data.loader import load_csv
from src.backtest.engine import run_backtest

STRATEGY_MAP = {
    "supertrend": ("src.strategies.supertrend", "SupertrendStrategy"),
}


def main():
    p = argparse.ArgumentParser(description="Run strategy backtest")
    p.add_argument("--data", required=True, help="Path to CSV file in data/csv/")
    p.add_argument("--strategy", required=True, choices=list(STRATEGY_MAP), help="Strategy name")
    args = p.parse_args()

    module_path, class_name = STRATEGY_MAP[args.strategy]
    module = importlib.import_module(module_path)
    strategy = getattr(module, class_name)()

    df = load_csv(args.data)
    print(f"Loaded {len(df):,} bars from {args.data}")

    metrics, _ = run_backtest(strategy, df)
    print("\n=== Backtest Results ===")
    print(metrics)


if __name__ == "__main__":
    main()
