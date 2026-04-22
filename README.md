
*Claude structure from https://github.com/poshan0126/dotclaude/blob/main/README.md


# Run agent Fetch Data

1. Via Claude Code (recommended)
Just tell me in chat: "fetch data" or "fetch data for BTC-USD" and I'll spawn the data-fetcher agent automatically.

2. Via CLI script directly


## Defaults: BTC-USD, last 6 months
python scripts/fetch_data.py --symbol BTC-USD

## Custom symbol/range
python scripts/fetch_data.py --symbol ETH-USD --start 2025-01-01 --end 2026-04-18


