import numpy as np
import pandas as pd
from dataclasses import dataclass


@dataclass
class BacktestMetrics:
    total_return_pct: float
    profit_factor: float
    sharpe_ratio: float
    max_drawdown_pct: float
    win_rate_pct: float
    total_trades: int
    avg_win_loss_ratio: float

    def __str__(self) -> str:
        return (
            f"Total Return    : {self.total_return_pct:+.1f}%\n"
            f"Profit Factor   : {self.profit_factor:.2f}\n"
            f"Sharpe Ratio    : {self.sharpe_ratio:.2f}\n"
            f"Max Drawdown    : {self.max_drawdown_pct:.1f}%\n"
            f"Win Rate        : {self.win_rate_pct:.1f}%\n"
            f"Total Trades    : {self.total_trades}\n"
            f"Avg Win/Loss    : {self.avg_win_loss_ratio:.2f}"
        )


def compute_metrics(equity_curve: pd.Series, trades: list[dict]) -> BacktestMetrics:
    returns = equity_curve.pct_change().dropna()

    total_return = (equity_curve.iloc[-1] / equity_curve.iloc[0] - 1) * 100

    drawdown = (equity_curve / equity_curve.cummax() - 1) * 100
    max_dd = drawdown.min()

    sharpe = (returns.mean() / returns.std() * np.sqrt(252)) if returns.std() > 0 else 0.0

    wins = [t["pnl"] for t in trades if t["pnl"] > 0]
    losses = [t["pnl"] for t in trades if t["pnl"] < 0]

    gross_profit = sum(wins) if wins else 0
    gross_loss = abs(sum(losses)) if losses else 0
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")

    win_rate = len(wins) / len(trades) * 100 if trades else 0
    avg_win = np.mean(wins) if wins else 0
    avg_loss = abs(np.mean(losses)) if losses else 1
    avg_win_loss = avg_win / avg_loss if avg_loss > 0 else 0

    return BacktestMetrics(
        total_return_pct=total_return,
        profit_factor=profit_factor,
        sharpe_ratio=sharpe,
        max_drawdown_pct=max_dd,
        win_rate_pct=win_rate,
        total_trades=len(trades),
        avg_win_loss_ratio=avg_win_loss,
    )
