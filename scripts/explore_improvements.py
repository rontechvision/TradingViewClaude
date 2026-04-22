#!/usr/bin/env python3
"""
Explore improvements to RK_Supertrend_Strategy_v1.

Variants tested on BTCUSDT 1h, 4h, 1d:
  A  Baseline   — original signals, signal-flip exits only
  B  Stops      — 2×ATR stop-loss + 4×ATR take-profit
  C  ADX        — ADX(14)>20 sideways filter + exit when oscillator crosses 0
  D  Best       — Stops + ADX + zero-cross exit (B+C combined)
  E  MTF        — 4h entries + 1d EMA(50) direction filter + Stops + ADX + zero-cross exit

Improvements address:
  - Losing trades   → ATR stops cut losses early
  - Sideways chop   → ADX filter skips low-trend environments
  - Overstaying     → zero-cross exit locks in reversal gains
  - Contra-trend    → 1d EMA direction filter (MTF)
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import bisect
import math
import numpy as np
import pandas as pd
from pathlib import Path
from dataclasses import dataclass

SYMBOL        = "BTCUSDT"
DATA_DIR      = Path(__file__).resolve().parents[1] / "data"
COMM          = 0.0005          # 0.05% per-side commission (matches Pine strategy)
CAPITAL       = 10_000.0
BARS_PER_WEEK = {"1h": 168, "4h": 42, "1d": 7}
# Annualisation factors for Sharpe (bars per year)
ANNUALIZE     = {"1h": math.sqrt(8_760), "4h": math.sqrt(2_190), "1d": math.sqrt(365)}


# ─────────────────────────────────── DATA ────────────────────────────────────

def load(interval: str) -> pd.DataFrame:
    d = DATA_DIR / SYMBOL
    files = sorted(d.glob(f"{SYMBOL}_{interval}_*.csv"))
    if not files:
        raise FileNotFoundError(f"No {interval} CSV for {SYMBOL} in {d}")
    return pd.read_csv(files[-1]).sort_values("timestamp").reset_index(drop=True)


# ──────────────────────────────── INDICATORS ─────────────────────────────────

def _wilder(s: pd.Series, n: int) -> pd.Series:
    """Wilder smoothing — EMA with alpha=1/n."""
    return s.ewm(alpha=1.0 / n, adjust=False).mean()


def calc_atr(df: pd.DataFrame, n: int = 10) -> pd.Series:
    pc = df["close"].shift(1)
    tr = pd.concat([
        df["high"] - df["low"],
        (df["high"] - pc).abs(),
        (df["low"]  - pc).abs(),
    ], axis=1).max(axis=1)
    return _wilder(tr, n)


def calc_adx(df: pd.DataFrame, n: int = 14) -> pd.Series:
    h, lo, c = df["high"], df["low"], df["close"]
    ph, pl, pc = h.shift(1), lo.shift(1), c.shift(1)
    up   = h  - ph
    down = pl - lo
    pdm  = pd.Series(np.where((up > down) & (up > 0),   up,   0.0), index=df.index)
    mdm  = pd.Series(np.where((down > up) & (down > 0), down, 0.0), index=df.index)
    tr   = pd.concat([h - lo, (h - pc).abs(), (lo - pc).abs()], axis=1).max(axis=1)
    a    = _wilder(tr, n)
    pdi  = 100.0 * _wilder(pdm, n) / a
    mdi  = 100.0 * _wilder(mdm, n) / a
    ds   = pdi + mdi
    dx   = pd.Series(np.where(ds > 0, 100.0 * (pdi - mdi).abs() / ds, 0.0), index=df.index)
    return _wilder(dx, n)


def calc_rso(close: pd.Series, lo: int = 10, hi: int = 100, step: int = 5) -> pd.Series:
    """Regression Slope Oscillator — exact Pine translation."""
    lengths = list(range(lo, hi + 1, step))
    max_l   = max(lengths)
    cls     = close.tolist()
    n       = len(cls)
    out     = [float("nan")] * n

    def _slope(w: list, l: int) -> float:
        sx = sy = sxx = sxy = 0.0
        for i in range(l):
            y = math.log(w[-(i + 1)])
            p = float(i + 1)
            sx += p;  sy += y;  sxx += p * p;  sxy += y * p
        d = l * sxx - sx * sx
        return 0.0 if d == 0 else (l * sxy - sx * sy) / d * -1.0

    for i in range(n):
        if i + 1 < max_l:
            continue
        out[i] = sum(_slope(cls[i - l + 1: i + 1], l) for l in lengths) / len(lengths)

    return pd.Series(out, index=close.index)


# ────────────────────────────── VARIANT CONFIG ───────────────────────────────

@dataclass
class Cfg:
    name:       str
    desc:       str
    stops:      bool  = False   # use ATR stop-loss + take-profit
    sl_mult:    float = 2.0     # stop-loss = entry ± sl_mult × ATR
    tp_mult:    float = 4.0     # take-profit = entry ± tp_mult × ATR  (2:1 R/R)
    use_adx:    bool  = False   # ADX(14) > adx_thr filter
    adx_thr:    float = 20.0
    zero_exit:  bool  = False   # exit long when osc crosses 0 upward; short when crosses 0 downward
    mtf_ema:    int   = 0       # 0=off; >0 = use 1d EMA(n) as direction filter (4h only)
    ema_filter: int   = 0       # 0=off; >0 = same-TF EMA(n) trend direction filter
    trailing:   bool  = False   # trailing stop: after entry trail at 1.5×ATR behind price


VARIANTS = [
    Cfg("A_baseline",   "Baseline — current logic, signal-flip exits only"),
    Cfg("B_stops",      "Stops    — 2xATR SL + 4xATR TP",               stops=True),
    Cfg("C_adx",        "ADX      — ADX>20 filter + zero-cross exit",    use_adx=True, zero_exit=True),
    Cfg("D_best",       "D_best   — Stops + ADX + zero-cross exit",      stops=True, use_adx=True, zero_exit=True),
    Cfg("E_mtf",        "MTF      — 4h + 1d EMA(50) + Stops + ADX",     stops=True, use_adx=True, zero_exit=True, mtf_ema=50),
    # Variants based on market analysis (BTC -29.5% in test period = bearish)
    Cfg("F_ema4h",      "EMA(50)  — same-TF EMA(50) trend filter",       ema_filter=50),
    Cfg("G_ema_best",   "EMA+Best — EMA(50) + Stops + ADX + zero-cross", stops=True, use_adx=True, zero_exit=True, ema_filter=50),
    Cfg("H_trailing",   "Trailing — EMA(50) + trailing stop (1.5xATR)",  ema_filter=50, trailing=True),
    # Targeting 1-2 trades/week with good quality on 1h
    Cfg("I_ema200",     "EMA(200) — 1h EMA(200) trend + stops (no ADX)", stops=True, ema_filter=200),
    Cfg("J_ema200_adx", "EMA200+A — EMA(200) + Stops + ADX",             stops=True, use_adx=True, ema_filter=200),
    Cfg("K_wide_stop",  "WideStop — 3xATR SL + 6xATR TP (baseline)",    stops=True, sl_mult=3.0, tp_mult=6.0),
]


# ───────────────────────── BACKTEST ENGINE ───────────────────────────────────

def run(df: pd.DataFrame, cfg: Cfg, interval: str, df_1d: pd.DataFrame | None = None):
    df   = df.reset_index(drop=True)
    osc  = calc_rso(df["close"])
    sigl = osc.rolling(7).mean()
    atr_ = calc_atr(df, 10)
    asm  = atr_.rolling(10).mean()
    adx_ = calc_adx(df) if cfg.use_adx else None

    # ── 1d EMA direction (look-ahead-safe merge) ──────────────────────────
    ema_dir = None
    if cfg.mtf_ema > 0 and df_1d is not None:
        d1      = df_1d.reset_index(drop=True).copy()
        d1_ema  = d1["close"].ewm(span=cfg.mtf_ema, adjust=False).mean()
        d1_dir  = (d1["close"] >= d1_ema).map({True: 1, False: -1}).values
        # A 1d bar is confirmed at its close = bar_open_ts + 86400000 ms
        d1_ts   = (d1["timestamp"].values + 86_400_000).astype(np.int64)
        bar_ts  = df["timestamp"].values.astype(np.int64)
        dirs    = []
        for ts in bar_ts:
            idx = bisect.bisect_right(d1_ts, ts) - 1
            dirs.append(int(d1_dir[idx]) if idx >= 0 else 1)
        ema_dir = pd.Series(dirs, index=df.index)

    # ── Same-TF EMA direction filter ───────────────────────────────────────
    same_tf_dir = None
    if cfg.ema_filter > 0:
        ema_s       = df["close"].ewm(span=cfg.ema_filter, adjust=False).mean()
        same_tf_dir = (df["close"] >= ema_s).map({True: 1, False: -1})

    # ── Signal generation (bar-by-bar) ────────────────────────────────────
    LONG, SHORT, HOLD = 1, -1, 0
    sigs = pd.Series(HOLD, index=df.index, dtype=int)

    for i in range(1, len(df)):
        oc, op = osc.iloc[i],  osc.iloc[i - 1]
        sc, sp = sigl.iloc[i], sigl.iloc[i - 1]
        if any(pd.isna(v) for v in [oc, op, sc, sp]):
            continue
        ac, am = atr_.iloc[i], asm.iloc[i]
        if pd.isna(ac) or pd.isna(am) or ac <= am:
            continue
        if cfg.use_adx:
            av = adx_.iloc[i]
            if pd.isna(av) or av < cfg.adx_thr:
                continue

        xup = (op < sp) and (oc > sc)
        xdn = (op > sp) and (oc < sc)

        # Determine allowed trade direction from filters
        # Both filters must agree if both active; if only one active, use it
        allow_long  = True
        allow_short = True
        if ema_dir is not None:
            allow_long  = allow_long  and (ema_dir.iloc[i] == LONG)
            allow_short = allow_short and (ema_dir.iloc[i] == SHORT)
        if same_tf_dir is not None:
            allow_long  = allow_long  and (same_tf_dir.iloc[i] == LONG)
            allow_short = allow_short and (same_tf_dir.iloc[i] == SHORT)

        if xup and oc < 0 and allow_long:
            sigs.iloc[i] = LONG
        elif xdn and oc > 0 and allow_short:
            sigs.iloc[i] = SHORT

    # ── Execution loop ────────────────────────────────────────────────────
    capital    = CAPITAL
    pos        = 0.0   # positive = long units, negative = short units
    ep         = 0.0   # entry price
    sl_p       = 0.0   # stop-loss / trailing-stop price
    tp_p       = 0.0   # take-profit price (unused when trailing)
    trail_mult = 1.5   # ATR multiples for trailing stop distance
    eq         = []
    trades     = []

    for i in range(1, len(df)):
        o     = df["open"].iloc[i]
        h     = df["high"].iloc[i]
        lo_b  = df["low"].iloc[i]
        c     = df["close"].iloc[i]
        sig   = sigs.iloc[i - 1]
        oi    = osc.iloc[i]
        op_i  = osc.iloc[i - 1]
        ae_i  = atr_.iloc[i]
        ae_i  = ae_i if not pd.isna(ae_i) else (atr_.dropna().iloc[-1] if len(atr_.dropna()) > 0 else 1.0)
        xp    = None   # exit price (None = no close this bar)
        rsn   = ""

        # ── Trailing stop update ──────────────────────────────────────────
        if cfg.trailing and pos != 0:
            if pos > 0:
                new_trail = h - trail_mult * ae_i
                sl_p = max(sl_p, new_trail)   # only raise trailing stop
            else:
                new_trail = lo_b + trail_mult * ae_i
                sl_p = min(sl_p, new_trail)   # only lower trailing stop (for shorts)

        # ── Stop / TP check ───────────────────────────────────────────────
        if (cfg.stops or cfg.trailing) and pos != 0:
            if pos > 0:
                if lo_b <= sl_p:   xp, rsn = sl_p, "stop"
                elif not cfg.trailing and h >= tp_p:   xp, rsn = tp_p, "tp"
            else:
                if h    >= sl_p:   xp, rsn = sl_p, "stop"
                elif not cfg.trailing and lo_b <= tp_p: xp, rsn = tp_p, "tp"

        # ── Zero-cross exit ───────────────────────────────────────────────
        if xp is None and cfg.zero_exit and pos != 0:
            if not (pd.isna(oi) or pd.isna(op_i)):
                if pos > 0 and op_i < 0 and oi >= 0:
                    xp, rsn = o, "zero_x"
                elif pos < 0 and op_i > 0 and oi <= 0:
                    xp, rsn = o, "zero_x"

        # ── Signal-flip exit ──────────────────────────────────────────────
        if xp is None and pos != 0:
            cur = LONG if pos > 0 else SHORT
            if sig != HOLD and sig != cur:
                xp, rsn = o, "flip"

        # ── Execute close ─────────────────────────────────────────────────
        if xp is not None:
            pnl = (xp - ep) * pos - abs(pos) * xp * COMM
            trades.append({"entry": ep, "exit": xp, "pnl": pnl, "reason": rsn})
            capital += pnl
            pos = 0.0

        # ── Open new position ─────────────────────────────────────────────
        if pos == 0 and sig != HOLD:
            units = capital / o
            ep    = o
            ae    = atr_.iloc[i - 1]
            if pd.isna(ae):
                ae = float(atr_.dropna().iloc[-1]) if len(atr_.dropna()) > 0 else 1.0

            if sig == LONG:
                pos  =  units
                sl_p = ep - cfg.sl_mult * ae
                tp_p = ep + cfg.tp_mult * ae
            else:
                pos  = -units
                sl_p = ep + cfg.sl_mult * ae
                tp_p = ep - cfg.tp_mult * ae

            capital -= abs(pos) * ep * COMM

        # ── Mark-to-market ────────────────────────────────────────────────
        unr = (c - ep) * pos if pos != 0 else 0.0
        eq.append(capital + unr)

    equity = pd.Series(eq, index=df.index[1:])
    return equity, trades


# ────────────────────────────── METRICS ──────────────────────────────────────

def get_metrics(equity: pd.Series, trades: list, interval: str) -> dict:
    bpw     = BARS_PER_WEEK[interval]
    ann     = ANNUALIZE[interval]
    n_weeks = max(len(equity) / bpw, 1.0)

    if len(equity) < 2:
        return {k: 0.0 for k in ["ret", "pf", "sharpe", "mdd", "wr", "n", "tpw"]}

    rets   = equity.pct_change().dropna()
    ret    = (equity.iloc[-1] / equity.iloc[0] - 1) * 100.0
    mdd    = (equity / equity.cummax() - 1).min() * 100.0
    sharpe = (rets.mean() / rets.std() * ann) if rets.std() > 0 else 0.0

    wins = [t["pnl"] for t in trades if t["pnl"] > 0]
    loss = [t["pnl"] for t in trades if t["pnl"] < 0]
    gp   = sum(wins) if wins else 0.0
    gl   = abs(sum(loss)) if loss else 0.0
    pf   = min(gp / gl, 99.9) if gl > 0 else (99.9 if gp > 0 else 0.0)
    wr   = len(wins) / len(trades) * 100.0 if trades else 0.0
    tpw  = len(trades) / n_weeks

    return dict(ret=ret, pf=pf, sharpe=sharpe, mdd=mdd, wr=wr, n=len(trades), tpw=tpw)


# ─────────────────────────────────── MAIN ────────────────────────────────────

def main():
    print("Loading BTCUSDT data ...")
    df_1h = load("1h")
    df_4h = load("4h")
    df_1d = load("1d")
    print(f"  1h: {len(df_1h)} bars | 4h: {len(df_4h)} bars | 1d: {len(df_1d)} bars\n")

    rows = []

    for cfg in VARIANTS:
        # MTF variant only makes sense on 4h (1d for direction, 4h for entries)
        if cfg.mtf_ema > 0:
            runs = [("4h", df_4h, df_1d)]
        else:
            runs = [("1h", df_1h, None), ("4h", df_4h, None), ("1d", df_1d, None)]

        for iv, df, df1d in runs:
            label = f"{cfg.name}[{iv}]"
            print(f"  {label:<22} ...", end=" ", flush=True)
            eq, trd = run(df, cfg, iv, df1d)
            m = get_metrics(eq, trd, iv)
            rows.append({"variant": cfg.name, "interval": iv, **m})
            print(f"ret={m['ret']:+6.1f}%  PF={m['pf']:5.2f}  MDD={m['mdd']:5.1f}%  "
                  f"trades={m['n']:3d} ({m['tpw']:.2f}/wk)")

    # ── Results table ─────────────────────────────────────────────────────────
    W = 108
    print("\n" + "=" * W)
    print(f"{'Variant':<22} {'IV':<4} {'Return%':>8} {'PF':>6} {'Sharpe':>7} "
          f"{'MaxDD%':>7} {'WinRate%':>9} {'Trades':>7} {'Trd/wk':>8}")
    print("-" * W)

    for r in rows:
        print(f"{r['variant']:<22} {r['interval']:<4} {r['ret']:>+8.1f} {r['pf']:>6.2f} "
              f"{r['sharpe']:>7.2f} {r['mdd']:>7.1f} {r['wr']:>8.1f}% {r['n']:>7d} "
              f"{r['tpw']:>7.2f}")
        # blank line between variant groups
        if r == rows[-1] or rows[rows.index(r) + 1]["variant"] != r["variant"]:
            print()

    # ── Best by various criteria ──────────────────────────────────────────────
    df_res = pd.DataFrame(rows)
    print("-" * W)

    best_pf  = df_res.loc[df_res["pf"].idxmax()]
    print(f"  Best Profit Factor : {best_pf['variant']}[{best_pf['interval']}]  "
          f"PF={best_pf['pf']:.2f}  ret={best_pf['ret']:+.1f}%  mdd={best_pf['mdd']:.1f}%")

    low_dd = df_res[df_res["mdd"] > -25]
    if not low_dd.empty:
        best_ret = low_dd.loc[low_dd["ret"].idxmax()]
        print(f"  Best Return (MaxDD<25%) : {best_ret['variant']}[{best_ret['interval']}]  "
              f"ret={best_ret['ret']:+.1f}%  PF={best_ret['pf']:.2f}  mdd={best_ret['mdd']:.1f}%")

    best_sh  = df_res.loc[df_res["sharpe"].idxmax()]
    print(f"  Best Sharpe        : {best_sh['variant']}[{best_sh['interval']}]  "
          f"Sharpe={best_sh['sharpe']:.2f}  ret={best_sh['ret']:+.1f}%")

    df_res["tpw_dist"] = (df_res["tpw"] - 1.5).abs()
    best_tpw = df_res.loc[df_res["tpw_dist"].idxmin()]
    print(f"  Closest 1-2 trades/week : {best_tpw['variant']}[{best_tpw['interval']}]  "
          f"{best_tpw['tpw']:.2f} trades/wk")

    # ── Composite score (return + PF + Sharpe, penalise DrawDown) ─────────────
    df_n = df_res.copy()
    for col in ["ret", "pf", "sharpe"]:
        span = df_n[col].max() - df_n[col].min()
        df_n[col + "_n"] = (df_n[col] - df_n[col].min()) / span if span > 0 else 0.5
    mdd_span = df_n["mdd"].max() - df_n["mdd"].min()
    df_n["mdd_n"] = (df_n["mdd"] - df_n["mdd"].max()) / mdd_span if mdd_span != 0 else 0.5
    df_n["score"] = 0.40 * df_n["ret_n"] + 0.30 * df_n["pf_n"] + 0.20 * df_n["sharpe_n"] + 0.10 * df_n["mdd_n"]

    best_idx = df_n["score"].idxmax()
    r   = df_res.loc[best_idx]
    cfg = {c.name: c for c in VARIANTS}[r["variant"]]

    print("\n" + "=" * W)
    print("  BEST OVERALL STRATEGY")
    print("=" * W)
    print(f"  Variant  : {r['variant']}  ({cfg.desc})")
    print(f"  Interval : {r['interval']}")
    print(f"  Return   : {r['ret']:+.1f}%")
    print(f"  PF       : {r['pf']:.2f}")
    print(f"  Sharpe   : {r['sharpe']:.2f}")
    print(f"  Max DD   : {r['mdd']:.1f}%")
    print(f"  Win Rate : {r['wr']:.1f}%")
    print(f"  Trades   : {r['n']}  ({r['tpw']:.2f}/week)")

    print("\n  Improvements vs baseline:")
    if cfg.stops:
        print(f"    + Stop-loss  : {cfg.sl_mult}× ATR below/above entry  "
              f"(limits per-trade loss)")
        print(f"    + Take-profit: {cfg.tp_mult}× ATR above/below entry  "
              f"(R/R = {cfg.tp_mult/cfg.sl_mult:.1f}:1)")
    if cfg.use_adx:
        print(f"    + ADX(14) > {cfg.adx_thr:.0f} filter  "
              f"(skip sideways / low-trend bars)")
    if cfg.zero_exit:
        print(f"    + Zero-cross exit  "
              f"(exit when oscillator completes its reversal cycle)")
    if cfg.mtf_ema > 0:
        print(f"    + 1d EMA({cfg.mtf_ema}) direction filter  "
              f"(only long above EMA, only short below EMA)")
    if cfg.ema_filter > 0:
        print(f"    + EMA({cfg.ema_filter}) same-TF trend filter  "
              f"(only long when price > EMA, only short when price < EMA)")
    if cfg.trailing:
        print(f"    + Trailing stop (1.5x ATR)  "
              f"(stop rises/falls with price to lock in profits)")
    print("=" * W)

    # ── Exit reason breakdown for best variant ────────────────────────────────
    eq_best, trd_best = run(
        df_4h if r["interval"] == "4h" else (df_1h if r["interval"] == "1h" else df_1d),
        cfg, r["interval"],
        df_1d if cfg.mtf_ema > 0 else None,
    )
    if trd_best:
        from collections import Counter
        reasons = Counter(t["reason"] for t in trd_best)
        wins_r  = Counter(t["reason"] for t in trd_best if t["pnl"] > 0)
        print("\n  Exit reason breakdown:")
        for rsn, cnt in sorted(reasons.items(), key=lambda x: -x[1]):
            w = wins_r.get(rsn, 0)
            avg_pnl = sum(t["pnl"] for t in trd_best if t["reason"] == rsn) / cnt
            print(f"    {rsn:<8}: {cnt:3d} trades  "
                  f"win rate={w/cnt*100:.0f}%  avg PnL=${avg_pnl:+.2f}")
    print("=" * W)


if __name__ == "__main__":
    main()
