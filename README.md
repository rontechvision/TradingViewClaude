
*Claude structure from https://github.com/poshan0126/dotclaude/blob/main/README.md


# Run agent Fetch Data

1. Via Claude Code (recommended)
Just tell me in chat: "fetch data" or "fetch data for BTC-USD" and I'll spawn the data-fetcher agent automatically.

2. Via CLI script directly


## Defaults: BTC-USD, last 6 months
python scripts/fetch_data.py --symbol BTC-USD

## Custom symbol/range
python scripts/fetch_data.py --symbol ETH-USD --start 2025-01-01 --end 2026-04-18


# Prompt

## Backtest Strategy Prompt
Witn data\BTCUSDT\*.csv data , backtest this strategy RK_Supertrend_Strategy_v1.pine , on BTCUSD 4H chart and give me the results


## Improve Strategy Prompt

Explore how to improve the RK_Supertrend_Strategy.pine strategy so that it has a much higher Profit with the same or lower Max Drawdown.
Intervals: 1h,4h,1d.
You can combine intervals for different tasks: direction, pullback ...
I general, i'm looking for 1-2 trades in week.
Check its losing trades and avoid them.
Check trades that were missed and try to catch them.
Try to avoid sideways markets.
Try to invest more equity per trade.
Backtest your ideas and give me the best performing one.


Improve Profit Factor by adding SL and TP
