"""dd_compare_lock5d_dyna.py — drawdown comparison: C1+Lock5d vs Dynamic A."""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np
import pandas as pd

from strategy_lab import (
    MacroStrategyLab, RegimeFilter, SignalCombiner,
    USDINRSignal, IndiaVIXSignal, SlowStressSignal, PanicShortSignal,
    _load_data, metrics, apply_annual_tax, build_rbi_repo_rate_series,
)
from test_min_hold_after_stress import SlowStressWithLockSignal
from compare_lock5d_vs_dyna import build_combiner, run_active, build_dyn_a


def drawdown_series(returns):
    cum = (1 + returns).cumprod()
    peak = cum.cummax()
    return (cum - peak) / peak


def top_drawdowns(returns, n=5):
    """Identify top-N drawdown episodes (peak-to-trough-to-recovery)."""
    cum = (1 + returns).cumprod()
    peak = cum.cummax()
    dd = (cum - peak) / peak
    in_dd = dd < 0
    episodes = []
    i = 0
    while i < len(dd):
        if in_dd.iloc[i]:
            start = i
            while i < len(dd) and in_dd.iloc[i]:
                i += 1
            end = i  # day of recovery (or end of sample)
            ep = dd.iloc[start:end]
            trough_idx = ep.idxmin()
            episodes.append({
                "peak_date": cum.index[start-1] if start > 0 else cum.index[0],
                "trough_date": trough_idx,
                "recovery_date": cum.index[end] if end < len(cum) else None,
                "min_dd": float(ep.min()),
                "duration_days": end - start + 1,
                "trough_days": (trough_idx - cum.index[start-1]).days if start > 0 else 0,
            })
        else:
            i += 1
    episodes.sort(key=lambda e: e["min_dd"])
    return episodes[:n]


def main():
    START, END = "2008-04-01", "2025-12-31"
    raw = _load_data()

    print("Running C1+Lock5d ...", file=sys.stderr)
    lock5_ss = SlowStressWithLockSignal(lock_days=5, inr_window=20, inr_threshold=0.01,
                                         vix_z_window=90, vix_z_threshold=1.5, vix_mom_window=5)
    df_l5 = run_active(lock5_ss, raw, START, END)

    print("Running Dynamic A ...", file=sys.stderr)
    _, dyna_posttax, _ = build_dyn_a(raw, START, END)

    r_l5 = df_l5["strategy_return"]
    r_da = dyna_posttax

    out = []
    def p(s=""): print(s); out.append(s)

    p("\n" + "=" * 130)
    p("  DRAWDOWN COMPARISON — C1+Lock5d vs Dynamic A")
    p("=" * 130)
    p()

    m_l5 = metrics(r_l5)
    m_da = metrics(r_da)
    dd_l5 = drawdown_series(r_l5)
    dd_da = drawdown_series(r_da)

    p("=" * 130)
    p("  HEADLINE DRAWDOWN METRICS")
    p("=" * 130)
    p(f"  {'Metric':<28} {'C1+Lock5d':>14} {'Dynamic A':>14} {'Difference':>14}")
    p("  " + "-"*28 + " " + "-"*14 + " " + "-"*14 + " " + "-"*14)
    p(f"  {'Max drawdown':<28} {m_l5['max_dd']*100:+13.2f}% {m_da['max_dd']*100:+13.2f}% {(m_l5['max_dd']-m_da['max_dd'])*100:+13.2f}pp")
    p(f"  {'Calmar (CAGR / |MaxDD|)':<28} {m_l5['calmar']:>13.2f}  {m_da['calmar']:>13.2f}  {m_l5['calmar']-m_da['calmar']:>+13.2f} ")
    p(f"  {'Avg DD (whole sample)':<28} {dd_l5.mean()*100:+13.2f}% {dd_da.mean()*100:+13.2f}% {(dd_l5.mean()-dd_da.mean())*100:+13.2f}pp")
    p(f"  {'Days in DD (% of total)':<28} {(dd_l5 < 0).mean()*100:>12.1f}% {(dd_da < 0).mean()*100:>12.1f}% {((dd_l5<0).mean()-(dd_da<0).mean())*100:+12.1f}pp")
    p(f"  {'Days DD > -5%':<28} {((dd_l5 < -0.05) & (dd_l5 >= -0.10)).sum():>14d} {((dd_da < -0.05) & (dd_da >= -0.10)).sum():>14d} {((dd_l5 < -0.05) & (dd_l5 >= -0.10)).sum() - ((dd_da < -0.05) & (dd_da >= -0.10)).sum():>+14d}")
    p(f"  {'Days DD > -10%':<28} {((dd_l5 < -0.10) & (dd_l5 >= -0.15)).sum():>14d} {((dd_da < -0.10) & (dd_da >= -0.15)).sum():>14d} {((dd_l5 < -0.10) & (dd_l5 >= -0.15)).sum() - ((dd_da < -0.10) & (dd_da >= -0.15)).sum():>+14d}")
    p(f"  {'Days DD < -15%':<28} {(dd_l5 < -0.15).sum():>14d} {(dd_da < -0.15).sum():>14d} {(dd_l5 < -0.15).sum() - (dd_da < -0.15).sum():>+14d}")
    p()

    p("=" * 130)
    p("  TOP 5 DRAWDOWN EPISODES — C1+Lock5d")
    p("=" * 130)
    p(f"  {'#':<3} {'Peak date':<12} {'Trough date':<12} {'Recovery date':<14} {'Min DD':>9} {'Trough days':>13}")
    p("  " + "-"*3 + " " + "-"*12 + " " + "-"*12 + " " + "-"*14 + " " + "-"*9 + " " + "-"*13)
    for i, ep in enumerate(top_drawdowns(r_l5, n=5), 1):
        rec = ep["recovery_date"].strftime('%Y-%m-%d') if ep["recovery_date"] else "(ongoing)"
        p(f"  {i:<3} {ep['peak_date'].strftime('%Y-%m-%d'):<12} {ep['trough_date'].strftime('%Y-%m-%d'):<12} {rec:<14} {ep['min_dd']*100:+8.2f}% {ep['trough_days']:>12d}d")
    p()

    p("=" * 130)
    p("  TOP 5 DRAWDOWN EPISODES — Dynamic A")
    p("=" * 130)
    p(f"  {'#':<3} {'Peak date':<12} {'Trough date':<12} {'Recovery date':<14} {'Min DD':>9} {'Trough days':>13}")
    p("  " + "-"*3 + " " + "-"*12 + " " + "-"*12 + " " + "-"*14 + " " + "-"*9 + " " + "-"*13)
    for i, ep in enumerate(top_drawdowns(r_da, n=5), 1):
        rec = ep["recovery_date"].strftime('%Y-%m-%d') if ep["recovery_date"] else "(ongoing)"
        p(f"  {i:<3} {ep['peak_date'].strftime('%Y-%m-%d'):<12} {ep['trough_date'].strftime('%Y-%m-%d'):<12} {rec:<14} {ep['min_dd']*100:+8.2f}% {ep['trough_days']:>12d}d")
    p()

    txt = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "results", "dd_compare_lock5d_dyna.txt")
    with open(txt, "w") as f:
        f.write("\n".join(out))
    print(f"\nSaved to {txt}", file=sys.stderr)


if __name__ == "__main__":
    main()
