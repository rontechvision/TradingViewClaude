# TradingView Backtest Engine

A Python system that fetches OHLCV market data, translates PineScript strategies into Python, and backtests them to optimize parameters.

## Commands

```bash
# Install dependencies
pip install -r requirements.txt

# Fetch market data (saves to data/{SYMBOL}/ — all 3 intervals: 1h, 4h, 1d)
# Supports multiple symbols in one run; removes stale files on success
python scripts/fetch_data.py --symbol BTC/USDT
python scripts/fetch_data.py --symbol BTC/USDT ETH/USDT --start 2024-01-01 --end 2026-04-18

# Run backtest on a strategy
python scripts/run_backtest.py --strategy supertrend --data data/csv/BTC-USD_1h_2025-10-18_2026-04-18.csv

# Optimize strategy parameters (grid search + walk-forward validation)
python scripts/optimize.py --strategy supertrend --data data/csv/BTC-USD_1h_2025-10-18_2026-04-18.csv
```

## Architecture

```
src/
  data/
    fetcher.py      — Binance/ccxt API calls; 4h native (no resampling); absolute DATA_DIR
    loader.py       — load/validate CSV files into DataFrames
  strategies/
    base.py         — BaseStrategy ABC with signal generation interface
    supertrend.py   — Regression Slope Oscillator translated from RK_Supertrend_Pro_v2.pine
  backtest/
    engine.py       — event-driven backtest loop (no look-ahead bias)
    metrics.py      — PnL, Sharpe, max drawdown, win rate, profit factor
  optimizer/
    grid_search.py  — exhaustive grid search over parameter space (IS split only)
    walk_forward.py — single IS/OOS holdout split to detect overfitting

data/{SYMBOL}/      — raw OHLCV files: e.g. data/BTCUSDT/BTCUSDT_1h_..._....csv
results/            — backtest output JSON reports
scripts/            — CLI entry points (thin wrappers around src/)
```

## Key Decisions

- **Binance (via ccxt)** for all data (crypto via `BTC/USDT` format)
- **No external backtest library** (Backtrader/vectorbt) — custom engine gives exact PineScript parity (bar-by-bar, not vectorized) and avoids look-ahead bias
- **CSV as data layer** — avoid re-fetching; versioned by symbol + interval + date range in filename
- **Walk-forward validation** mandatory before claiming a strategy "works" — in-sample optimization + out-of-sample verification
- **4h interval** natively supported by Binance — no resampling needed

## Data File Convention

`data/{SYMBOL}/{SYMBOL}_{INTERVAL}_{START}_{END}.csv`

- `{SYMBOL}` is normalized: `BTC/USDT` → `BTCUSDT`
- Example: `data/BTCUSDT/BTCUSDT_1h_2025-10-22_2026-04-22.csv`

Columns: `timestamp,open,high,low,close,volume` (Unix ms timestamp)

## fetch_data.py Behavior

- Accepts one or more symbols: `--symbol BTC/USDT ETH/USDT`
- Always fetches all three intervals in one run: `1h`, `4h`, `1d`
- For intraday (1h/4h), `end` date is advanced by +1 day internally so today's bars are included
- Daily (`1d`) end is not advanced — Binance does not emit a partial-day bar
- On success, removes stale CSV files in `data/{SYMBOL}/` (different date ranges)

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
- **Overfitting filter**: candidate passes if OOS PF ≥ 1.2 AND IS PF < 3.0

## Workflow

- Always use bar-by-bar loop in engine — never use future data
- After fetching data, inspect CSV head/tail before running backtest
- When optimizing, always reserve last 20% of data as OOS holdout
- Run typecheck after changes: `mypy src/`
- Preferred symbol format for crypto: `BTC/USDT` (Binance format)

## Don'ts

- Don't use `pandas_ta` or `ta-lib` for indicator calculation — implement from scratch to match PineScript exactly
- Don't vectorize the backtest loop — bar-by-bar is intentional
- Don't commit raw API keys — use `.env` file (already in `.gitignore`)
- Don't optimize on the full dataset — always hold out OOS data
- Don't use yfinance — data layer is Binance via ccxt only
