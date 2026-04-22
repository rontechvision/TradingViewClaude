#!/usr/bin/env python3
"""Explore HARSI improvements on BTCUSDT 4h.

Variants tested:
  A — Baseline (RSI crossover of +/-20 OB/OS)
  B — + EMA trend filter (50)
  C — + EMA trend filter (100)
  D — + EMA trend filter (200)
  E — + ATR stop-loss (2x) / take-profit (4x)
  F — + ADX > 20 filter (trend regime)
  G — EMA50 + ATR stops combined
  H — EMA50 + ADX filter combined
  I — EMA50 + ATR stops + ADX combined  (the "deluxe" variant)
  J — MTF: 1d EMA50 direction filter on 4h entries
  K — HARSI candle color confirm (C > O for long, C < O for short)
  L — Stoch RSI confirmation (StochK crosses StochD in OB/OS zones)
  M — Wider OB/OS (+25/-25) for higher-quality signals
  N — Narrower OB/OS (+15/-15) for more frequent entries

Position size: 5% equity per trade @ 10x leverage = 50% notional exposure.
Commission: 0.05% per side (0.10% roundtrip).
"""
import sys, os, bisect
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import math
import pandas as pd
import numpy as np
from dataclasses import dataclass, field
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "BTCUSDT"

# Crypto 10x defaults (match strategy-translator.md)
INITIAL_CAPITAL = 1000.0
POSITION_PCT    = 0.05     # 5% of equity as margin
LEVERAGE        = 10       # 10x
COMMISSION_PCT  = 0.0005   # 0.05% per side


# ---------- Data loading ----------
def load_csv(interval: str) -> pd.DataFrame:
    files = sorted((DATA_DIR).glob(f"BTCUSDT_{interval}_*.csv"))
    if not files:
        raise FileNotFoundError(f"No {interval} data in {DATA_DIR}")
    df = pd.read_csv(files[-1])
    df = df.reset_index(drop=True)
    return df


# ---------- Indicator helpers ----------
def wilder_rsi(src: pd.Series, n: int) -> pd.Series:
    delta = src.diff()
    gain = delta.clip(lower=0.0)
    loss = (-delta).clip(lower=0.0)
    ag = gain.ewm(alpha=1/n, adjust=False).mean()
    al = loss.ewm(alpha=1/n, adjust=False).mean()
    rs = ag / al.replace(0.0, np.nan)
    rsi = 100 - 100 / (1 + rs)
    return rsi.where(al != 0, 100.0)


def compute_rsi_smoothed(src: pd.Series, n: int) -> pd.Series:
    """Pine f_rsi with i_mode=true: recursive smoothed zero-median RSI."""
    zrsi = wilder_rsi(src, n) - 50.0
    out = [float("nan")] * len(zrsi)
    prev = float("nan")
    for i, v in enumerate(zrsi.tolist()):
        if pd.isna(v):
            continue
        cur = v if pd.isna(prev) else (prev + v) / 2.0
        out[i] = cur
        prev = cur
    return pd.Series(out, index=src.index, dtype=float)


def compute_atr(df: pd.DataFrame, n: int) -> pd.Series:
    h, l, c = df["high"], df["low"], df["close"]
    pc = c.shift(1)
    tr = pd.concat([h - l, (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1/n, adjust=False).mean()


def compute_adx(df: pd.DataFrame, n: int) -> pd.Series:
    h, l, c = df["high"], df["low"], df["close"]
    up, dn = h.diff(), -l.diff()
    plus_dm  = np.where((up > dn) & (up > 0),  up,  0.0)
    minus_dm = np.where((dn > up) & (dn > 0),  dn,  0.0)
    pc = c.shift(1)
    tr = pd.concat([h - l, (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1/n, adjust=False).mean()
    pdi = 100 * pd.Series(plus_dm,  index=df.index).ewm(alpha=1/n, adjust=False).mean() / atr
    mdi = 100 * pd.Series(minus_dm, index=df.index).ewm(alpha=1/n, adjust=False).mean() / atr
    dx = 100 * (pdi - mdi).abs() / (pdi + mdi).replace(0, np.nan)
    return dx.ewm(alpha=1/n, adjust=False).mean()


def compute_stoch(src: pd.Series, n: int, smooth_k: int, smooth_d: int, scale: int) -> tuple:
    lo = src.rolling(n).min()
    hi = src.rolling(n).max()
    raw = 100 * (src - lo) / (hi - lo).replace(0, np.nan) - 50
    sma_k = raw.rolling(smooth_k).mean()
    k = (sma_k / 100.0) * scale
    d = k.rolling(smooth_d).mean()
    return k, d


# ---------- Config & backtest ----------
@dataclass
class Cfg:
    name: str
    desc: str
    ob:          int = 20
    os_:         int = -20     # "os" is builtin
    ema_filter:  int = 0        # 0 disabled
    atr_stops:   bool = False
    sl_mult:     float = 2.0
    tp_mult:     float = 4.0
    adx_filter:  bool = False
    adx_thr:     float = 20.0
    mtf_1d_ema:  int = 0        # 0 disabled
    harsi_color: bool = False
    stoch_confirm: bool = False


def run(df: pd.DataFrame, cfg: Cfg, interval: str, df_1d: pd.DataFrame | None = None) -> dict:
    src = (df["open"] + df["high"] + df["low"] + df["close"]) / 4.0
    rsi = compute_rsi_smoothed(src, 7)
    atr = compute_atr(df, 14)
    adx = compute_adx(df, 14)
    ema = df["close"].ewm(span=cfg.ema_filter, adjust=False).mean() if cfg.ema_filter else None
    stoch_k, stoch_d = (None, None)
    if cfg.stoch_confirm:
        stoch_k, stoch_d = compute_stoch(rsi, 14, 3, 3, 80)

    # HARSI candles (simplified — only need C > O for color)
    # zero-median RSI open is nz(close_rsi[1], close_rsi); close is avg of o/h/l/c RSI
    # For color confirmation we just need C vs O of HARSI candles
    close_rsi = wilder_rsi(df["close"], 15) - 50
    open_rsi  = close_rsi.shift(1).fillna(close_rsi)
    high_raw  = wilder_rsi(df["high"],  15) - 50
    low_raw   = wilder_rsi(df["low"],   15) - 50
    h_rsi = pd.concat([high_raw, low_raw], axis=1).max(axis=1)
    l_rsi = pd.concat([high_raw, low_raw], axis=1).min(axis=1)
    c_harsi = (open_rsi + h_rsi + l_rsi + close_rsi) / 4.0
    # Smoothed open (Pine f_rsiHeikinAshi with i_smoothing=5)
    o_harsi = [float("nan")] * len(df)
    s = 5
    for i in range(len(df)):
        if i < s or pd.isna(open_rsi.iloc[i]) or pd.isna(close_rsi.iloc[i]):
            continue
        prior = o_harsi[i-1] if (i > 0 and not pd.isna(o_harsi[i-1])) else np.nan
        if pd.isna(prior):
            o_harsi[i] = (open_rsi.iloc[i] + close_rsi.iloc[i]) / 2.0
        else:
            o_harsi[i] = (prior * s + c_harsi.iloc[i-1]) / (s + 1)
    o_harsi = pd.Series(o_harsi, index=df.index)

    # MTF 1d EMA lookup
    d1_ts, d1_bull = None, None
    if cfg.mtf_1d_ema and df_1d is not None:
        d1_ema = df_1d["close"].ewm(span=cfg.mtf_1d_ema, adjust=False).mean()
        d1_bull_arr = (df_1d["close"] > d1_ema).tolist()
        # Confirmed at end of the day: ts + 86_400_000 ms
        d1_ts = (df_1d["timestamp"] + 86_400_000).tolist()
        d1_bull = d1_bull_arr

    # State
    capital = INITIAL_CAPITAL
    pos = 0          # +1 long, -1 short, 0 flat
    entry_px = 0.0
    entry_atr = 0.0
    notional = 0.0
    trades = []
    equity = [capital]

    for i in range(1, len(df)):
        open_px = df["open"].iloc[i]
        high_px = df["high"].iloc[i]
        low_px  = df["low"].iloc[i]
        close_px= df["close"].iloc[i]
        ts = df["timestamp"].iloc[i]

        cur = rsi.iloc[i-1]  # use confirmed bar for signal
        prv = rsi.iloc[i-2] if i >= 2 else np.nan

        # --- Check ATR stop-loss / take-profit INTRA-BAR on bar i ---
        if pos != 0 and cfg.atr_stops:
            sl = entry_px - cfg.sl_mult * entry_atr * pos
            tp = entry_px + cfg.tp_mult * entry_atr * pos
            hit_sl = (pos > 0 and low_px  <= sl) or (pos < 0 and high_px >= sl)
            hit_tp = (pos > 0 and high_px >= tp) or (pos < 0 and low_px  <= tp)
            exit_px = None
            reason = ""
            if hit_sl and hit_tp:
                # Conservative: assume SL hit first (worst case)
                exit_px = sl
                reason = "SL"
            elif hit_sl:
                exit_px, reason = sl, "SL"
            elif hit_tp:
                exit_px, reason = tp, "TP"
            if exit_px is not None:
                pnl_pct = (exit_px - entry_px) / entry_px * pos
                gross = notional * pnl_pct
                gross -= notional * COMMISSION_PCT  # exit commission
                capital += gross
                trades.append({
                    "entry": entry_px, "exit": exit_px, "pnl": gross,
                    "side": "L" if pos > 0 else "S", "reason": reason,
                    "entry_i": entry_i, "exit_i": i,
                })
                pos = 0

        # --- Determine signal on confirmed bar (i-1) ---
        long_sig = False
        short_sig = False
        if not (pd.isna(cur) or pd.isna(prv)):
            if prv <= cfg.os_ and cur > cfg.os_:
                long_sig = True
            if prv >= cfg.ob and cur < cfg.ob:
                short_sig = True

        # Filters — applied at bar i-1 context
        if cfg.ema_filter:
            ema_prev = ema.iloc[i-1]
            close_prev = df["close"].iloc[i-1]
            if long_sig and not (close_prev > ema_prev):
                long_sig = False
            if short_sig and not (close_prev < ema_prev):
                short_sig = False

        if cfg.adx_filter:
            adx_prev = adx.iloc[i-1]
            if not (adx_prev > cfg.adx_thr):
                long_sig = False
                short_sig = False

        if cfg.harsi_color:
            o_prev = o_harsi.iloc[i-1]
            c_prev = c_harsi.iloc[i-1]
            if pd.isna(o_prev) or pd.isna(c_prev):
                long_sig = False
                short_sig = False
            else:
                if long_sig  and not (c_prev > o_prev): long_sig = False
                if short_sig and not (c_prev < o_prev): short_sig = False

        if cfg.stoch_confirm:
            k_prev = stoch_k.iloc[i-1]
            d_prev = stoch_d.iloc[i-1]
            k_prv2 = stoch_k.iloc[i-2] if i >= 2 else np.nan
            d_prv2 = stoch_d.iloc[i-2] if i >= 2 else np.nan
            if long_sig:
                cross_up = (not pd.isna(k_prv2)) and (k_prv2 <= d_prv2) and (k_prev > d_prev)
                if not cross_up: long_sig = False
            if short_sig:
                cross_dn = (not pd.isna(k_prv2)) and (k_prv2 >= d_prv2) and (k_prev < d_prev)
                if not cross_dn: short_sig = False

        if cfg.mtf_1d_ema and d1_ts is not None:
            # Find most recent confirmed 1d bar <= ts at i-1
            ts_prev = df["timestamp"].iloc[i-1]
            idx = bisect.bisect_right(d1_ts, ts_prev) - 1
            if idx < 0:
                long_sig = False
                short_sig = False
            else:
                is_bull_day = d1_bull[idx]
                if long_sig  and not is_bull_day:    long_sig = False
                if short_sig and is_bull_day:        short_sig = False

        # --- Handle signal-based entries/exits at bar i open ---
        new_sig = 0
        if long_sig:  new_sig = +1
        if short_sig: new_sig = -1

        if pos != 0 and new_sig != 0 and new_sig != pos:
            # Close existing on opposite
            pnl_pct = (open_px - entry_px) / entry_px * pos
            gross = notional * pnl_pct
            gross -= notional * COMMISSION_PCT
            capital += gross
            trades.append({
                "entry": entry_px, "exit": open_px, "pnl": gross,
                "side": "L" if pos > 0 else "S", "reason": "REV",
                "entry_i": entry_i, "exit_i": i,
            })
            pos = 0

        if pos == 0 and new_sig != 0:
            margin = capital * POSITION_PCT
            notional = margin * LEVERAGE
            notional -= notional * COMMISSION_PCT  # entry commission
            entry_px = open_px
            entry_atr = atr.iloc[i-1] if not pd.isna(atr.iloc[i-1]) else 0.0
            entry_i = i
            pos = new_sig

        # Equity (mark-to-market)
        unreal = 0.0
        if pos != 0:
            unreal = notional * (close_px - entry_px) / entry_px * pos
        equity.append(capital + unreal)

    # Final close at last bar
    if pos != 0:
        last_close = df["close"].iloc[-1]
        pnl_pct = (last_close - entry_px) / entry_px * pos
        gross = notional * pnl_pct
        gross -= notional * COMMISSION_PCT
        capital += gross
        trades.append({
            "entry": entry_px, "exit": last_close, "pnl": gross,
            "side": "L" if pos > 0 else "S", "reason": "EOD",
            "entry_i": entry_i, "exit_i": len(df) - 1,
        })

    equity_series = pd.Series(equity, index=df.index[:len(equity)])
    return {
        "cfg": cfg,
        "metrics": metrics(equity_series, trades, interval),
        "trades": trades,
        "equity": equity_series,
    }


# ---------- Metrics ----------
def metrics(eq: pd.Series, trades: list, interval: str) -> dict:
    if len(eq) < 2:
        return {}
    ret = (eq.iloc[-1] / eq.iloc[0] - 1) * 100
    rets = eq.pct_change().dropna()
    bars_per_year = {"1h": 8760, "4h": 2190, "1d": 365}[interval]
    sharpe = (rets.mean() / rets.std() * math.sqrt(bars_per_year)) if rets.std() > 0 else 0.0
    dd = (eq / eq.cummax() - 1) * 100
    mdd = dd.min()
    wins = [t["pnl"] for t in trades if t["pnl"] > 0]
    losses = [t["pnl"] for t in trades if t["pnl"] < 0]
    gp = sum(wins) if wins else 0
    gl = abs(sum(losses)) if losses else 1e-9
    pf = gp / gl if gl > 0 else float("inf")
    wr = (len(wins) / len(trades) * 100) if trades else 0
    # Trades per week
    if trades:
        bars_per_week = {"1h": 168, "4h": 42, "1d": 7}[interval]
        tpw = len(trades) / (len(eq) / bars_per_week)
    else:
        tpw = 0
    return {
        "ret": ret, "pf": pf, "sharpe": sharpe, "mdd": mdd,
        "wr": wr, "trades": len(trades), "tpw": tpw,
        "avg_w": np.mean(wins) if wins else 0,
        "avg_l": np.mean(losses) if losses else 0,
    }


# ---------- Main ----------
def main():
    df_4h = load_csv("4h")
    df_1d = load_csv("1d")

    configs = [
        Cfg("A_baseline",      "Baseline HARSI"),
        Cfg("B_ema50",         "+ EMA(50) trend filter",   ema_filter=50),
        Cfg("C_ema100",        "+ EMA(100) trend filter",  ema_filter=100),
        Cfg("D_ema200",        "+ EMA(200) trend filter",  ema_filter=200),
        Cfg("E_atr_stops",     "+ ATR stops 2x/4x",        atr_stops=True),
        Cfg("F_adx",           "+ ADX > 20 filter",        adx_filter=True),
        Cfg("G_ema50+atr",     "EMA(50) + ATR stops",      ema_filter=50, atr_stops=True),
        Cfg("H_ema50+adx",     "EMA(50) + ADX filter",     ema_filter=50, adx_filter=True),
        Cfg("I_all",           "EMA(50)+ATR+ADX combo",    ema_filter=50, atr_stops=True, adx_filter=True),
        Cfg("J_mtf_1d",        "+ 1d EMA50 MTF filter",    mtf_1d_ema=50),
        Cfg("K_harsi_color",   "+ HARSI candle color",     harsi_color=True),
        Cfg("L_stoch_confirm", "+ Stoch K/D crossover",    stoch_confirm=True),
        Cfg("M_wide_OB",       "Wider OB/OS (+/-25)",      ob=25,  os_=-25),
        Cfg("N_narrow_OB",     "Narrower OB/OS (+/-15)",   ob=15,  os_=-15),
        Cfg("O_ema50_wide",    "EMA(50) + wider OB/OS",    ema_filter=50, ob=25, os_=-25),
        Cfg("P_ema50_stops_color", "EMA50+ATR stops+HARSI color", ema_filter=50, atr_stops=True, harsi_color=True),
    ]

    print(f"\n{'='*95}")
    print(f"HARSI Improvement Exploration — BTCUSDT 4h")
    print(f"Capital: ${INITIAL_CAPITAL}  |  Leverage: {LEVERAGE}x  |  Size: {POSITION_PCT*100:.0f}% equity/trade")
    print(f"Commission: {COMMISSION_PCT*100:.2f}% per side  |  Data: {len(df_4h)} bars")
    print(f"{'='*95}")

    results = []
    for cfg in configs:
        r = run(df_4h, cfg, "4h", df_1d)
        results.append(r)

    # Sort by composite score
    def score(m):
        if not m or m["trades"] < 5: return -1e9
        return (
            0.35 * m["ret"]
            + 0.30 * m["pf"] * 10
            + 0.20 * m["sharpe"] * 10
            + 0.15 * m["mdd"]   # more negative = worse
        )

    # Print table
    hdr = f"{'Variant':<20} {'Desc':<32} {'Ret%':>7} {'PF':>6} {'Shrp':>6} {'MDD%':>7} {'WR%':>6} {'Trd':>4} {'/wk':>5}"
    print(hdr)
    print("-" * len(hdr))
    for r in results:
        m = r["metrics"]
        if not m:
            print(f"{r['cfg'].name:<20} {r['cfg'].desc:<32} NO DATA")
            continue
        print(f"{r['cfg'].name:<20} {r['cfg'].desc:<32} "
              f"{m['ret']:+7.1f} {m['pf']:6.2f} {m['sharpe']:6.2f} {m['mdd']:7.1f} "
              f"{m['wr']:6.1f} {m['trades']:4d} {m['tpw']:5.2f}")

    # Best
    results_sorted = sorted(results, key=lambda r: score(r["metrics"]), reverse=True)
    best = results_sorted[0]
    print("\n" + "=" * 95)
    print(f"BEST: {best['cfg'].name} — {best['cfg'].desc}")
    print("=" * 95)
    m = best["metrics"]
    print(f"Return       : {m['ret']:+7.2f}%")
    print(f"Profit Factor: {m['pf']:7.2f}")
    print(f"Sharpe       : {m['sharpe']:7.2f}")
    print(f"Max Drawdown : {m['mdd']:7.2f}%")
    print(f"Win Rate     : {m['wr']:7.2f}%")
    print(f"Trades       : {m['trades']} ({m['tpw']:.2f}/week)")
    print(f"Avg Win      : ${m['avg_w']:.2f}")
    print(f"Avg Loss     : ${m['avg_l']:.2f}")

    # Trade exit reason breakdown for best
    reasons = {}
    for t in best["trades"]:
        reasons.setdefault(t["reason"], []).append(t["pnl"])
    print("\nExit reason breakdown:")
    for r_, pnls in reasons.items():
        print(f"  {r_:4}: {len(pnls):3d} trades, total ${sum(pnls):+8.2f}, avg ${np.mean(pnls):+7.2f}")

    # Losing trade inspection for baseline vs best
    print("\n" + "-" * 95)
    print("Losing trades in BASELINE (first 10):")
    print("-" * 95)
    base = results[0]
    loss_base = [t for t in base["trades"] if t["pnl"] < 0][:10]
    for t in loss_base:
        ts_entry = pd.to_datetime(df_4h["timestamp"].iloc[t["entry_i"]], unit="ms")
        ts_exit  = pd.to_datetime(df_4h["timestamp"].iloc[t["exit_i"]], unit="ms")
        print(f"  {t['side']} {ts_entry} -> {ts_exit}  "
              f"entry ${t['entry']:.0f} exit ${t['exit']:.0f}  pnl ${t['pnl']:+7.2f}  [{t['reason']}]")


if __name__ == "__main__":
    main()
