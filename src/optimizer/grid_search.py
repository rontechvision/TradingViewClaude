"""
Grid search over a strategy's parameter space.

Usage
-----
from src.optimizer.grid_search import grid_search
results = grid_search(SupertrendStrategy, param_grid, df)
"""

import itertools
from typing import Type

import pandas as pd

from src.strategies.base import BaseStrategy
from src.backtest.engine import run_backtest


def grid_search(
    strategy_class: Type[BaseStrategy],
    param_grid: dict,
    df: pd.DataFrame,
) -> list[dict]:
    """Run all param combinations on df.

    Parameters
    ----------
    strategy_class : Type[BaseStrategy]
        The strategy class to instantiate for each combination.
    param_grid : dict
        Mapping of parameter name → list of candidate values.
    df : pd.DataFrame
        OHLCV data to backtest on (should be the IS split only).

    Returns
    -------
    list[dict]
        Each entry is ``{"params": {...}, "metrics": BacktestMetrics}``,
        sorted by profit_factor descending.
    """
    keys = list(param_grid.keys())
    values = list(param_grid.values())
    combinations = list(itertools.product(*values))
    total = len(combinations)
    print(f"Grid search: {total} combinations over {len(keys)} parameters")

    results = []

    for idx, combo in enumerate(combinations, start=1):
        params = dict(zip(keys, combo))

        try:
            strategy = strategy_class(**params)
            metrics, _ = run_backtest(strategy, df)
        except Exception as exc:  # noqa: BLE001
            print(f"  [combo {idx}/{total}] FAILED with {exc!r} — params={params}")
            continue

        results.append({"params": params, "metrics": metrics})

        if idx % 10 == 0 or idx == total:
            pf = metrics.profit_factor
            pf_str = f"{pf:.2f}" if pf != float("inf") else "inf"
            print(
                f"  [{idx:>{len(str(total))}}/{total}] "
                f"PF={pf_str}  SR={metrics.sharpe_ratio:.2f}  "
                f"trades={metrics.total_trades}  params={params}"
            )

    # Sort by profit_factor descending (inf last to avoid false positives
    # from zero-loss runs with tiny trade counts).
    def sort_key(r: dict) -> float:
        pf = r["metrics"].profit_factor
        # Treat inf as a large but finite sentinel so it ranks high yet
        # after legitimate high-PF results that have real trade history.
        return pf if pf != float("inf") else 999.0

    results.sort(key=sort_key, reverse=True)
    return results
