import pandas as pd
from src.strategies.base import BaseStrategy, Signal
from src.backtest.metrics import BacktestMetrics, compute_metrics

INITIAL_CAPITAL = 10_000.0
POSITION_SIZE_PCT = 1.0  # 100% of capital per trade


def run_backtest(strategy: BaseStrategy, df: pd.DataFrame) -> tuple[BacktestMetrics, pd.Series]:
    signals = strategy.generate_signals(df)

    capital = INITIAL_CAPITAL
    position = 0.0  # units held (positive = long, negative = short)
    entry_price = 0.0
    equity = []
    trades = []

    for i in range(1, len(df)):
        price_open = df["open"].iloc[i]
        signal = signals.iloc[i - 1]  # signal from previous bar, enter at current open

        # Close existing position on opposite signal
        if position != 0 and signal != Signal(int(position > 0) - int(position < 0)):
            pnl = (price_open - entry_price) * position
            trades.append({"entry": entry_price, "exit": price_open, "pnl": pnl, "size": position})
            capital += pnl
            position = 0.0

        # Open new position
        if position == 0 and signal != Signal.HOLD:
            units = (capital * POSITION_SIZE_PCT) / price_open
            position = units if signal == Signal.LONG else -units
            entry_price = price_open

        # Mark-to-market equity
        unrealized = (df["close"].iloc[i] - entry_price) * position if position != 0 else 0
        equity.append(capital + unrealized)

    equity_curve = pd.Series(equity, index=df.index[1:])
    metrics = compute_metrics(equity_curve, trades)
    return metrics, equity_curve
