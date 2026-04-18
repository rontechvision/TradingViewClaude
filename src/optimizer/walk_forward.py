"""
Walk-forward validation: split data into IS + OOS and compare metrics.

Usage
-----
from src.optimizer.walk_forward import walk_forward
result = walk_forward(SupertrendStrategy, best_params, df)
"""

from typing import Type

import pandas as pd

from src.strategies.base import BaseStrategy
from src.backtest.engine import run_backtest


def walk_forward(
    strategy_class: Type[BaseStrategy],
    best_params: dict,
    df: pd.DataFrame,
    is_pct: float = 0.8,
) -> dict:
    """Validate best_params on out-of-sample slice (last 20%).

    Parameters
    ----------
    strategy_class : Type[BaseStrategy]
        The strategy class to instantiate.
    best_params : dict
        Parameter dictionary to validate (from grid search).
    df : pd.DataFrame
        Full OHLCV dataset (IS + OOS combined).
    is_pct : float
        Fraction of data used as in-sample (default 0.8).

    Returns
    -------
    dict
        Keys: ``is_metrics``, ``oos_metrics``, ``passed``, ``is_rows``, ``oos_rows``.

    Anti-overfitting rules
    ----------------------
    * ``passed = True``  iff  OOS profit_factor >= 1.2  AND  IS profit_factor < 3.0
    * A strategy with IS PF > 3.0 is flagged as likely overfit regardless of OOS.
    """
    split = int(len(df) * is_pct)
    df_is = df.iloc[:split].copy()
    df_oos = df.iloc[split:].copy()

    strategy_is = strategy_class(**best_params)
    is_metrics, _ = run_backtest(strategy_is, df_is)

    strategy_oos = strategy_class(**best_params)
    oos_metrics, _ = run_backtest(strategy_oos, df_oos)

    oos_pf = oos_metrics.profit_factor
    is_pf = is_metrics.profit_factor

    passed = (oos_pf >= 1.2) and (is_pf < 3.0)

    return {
        "params": best_params,
        "is_metrics": is_metrics,
        "oos_metrics": oos_metrics,
        "is_rows": len(df_is),
        "oos_rows": len(df_oos),
        "passed": passed,
    }
