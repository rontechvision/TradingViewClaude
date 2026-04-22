"""
RK - Heikin Ashi RSI Oscillator (HARSI) — translated from
`pinescripts/strategies/RK - Heikin Ashi RSI Oscillator_strategy.pine`.

The Pine source is an indicator. The auto-converted strategy uses the
cleanest OB/OS crossover signal from the indicator design:

  LONG  : ta.crossover(RSI,  i_lower)   — RSI recovers above OS boundary (-20)
  SHORT : ta.crossunder(RSI, i_upper)   — RSI rejects below OB boundary (+20)

Positions auto-reverse on the opposite signal (no stops/TP in this first
version). Backtests assume the crypto 10x isolated-margin convention
(initial capital $1,000, 5% position size => 50% exposure at 10x leverage,
0.05% commission per side, 2-tick slippage) as described in
`.claude/agents/strategy-translator.md`.

Pine `RSI` replicated exactly:
    zrsi     = ta.rsi(src, len) - 50                          # zero-median RSI
    smoothed = na(smoothed[1]) ? zrsi : (smoothed[1]+zrsi)/2  # recursive avg
    RSI      = i_mode ? smoothed : zrsi

`ta.rsi` uses Wilder smoothing (alpha = 1/length, adjust=False).

Constructor parameters
----------------------
len_rsi       : int   — RSI length on source (Pine: i_lenRSI = 7)
smoothed_mode : bool  — apply recursive smoothing (Pine: i_mode = true)
ob_upper      : int   — OB boundary (Pine: i_upper = 20)
os_lower      : int   — OS boundary (Pine: i_lower = -20)
source        : str   — price source: 'ohlc4' (default), 'hlc3', 'close', ...
"""

import pandas as pd

from src.strategies.base import BaseStrategy, Signal


class HARSIStrategy(BaseStrategy):
    def __init__(
        self,
        len_rsi: int = 7,
        smoothed_mode: bool = True,
        ob_upper: int = 20,
        os_lower: int = -20,
        source: str = "ohlc4",
    ) -> None:
        self.len_rsi = len_rsi
        self.smoothed_mode = smoothed_mode
        self.ob_upper = ob_upper
        self.os_lower = os_lower
        self.source = source

    @staticmethod
    def _wilder_rsi(src: pd.Series, length: int) -> pd.Series:
        """Match Pine `ta.rsi` exactly: Wilder-smoothed RSI (alpha = 1/length).

        Edge cases:
          - avg_loss == 0  => RSI = 100 (no downside => fully overbought)
          - avg_gain == 0 AND avg_loss == 0 => treated as 100 too (no movement);
            this is an early-bar-only corner case and does not affect crossovers.
        """
        delta = src.diff()
        gain = delta.clip(lower=0.0)
        loss = (-delta).clip(lower=0.0)
        avg_gain = gain.ewm(alpha=1.0 / length, adjust=False).mean()
        avg_loss = loss.ewm(alpha=1.0 / length, adjust=False).mean()
        rs = avg_gain / avg_loss.replace(0.0, float("nan"))
        rsi = 100.0 - (100.0 / (1.0 + rs))
        rsi = rsi.where(avg_loss != 0.0, 100.0)
        return rsi

    def _source_series(self, df: pd.DataFrame) -> pd.Series:
        if self.source == "ohlc4":
            return (df["open"] + df["high"] + df["low"] + df["close"]) / 4.0
        if self.source == "hlc3":
            return (df["high"] + df["low"] + df["close"]) / 3.0
        if self.source == "hl2":
            return (df["high"] + df["low"]) / 2.0
        return df[self.source]

    def _compute_rsi(self, df: pd.DataFrame) -> pd.Series:
        """Replicates Pine f_rsi(source, lenRSI, mode) including the recursive
        smoothed branch. Returns a Series aligned to df.index.

        The Pine recursion is:
            smoothed := na(smoothed[1]) ? zrsi : (smoothed[1] + zrsi) / 2
        We must walk bar-by-bar because the output at bar `i` feeds bar `i+1`.
        NaN zrsi values (before Wilder RSI is warmed up) are skipped so that
        `prev_smoothed` is only initialized once zrsi becomes non-NaN — this
        matches Pine's `na`-aware seeding of the var.
        """
        src = self._source_series(df)
        zrsi = self._wilder_rsi(src, self.len_rsi) - 50.0

        if not self.smoothed_mode:
            return pd.Series(zrsi.values, index=df.index, dtype=float)

        smoothed = [float("nan")] * len(zrsi)
        prev = float("nan")
        for i, v in enumerate(zrsi.tolist()):
            if pd.isna(v):
                continue
            cur = v if pd.isna(prev) else (prev + v) / 2.0
            smoothed[i] = cur
            prev = cur
        return pd.Series(smoothed, index=df.index, dtype=float)

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        rsi = self._compute_rsi(df)
        signals = pd.Series(Signal.HOLD, index=df.index, dtype=int)

        # Bar-by-bar crossover detection — no look-ahead. Uses rsi at i and i-1
        # only, which both come from data up to bar i.
        for i in range(1, len(df)):
            cur = rsi.iloc[i]
            prev = rsi.iloc[i - 1]
            if pd.isna(cur) or pd.isna(prev):
                continue

            # ta.crossover(RSI, i_lower): prev <= lower AND cur > lower
            if prev <= self.os_lower and cur > self.os_lower:
                signals.iloc[i] = Signal.LONG
                continue

            # ta.crossunder(RSI, i_upper): prev >= upper AND cur < upper
            if prev >= self.ob_upper and cur < self.ob_upper:
                signals.iloc[i] = Signal.SHORT

        return signals
