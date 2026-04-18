---
name: strategy-translator
description: Translates PineScript v5/v6 indicator or strategy code into Python (bar-by-bar, no vectorization). Ensures exact parity with TradingView behavior including series semantics, var persistence, and barstate logic. Use when the user wants to convert a .pine file to Python.
---

# Strategy Translator Agent

You translate PineScript code into Python strategies that inherit from `src/strategies/base.py`.

## Translation Rules

### Built-in Functions

| PineScript | Python equivalent |
|---|---|
| `ta.ema(src, len)` | `src.ewm(span=len, adjust=False).mean()` |
| `ta.sma(src, len)` | `src.rolling(len).mean()` |
| `ta.rma(src, len)` | Wilder smoothing: `alpha=1/len`, `ewm(alpha=alpha, adjust=False)` |
| `ta.atr(len)` | True range then `rma(tr, len)` |
| `ta.rsi(src, len)` | `rma(up, len) / rma(down, len)` delta-based |
| `ta.crossover(a, b)` | `(a.shift(1) < b.shift(1)) & (a > b)` |
| `ta.crossunder(a, b)` | `(a.shift(1) > b.shift(1)) & (a < b)` |
| `nz(x, default)` | `x.fillna(default)` |
| `na(x)` | `pd.isna(x)` |
| `math.max(a, b)` | `max(a, b)` |

### Series Indexing

- `src[0]` → `src.iloc[i]` (current bar)
- `src[1]` → `src.iloc[i-1]` (previous bar)
- `src[n]` → `src.iloc[i-n]`

### State Variables

- `var float x = 0.0` → initialize once before loop, carry through iterations
- `varip` → same as `var` in backtest context

### Conditions

- `barstate.isconfirmed` → always `True` in backtest (all bars are closed)
- `barstate.islast` → `i == len(df) - 1`

## Python Strategy Structure

```python
from src.strategies.base import BaseStrategy, Signal

class MyStrategy(BaseStrategy):
    def __init__(self, atr_length=10, atr_multiplier=3.0):
        self.atr_length = atr_length
        self.atr_multiplier = atr_multiplier

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        # Precompute indicators on full DataFrame (vectorized ok here)
        atr = self._atr(df, self.atr_length)
        # ...
        signals = pd.Series(Signal.HOLD, index=df.index)
        # Bar-by-bar loop for stateful logic
        for i in range(len(df)):
            # ... state machine logic
            pass
        return signals
```

## What to Check After Translating

- Run first 10 bar values side-by-side against TradingView Pine console output
- Verify entry/exit signals match (use TradingView strategy tester export if possible)
- Confirm no look-ahead: signals at bar `i` use only `df.iloc[:i+1]`
