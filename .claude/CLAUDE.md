# TradingView Backtest Engine

A Python system that fetches OHLCV market data, translates PineScript strategies into Python, and backtests them to optimize parameters.

## Commands

```bash
# Install dependencies
pip install -r requirements.txt

# Fetch market data (saves to data/csv/)
python scripts/fetch_data.py --symbol BTCUSDT --interval 1h --start 2022-01-01 --end 2024-01-01

# Run backtest on a strategy
python scripts/run_backtest.py --symbol BTCUSDT --strategy supertrend --data data/csv/BTCUSDT_1h.csv

# Optimize strategy parameters
python scripts/optimize.py --symbol BTCUSDT --strategy supertrend --data data/csv/BTCUSDT_1h.csv

# Run all backtests
python scripts/run_all.py
```

## Architecture

```
src/
  data/
    fetcher.py      — API calls (ccxt for crypto, yfinance for stocks)
    loader.py       — load/validate CSV files into DataFrames
  strategies/
    base.py         — BaseStrategy ABC with signal generation interface
    supertrend.py   — RK Supertrend Pro v2 translated from PineScript
  backtest/
    engine.py       — event-driven backtest loop (no look-ahead bias)
    metrics.py      — PnL, Sharpe, max drawdown, win rate, profit factor
    report.py       — save results to results/ as JSON + CSV
  optimizer/
    grid_search.py  — exhaustive grid search over parameter space
    walk_forward.py — walk-forward validation to avoid overfitting

data/csv/           — raw OHLCV files: {SYMBOL}_{INTERVAL}.csv
results/            — backtest output JSON reports
scripts/            — CLI entry points (thin wrappers around src/)
```

## Key Decisions

- **ccxt** for crypto data (unified interface across exchanges, supports Binance/Bybit)
- **yfinance** for stocks/ETFs/indices
- **No external backtest library** (Backtrader/vectorbt) — custom engine gives exact PineScript parity (bar-by-bar, not vectorized) and avoids look-ahead bias
- **CSV as data layer** — avoid re-fetching; versioned by symbol + interval + date range in filename
- **Walk-forward validation** mandatory before claiming a strategy "works" — in-sample optimization + out-of-sample verification

## Data File Convention

`data/csv/{SYMBOL}_{INTERVAL}_{START}_{END}.csv`

Columns: `timestamp,open,high,low,close,volume` (Unix ms timestamp)

## Strategy Translation Rules (PineScript → Python)

- `ta.ema(src, length)` → `src.ewm(span=length, adjust=False).mean()`
- `ta.sma(src, length)` → `src.rolling(length).mean()`
- `ta.atr(length)` → compute from OHLC with Wilder smoothing
- `barstate.isconfirmed` → always True in backtest (bar already closed)
- Series indexing `src[1]` → `src.shift(1)`
- `var` variables → initialize before loop, carry state between bars

## Domain Knowledge

- **ATR**: Average True Range — volatility measure used in Supertrend
- **Supertrend**: trend-following indicator using ATR bands; flips direction on band crossover
- **Profit Factor**: gross profit / gross loss — target > 1.5 for viable strategy
- **Sharpe Ratio**: risk-adjusted return — target > 1.0
- **Max Drawdown**: worst peak-to-trough loss — monitor closely
- **Walk-forward**: split data into IS (in-sample optimize) + OOS (out-of-sample verify) windows

## Workflow

- Always use bar-by-bar loop in engine — never use future data
- After fetching data, inspect CSV head/tail before running backtest
- When optimizing, always reserve last 20% of data as OOS holdout
- Run typecheck after changes: `mypy src/`
- Preferred exchange for crypto: **Binance** (highest liquidity, most history)

## Don'ts

- Don't use `pandas_ta` or `ta-lib` for indicator calculation — implement from scratch to match PineScript exactly
- Don't vectorize the backtest loop — bar-by-bar is intentional
- Don't commit raw API keys — use `.env` file (already in `.gitignore`)
- Don't optimize on the full dataset — always hold out OOS data
