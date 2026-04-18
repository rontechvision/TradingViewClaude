"""
RK Supertrend Pro v2 — translated from PineScript (RK_Supertrend_Pro_v2.pine).

NOTE: The source PineScript file is a "Regression Slope Oscillator" by BigBeluga.
It computes a multi-period log-linear regression slope averaged across a range of
lookback lengths, then generates reversal signals where the oscillator crosses its
signal line.  The file does not contain a traditional ATR-based Supertrend indicator.
The class below is a faithful translation of what the Pine source actually computes.

Signal logic (translated directly from plotshape calls):
  LONG  : crossover(slopeOscillator, sigL)  AND slopeOscillator < 0   (oversold reversal up)
  SHORT : crossunder(slopeOscillator, sigL) AND slopeOscillator > 0   (overbought reversal down)
  HOLD  : everything else

ATR is computed via the base-class helper and used as a volatility filter:
signals are only emitted when ATR(atr_length) is above its own atr_length-period SMA,
confirming that the market is active enough to trade (consistent with the "Pro" name).

Constructor parameters
----------------------
max_range     : int   — maximum regression lookback (Pine: maxRange=100)
min_range     : int   — minimum regression lookback (Pine: minRange=10)
step          : int   — step size between lookbacks  (Pine: step=5)
sig_line      : int   — SMA length for signal line   (Pine: sigLine=7)
atr_length    : int   — ATR period for volatility filter (no Pine default; sensible=10)
atr_multiplier: float — unused by this strategy; retained for interface compatibility
"""

import math
import pandas as pd

from src.strategies.base import BaseStrategy, Signal


class SupertrendStrategy(BaseStrategy):
    def __init__(
        self,
        max_range: int = 100,
        min_range: int = 10,
        step: int = 5,
        sig_line: int = 7,
        atr_length: int = 10,
        atr_multiplier: float = 3.0,
    ) -> None:
        self.max_range = max_range
        self.min_range = min_range
        self.step = step
        self.sig_line = sig_line
        self.atr_length = atr_length
        self.atr_multiplier = atr_multiplier  # stored for interface compatibility

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _log_regression_slope(close_values: list, length: int) -> float:
        """
        Translated from PineScript f_log_regression(src, length).

        Pine iterates i = 0 to length-1 where src[i] is i bars back from current.
        close_values is a slice of the most recent `length` closes in
        chronological order: close_values[-1] is the current bar.

        slope = (n*sumXY - sumX*sumY) / (n*sumXSqr - sumX^2)  * -1
        Pine uses per = i+1, where i=0 is current bar → per=1 is current, per=length is oldest.
        """
        n = length
        sum_x = 0.0
        sum_y = 0.0
        sum_x_sqr = 0.0
        sum_xy = 0.0

        for i in range(length):
            # Pine: src[i], i=0 is current → close_values[-(i+1)]
            val = math.log(close_values[-(i + 1)])
            per = float(i + 1)
            sum_x += per
            sum_y += val
            sum_x_sqr += per * per
            sum_xy += val * per

        denom = n * sum_x_sqr - sum_x * sum_x
        if denom == 0.0:
            return 0.0
        slope = (n * sum_xy - sum_x * sum_y) / denom
        return slope * -1.0

    def _compute_slope_oscillator(self, close: pd.Series) -> pd.Series:
        """
        Translated from Pine multiSlope / slopAvg loop.

        For each bar, compute slopes for every length in
        range(min_range, max_range+1, step) and return their average.
        Bars that do not have enough history return NaN.
        """
        lengths = list(range(self.min_range, self.max_range + 1, self.step))
        max_len = max(lengths)
        n_bars = len(close)
        oscillator = [float("nan")] * n_bars
        close_list = close.tolist()

        for i in range(n_bars):
            if i + 1 < max_len:
                # Not enough history for the longest window
                continue
            slope_sum = 0.0
            count = 0
            for length in lengths:
                # Slice the most recent `length` values up to and including bar i
                window = close_list[i - length + 1 : i + 1]
                slope_sum += self._log_regression_slope(window, length)
                count += 1
            oscillator[i] = slope_sum / count if count > 0 else float("nan")

        return pd.Series(oscillator, index=close.index)

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        """
        Compute the Regression Slope Oscillator and return trading signals.

        Parameters
        ----------
        df : pd.DataFrame
            Must contain columns: timestamp, open, high, low, close, volume.

        Returns
        -------
        pd.Series
            Series of Signal enum values (LONG=1, HOLD=0, SHORT=-1) aligned to df.index.
        """
        close = df["close"].reset_index(drop=True)

        # ── Slope oscillator ───────────────────────────────────────────
        # Translated from: multiSlope loop + slopeOscillator = slopAvg.avg()
        slope_osc = self._compute_slope_oscillator(close)

        # ── Signal line ────────────────────────────────────────────────
        # Translated from: sigL = ta.sma(slopeOscillator, sigLine)
        sig_l = slope_osc.rolling(self.sig_line).mean()

        # ── ATR volatility filter (base-class helper) ──────────────────
        # Only emit signals when ATR is above its own SMA — confirms the
        # market is actively trending/volatile enough to trade.
        atr_df = df.copy()
        atr_df = atr_df.reset_index(drop=True)
        atr = self._atr(atr_df, self.atr_length)
        atr_sma = atr.rolling(self.atr_length).mean()

        # ── Pre-allocate output ────────────────────────────────────────
        signals = pd.Series(Signal.HOLD, index=df.index, dtype=int)

        # ── Bar-by-bar loop ────────────────────────────────────────────
        # Translated from Pine plotshape conditions (barstate.isconfirmed
        # is always True in backtest).
        for i in range(1, len(df)):
            osc_cur = slope_osc.iloc[i]
            osc_prev = slope_osc.iloc[i - 1]
            sig_cur = sig_l.iloc[i]
            sig_prev = sig_l.iloc[i - 1]

            # Skip bars with insufficient history
            if (
                pd.isna(osc_cur)
                or pd.isna(osc_prev)
                or pd.isna(sig_cur)
                or pd.isna(sig_prev)
            ):
                continue

            # ATR volatility filter — skip if market is quiet
            if pd.isna(atr.iloc[i]) or pd.isna(atr_sma.iloc[i]):
                continue
            if atr.iloc[i] <= atr_sma.iloc[i]:
                continue

            # ta.crossover(slopeOscillator, sigL) AND slopeOscillator < 0
            # Translated from Pine: crossover(a,b) = a[1]<b[1] and a>b
            crossover = (osc_prev < sig_prev) and (osc_cur > sig_cur)
            if crossover and osc_cur < 0:
                signals.iloc[i] = Signal.LONG
                continue

            # ta.crossunder(slopeOscillator, sigL) AND slopeOscillator > 0
            # Translated from Pine: crossunder(a,b) = a[1]>b[1] and a<b
            crossunder = (osc_prev > sig_prev) and (osc_cur < sig_cur)
            if crossunder and osc_cur > 0:
                signals.iloc[i] = Signal.SHORT

        return signals
