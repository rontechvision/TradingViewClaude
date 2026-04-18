#!/usr/bin/env python3
"""Optimize strategy parameters via grid search + walk-forward validation."""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import argparse
import importlib
import json
import math
from datetime import datetime
from pathlib import Path

from src.data.loader import load_csv
from src.optimizer.grid_search import grid_search
from src.optimizer.walk_forward import walk_forward

STRATEGY_MAP = {
    "supertrend": ("src.strategies.supertrend", "SupertrendStrategy"),
}

PARAM_GRIDS = {
    "supertrend": {
        "max_range": [50, 75, 100],
        "min_range": [5, 10, 15],
        "step": [3, 5, 10],
        "sig_line": [5, 7, 10],
        "atr_length": [10, 14, 20],
    },
}

TOP_N = 5
IS_PCT = 0.8


def _pf_str(pf: float) -> str:
    return "inf" if pf == float("inf") else f"{pf:.2f}"


def _metrics_to_dict(m) -> dict:
    return {
        "total_return_pct": round(m.total_return_pct, 4),
        "profit_factor": m.profit_factor if not math.isinf(m.profit_factor) else None,
        "sharpe_ratio": round(m.sharpe_ratio, 4),
        "max_drawdown_pct": round(m.max_drawdown_pct, 4),
        "win_rate_pct": round(m.win_rate_pct, 4),
        "total_trades": m.total_trades,
        "avg_win_loss_ratio": round(m.avg_win_loss_ratio, 4),
    }


def main():
    p = argparse.ArgumentParser(description="Optimize strategy parameters")
    p.add_argument("--data", required=True, help="Path to CSV data file")
    p.add_argument(
        "--strategy",
        required=True,
        choices=list(STRATEGY_MAP),
        help="Strategy name",
    )
    p.add_argument("--output", default="results/", help="Output directory for JSON")
    args = p.parse_args()

    # ── Load strategy class ────────────────────────────────────────────────
    module_path, class_name = STRATEGY_MAP[args.strategy]
    module = importlib.import_module(module_path)
    strategy_class = getattr(module, class_name)

    # ── Load data ──────────────────────────────────────────────────────────
    df = load_csv(args.data)
    print(f"Loaded {len(df):,} bars from {args.data}")

    split = int(len(df) * IS_PCT)
    df_is = df.iloc[:split].copy()
    df_oos = df.iloc[split:].copy()

    is_start = df_is.index[0].strftime("%Y-%m-%d")
    is_end = df_is.index[-1].strftime("%Y-%m-%d")
    oos_start = df_oos.index[0].strftime("%Y-%m-%d")
    oos_end = df_oos.index[-1].strftime("%Y-%m-%d")

    # Derive symbol from filename (best-effort)
    data_stem = Path(args.data).stem  # e.g. BTCUSDT_1h_2022-01-01_2024-01-01
    parts = data_stem.split("_")
    symbol = parts[0] if parts else data_stem

    param_grid = PARAM_GRIDS[args.strategy]

    print(f"\nIS  period : {is_start} -> {is_end}  ({len(df_is):,} bars)")
    print(f"OOS period : {oos_start} -> {oos_end}  ({len(df_oos):,} bars)")
    print(f"\nRunning grid search on IS data ...")

    # ── Grid search on IS split only ───────────────────────────────────────
    gs_results = grid_search(strategy_class, param_grid, df_is)

    if not gs_results:
        print("ERROR: Grid search returned no results.")
        sys.exit(1)

    top_candidates = gs_results[:TOP_N]
    print(f"\nTop-{TOP_N} IS candidates selected. Running walk-forward validation ...")

    # ── Walk-forward validate each top candidate ───────────────────────────
    validated = []
    for rank, candidate in enumerate(top_candidates, start=1):
        params = candidate["params"]
        wf = walk_forward(strategy_class, params, df, is_pct=IS_PCT)
        wf["is_gs_metrics"] = candidate["metrics"]  # IS metrics from grid search
        wf["rank"] = rank
        validated.append(wf)
        status = "PASS" if wf["passed"] else "OVERFIT"
        print(
            f"  Rank {rank}: IS PF={_pf_str(wf['is_metrics'].profit_factor)}  "
            f"OOS PF={_pf_str(wf['oos_metrics'].profit_factor)}  "
            f"IS SR={wf['is_metrics'].sharpe_ratio:.2f}  "
            f"OOS SR={wf['oos_metrics'].sharpe_ratio:.2f}  "
            f"→ {status}  params={params}"
        )

    # ── Print results table ────────────────────────────────────────────────
    print(f"\n{'=' * 80}")
    print("=== Optimization Results ===")
    print(f"{'=' * 80}")
    print(f"Strategy  : {class_name}")
    print(f"Symbol    : {symbol}")
    print(f"IS Period : {is_start} -> {is_end}")
    print(f"OOS Period: {oos_start} -> {oos_end}")
    print()

    # Table header — dynamic column widths based on param names
    param_keys = list(param_grid.keys())
    col_widths = {k: max(len(k), 6) for k in param_keys}

    header_parts = ["Rank"]
    for k in param_keys:
        header_parts.append(k.center(col_widths[k]))
    header_parts += ["IS PF ", "OOS PF", "IS SR ", "OOS SR", "Verdict "]
    header = " | ".join(header_parts)
    separator = "-" * len(header)
    print(header)
    print(separator)

    best_oos_pf = -1.0
    best_candidate = None

    for v in validated:
        params = v["params"]
        is_pf = v["is_metrics"].profit_factor
        oos_pf = v["oos_metrics"].profit_factor
        is_sr = v["is_metrics"].sharpe_ratio
        oos_sr = v["oos_metrics"].sharpe_ratio
        verdict = "PASS   " if v["passed"] else "OVERFIT"

        row_parts = [f"  {v['rank']}  "]
        for k in param_keys:
            val_str = str(params[k]).center(col_widths[k])
            row_parts.append(val_str)
        row_parts += [
            f"{_pf_str(is_pf):>6}",
            f"{_pf_str(oos_pf):>6}",
            f"{is_sr:>6.2f}",
            f"{oos_sr:>6.2f}",
            verdict,
        ]
        print(" | ".join(row_parts))

        if v["passed"] and oos_pf > best_oos_pf:
            best_oos_pf = oos_pf
            best_candidate = v

    print(separator)

    if best_candidate:
        bp = best_candidate["params"]
        param_str = ", ".join(f"{k}={v}" for k, v in bp.items())
        print(f"\nRecommended: {param_str}")
        print(f"  IS  PF={_pf_str(best_candidate['is_metrics'].profit_factor)}"
              f"  SR={best_candidate['is_metrics'].sharpe_ratio:.2f}"
              f"  trades={best_candidate['is_metrics'].total_trades}")
        print(f"  OOS PF={_pf_str(best_candidate['oos_metrics'].profit_factor)}"
              f"  SR={best_candidate['oos_metrics'].sharpe_ratio:.2f}"
              f"  trades={best_candidate['oos_metrics'].total_trades}")
    else:
        print("\nNo candidates passed the walk-forward filter (all overfit).")
        print("Consider loosening param_grid constraints or reviewing the strategy.")

    # ── Save JSON ──────────────────────────────────────────────────────────
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d")
    out_path = output_dir / f"{symbol}_{args.strategy}_optimization_{ts}.json"

    output_data = {
        "strategy": class_name,
        "symbol": symbol,
        "is_period": {"start": is_start, "end": is_end, "rows": len(df_is)},
        "oos_period": {"start": oos_start, "end": oos_end, "rows": len(df_oos)},
        "param_grid": {k: list(v) for k, v in param_grid.items()},
        "top_candidates": [
            {
                "rank": v["rank"],
                "params": v["params"],
                "passed": v["passed"],
                "is_metrics": _metrics_to_dict(v["is_metrics"]),
                "oos_metrics": _metrics_to_dict(v["oos_metrics"]),
            }
            for v in validated
        ],
        "recommended": (
            {
                "params": best_candidate["params"],
                "is_metrics": _metrics_to_dict(best_candidate["is_metrics"]),
                "oos_metrics": _metrics_to_dict(best_candidate["oos_metrics"]),
            }
            if best_candidate
            else None
        ),
    }

    with open(out_path, "w") as f:
        json.dump(output_data, f, indent=2)

    print(f"\nSaved: {out_path.resolve()}")


if __name__ == "__main__":
    main()
