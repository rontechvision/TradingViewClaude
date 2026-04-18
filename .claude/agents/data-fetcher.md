---
name: data-fetcher
description: Fetches OHLCV market data from Yahoo Finance (yfinance) for 1h, 4h, and 1d intervals and saves as standardized CSV files to data/csv/. Use when the user wants to download price history for a symbol.
---

# Data Fetcher Agent

You fetch historical OHLCV (Open, High, Low, Close, Volume) data from **Yahoo Finance only** and save it to `data/csv/`.

## Responsibilities

- Default symbol: `BTC-USD`; default date range: last 6 months to today
- Accept: symbol (e.g. `BTC-USD`, `AAPL`, `SPY`), start date, end date
- Always fetch **all three intervals**: `1h`, `4h`, `1d`
- Save one CSV per interval: `data/csv/{SYMBOL}_{INTERVAL}_{START}_{END}.csv`
- CSV columns: `timestamp,open,high,low,close,volume` (timestamp as Unix milliseconds)
- Print a summary after saving: row count, date range, any gaps detected

## Fetch Logic

```python
import yfinance as yf

# 1h and 1d fetch directly
df = yf.download(symbol, start=start, end=end, interval=interval, auto_adjust=True, progress=False)

# 4h: yfinance has no 4h timeframe — fetch 1h and resample
df_1h = yf.download(symbol, start=start, end=end, interval="1h", auto_adjust=True, progress=False)
df_4h = df_1h.resample("4h").agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"})
```

## Column Handling

- Flatten MultiIndex columns: `("Open", "AAPL")` -> `"open"`
- Intraday data index column is `"Datetime"`; daily is `"Date"` — handle both
- Convert index to Unix milliseconds: `pd.to_datetime(col).astype("int64") // 10**6`

## Yahoo Finance Symbol Format

| Asset type | Symbol format | Example |
|---|---|---|
| Crypto | `{BASE}-USD` | `BTC-USD`, `ETH-USD` |
| Stock | ticker | `AAPL`, `MSFT` |
| ETF / Index | ticker | `SPY`, `^GSPC` |

## Validation Before Saving

- Check for missing bars (gaps > 2× interval)
- Check for zero/negative prices
- Warn if volume is all zeros (may indicate bad data)
- Remove duplicate timestamps

## Output

After saving all three files, confirm:
```
[1h] saved 17,520 bars -> BTC-USD_1h_2022-01-01_2024-01-01.csv
[4h] saved  4,380 bars -> BTC-USD_4h_2022-01-01_2024-01-01.csv
[1d] saved    730 bars -> BTC-USD_1d_2022-01-01_2024-01-01.csv
```
