"""
sensitivity_v2_lock.py — sensitivity analysis for the two v2.0 production
parameters: V2 bear-DD threshold and slow-stress lock days.

Two scans, holding everything else at v2.0 defaults (Config 7 = Mom30 + V2 +
5-day lock):

  Scan 1 — V2 bear-DD threshold (with lock=5d fixed)
           Values: 10%, 12%, 15%, 18%, 20% (and "no V2" for reference)
  Scan 2 — Slow-stress lock days (with V2 threshold=15% fixed)
           Values: 0 (no lock), 3, 5, 7, 10, 15, 20

For each variant report: CAGR, Sharpe, Calmar, MaxDD, key-year impact (2009,
2018, 2019, 2020 — most sensitive years), and disqualification flags.
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import strategy as s
from strategy_lab import _load_data


def run_v7(raw, *, lock_days=5, v2_dd=0.15, v2_days=60, enable_v2=True):
    combiner = s.make_combiner(rotate_stress=True, rotate_panic=False,
                                use_momentum_gold=True,
                                slow_stress_lock_days=lock_days)
    strat = s.MacroStrategy(combiner, nifty_cost_bps=3, gold_cost_bps=5,
                             long_target="NIFTYMOM30", long_cost_bps=6,
                             enable_v2=enable_v2,
                             v2_dd_threshold=v2_dd,
                             v2_days=v2_days)
    return strat.run(raw).loc["2008-04-01":"2025-12-31"]


def year_return(df, year, month=None):
    if month is None:
        mask = (df.index.year == year)
    else:
        mask = (df.index.year == year) & (df.index.month == month)
    sub = df["strategy_return"][mask]
    return float((1 + sub).prod() - 1) * 100


def main():
    raw = _load_data()

    print("Running V2 DD-threshold scan ...", file=sys.stderr)
    v2_scan = [
        ("V2 OFF (no V2)",   dict(enable_v2=False, lock_days=5)),
        ("V2 DD ≥ 10%",      dict(v2_dd=0.10, lock_days=5)),
        ("V2 DD ≥ 12%",      dict(v2_dd=0.12, lock_days=5)),
        ("V2 DD ≥ 15% (PROD)", dict(v2_dd=0.15, lock_days=5)),
        ("V2 DD ≥ 18%",      dict(v2_dd=0.18, lock_days=5)),
        ("V2 DD ≥ 20%",      dict(v2_dd=0.20, lock_days=5)),
    ]
    v2_results = [(label, run_v7(raw, **params)) for label, params in v2_scan]

    print("Running lock-days scan ...", file=sys.stderr)
    lock_scan = [
        ("Lock 0d (no lock)", dict(lock_days=0, v2_dd=0.15)),
        ("Lock 3d",           dict(lock_days=3, v2_dd=0.15)),
        ("Lock 5d (PROD)",    dict(lock_days=5, v2_dd=0.15)),
        ("Lock 7d",           dict(lock_days=7, v2_dd=0.15)),
        ("Lock 10d",          dict(lock_days=10, v2_dd=0.15)),
        ("Lock 15d",          dict(lock_days=15, v2_dd=0.15)),
        ("Lock 20d",          dict(lock_days=20, v2_dd=0.15)),
    ]
    lock_results = [(label, run_v7(raw, **params)) for label, params in lock_scan]

    out = []
    def p(text=""): print(text); out.append(text)

    p("\n" + "=" * 140)
    p("  SENSITIVITY ANALYSIS — V2 bear-DD threshold and slow-stress lock days")
    p("=" * 140)
    p()
    p("  Production (Config 7 / v2.0 / L5): V2 DD ≥ 15%, V2 hold = 60 days,")
    p("  slow-stress lock = 5 days. All other parameters fixed at v1.5 defaults.")
    p()

    # ---- Scan 1: V2 DD threshold ----
    p("=" * 140)
    p("  SCAN 1 — V2 bear-DD threshold (lock=5d fixed)")
    p("=" * 140)
    p(f"  {'Variant':<22} {'CAGR':>9} {'Sharpe':>8} {'Calmar':>8} {'MaxDD':>9} {'Rs1 →':>9} "
      f"{'2009':>8} {'2018':>8} {'2019':>8} {'2020':>8}  Note")
    p("  " + "-"*22 + " " + "-"*9 + " " + "-"*8 + " " + "-"*8 + " " + "-"*9 + " " + "-"*9
      + " " + "-"*8 + " " + "-"*8 + " " + "-"*8 + " " + "-"*8 + "  " + "-"*30)
    prod_m = None
    for label, df in v2_results:
        m = s.metrics(df["strategy_return"])
        cum = (1 + df["strategy_return"]).cumprod().iloc[-1]
        y09 = year_return(df, 2009); y18 = year_return(df, 2018)
        y19 = year_return(df, 2019); y20 = year_return(df, 2020)
        note = ""
        if "PROD" in label:
            prod_m = m
            note = "← chosen"
        elif prod_m is not None:
            dc = m["cagr"] - prod_m["cagr"]
            note = f"Δ CAGR {dc*100:+.2f}pp vs PROD"
        p(f"  {label:<22} {m['cagr']*100:+7.2f}% {m['sharpe']:>8.3f} {m['calmar']:>8.2f} "
          f"{m['max_dd']*100:+8.2f}% Rs{cum:>6.2f} {y09:>+7.1f}% {y18:>+7.1f}% "
          f"{y19:>+7.1f}% {y20:>+7.1f}%  {note}")
    p()

    # ---- Scan 2: lock days ----
    p("=" * 140)
    p("  SCAN 2 — slow-stress lock days (V2 DD=15% fixed)")
    p("=" * 140)
    p(f"  {'Variant':<22} {'CAGR':>9} {'Sharpe':>8} {'Calmar':>8} {'MaxDD':>9} {'Rs1 →':>9} "
      f"{'2018-Sep':>9} {'2019':>8} {'2013':>8} {'2021':>8}  Note")
    p("  " + "-"*22 + " " + "-"*9 + " " + "-"*8 + " " + "-"*8 + " " + "-"*9 + " " + "-"*9
      + " " + "-"*9 + " " + "-"*8 + " " + "-"*8 + " " + "-"*8 + "  " + "-"*30)
    prod_m = None
    for label, df in lock_results:
        m = s.metrics(df["strategy_return"])
        cum = (1 + df["strategy_return"]).cumprod().iloc[-1]
        y18sep = year_return(df, 2018, month=9)
        y19 = year_return(df, 2019); y13 = year_return(df, 2013); y21 = year_return(df, 2021)
        note = ""
        if "PROD" in label:
            prod_m = m
            note = "← chosen"
        elif prod_m is not None:
            dc = m["cagr"] - prod_m["cagr"]
            note = f"Δ CAGR {dc*100:+.2f}pp vs PROD"
        p(f"  {label:<22} {m['cagr']*100:+7.2f}% {m['sharpe']:>8.3f} {m['calmar']:>8.2f} "
          f"{m['max_dd']*100:+8.2f}% Rs{cum:>6.2f} {y18sep:>+8.1f}% {y19:>+7.1f}% "
          f"{y13:>+7.1f}% {y21:>+7.1f}%  {note}")
    p()

    # ---- Disqualification snapshot ----
    p("=" * 140)
    p("  DISQUALIFICATION CHECK — give-back > 1pp in {2008, 2018-Sep, 2020, 2021} vs prod (Cfg 7)")
    p("=" * 140)
    prod_df = [df for label, df in v2_results if "PROD" in label][0]
    base_vals = {
        "2008":     year_return(prod_df, 2008),
        "2018-Sep": year_return(prod_df, 2018, month=9),
        "2020":     year_return(prod_df, 2020),
        "2021":     year_return(prod_df, 2021),
    }
    p()
    p("  V2 DD threshold scan:")
    p(f"    {'Variant':<22} {'2008':>10} {'2018-Sep':>11} {'2020':>10} {'2021':>10}    Verdict")
    p("    " + "-"*22 + " " + "-"*10 + " " + "-"*11 + " " + "-"*10 + " " + "-"*10
      + "    " + "-"*30)
    for label, df in v2_results:
        vals = {k: year_return(df, *((int(k.split("-")[0]),) if "-" not in k else (int(k.split("-")[0]), 9)))
                for k in base_vals}
        deltas = {k: vals[k] - base_vals[k] for k in base_vals}
        disq = [f"{k} ({d:+.2f}pp)" for k, d in deltas.items() if d < -1.0]
        verdict = "DISQ: " + ", ".join(disq) if disq else "PASS"
        row = f"    {label:<22} " + "  ".join(
            f"{vals[k]:>+5.2f}({deltas[k]:+.1f})" for k in ["2008", "2018-Sep", "2020", "2021"])
        p(f"{row}    {verdict}")
    p()
    p("  Lock-days scan:")
    p(f"    {'Variant':<22} {'2008':>10} {'2018-Sep':>11} {'2020':>10} {'2021':>10}    Verdict")
    p("    " + "-"*22 + " " + "-"*10 + " " + "-"*11 + " " + "-"*10 + " " + "-"*10
      + "    " + "-"*30)
    for label, df in lock_results:
        vals = {k: year_return(df, *((int(k.split("-")[0]),) if "-" not in k else (int(k.split("-")[0]), 9)))
                for k in base_vals}
        deltas = {k: vals[k] - base_vals[k] for k in base_vals}
        disq = [f"{k} ({d:+.2f}pp)" for k, d in deltas.items() if d < -1.0]
        verdict = "DISQ: " + ", ".join(disq) if disq else "PASS"
        row = f"    {label:<22} " + "  ".join(
            f"{vals[k]:>+5.2f}({deltas[k]:+.1f})" for k in ["2008", "2018-Sep", "2020", "2021"])
        p(f"{row}    {verdict}")
    p()
    p("  (Each cell shows: variant_return (Δ_vs_prod). Disqualification threshold: Δ < -1.0pp.)")
    p()

    txt = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "results", "sensitivity_v2_lock.txt")
    with open(txt, "w") as f:
        f.write("\n".join(out))
    print(f"\nSaved to {txt}", file=sys.stderr)


if __name__ == "__main__":
    main()
