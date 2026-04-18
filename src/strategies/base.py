from abc import ABC, abstractmethod
from enum import IntEnum
import pandas as pd


class Signal(IntEnum):
    SHORT = -1
    HOLD = 0
    LONG = 1


class BaseStrategy(ABC):
    @abstractmethod
    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        """Return a Series of Signal values aligned to df.index."""
        ...

    def _atr(self, df: pd.DataFrame, length: int) -> pd.Series:
        high, low, prev_close = df["high"], df["low"], df["close"].shift(1)
        tr = pd.concat([
            high - low,
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ], axis=1).max(axis=1)
        return tr.ewm(alpha=1 / length, adjust=False).mean()
