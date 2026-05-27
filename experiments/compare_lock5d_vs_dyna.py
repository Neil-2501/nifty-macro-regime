"""
compare_lock5d_vs_dyna.py — final comparison: C1+Lock5d vs C1 vs Dynamic A vs NIFTY B&H.

Dynamic A: NIFTY > 100-DMA → 100% Mom30, else cash. 6bps cost to enter/exit.
           Same 15% short-term tax model as the active strategies.
NIFTY B&H: no rebalance; uses 10% long-term cap gains tax.
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np
import pandas as pd

from strategy_lab import (
    MacroStrategyLab, RegimeFilter, SignalCombiner,
    USDINRSignal, IndiaVIXSignal, SlowStressSignal, PanicShortSignal,
    _load_data, metrics, apply_annual_tax,
)
from test_min_hold_after_stress import SlowStressWithLockSignal


def build_combiner(slow_stress_signal):
    rf = RegimeFilter(window=100)
    c = SignalCombiner(regime_filter=rf,
                       rotate_to_gold_on_stress_flat=True,
                       rotate_to_gold_on_panic_short=False,
                       rotate_with_momentum=True,
                       gold_gate_external=True)
    c.add_entry(USDINRSignal(window=10, threshold=0.01), weight=1.5)
    c.add_entry(IndiaVIXSignal(window=10, threshold=0.20), weight=1.5)
    c.add_exit_no_cooldown(slow_stress_signal)
    c.add_short(PanicShortSignal(vix_level=25, vix_spike=0.50, window=10, dma=100),
                hold=False, max_hold_days=60, exit_ma_fast=5, exit_ma_slow=20)
    return c


def run_active(slow_stress, raw, start, end):
    combiner = build_combiner(slow_stress)
    s = MacroStrategyLab(
        combiner,
        target="^NSEI", gold_target="GOLDBEES.NS",
        long_target="NIFTYMOM30", long_cost_bps=6,
        nifty_cost_bps=3, gold_cost_bps=5,
        cash_yield_haircut_bps=100,
        apply_tax=True, tax_rate=0.15,
        enable_v2=True, v2_dd_threshold=0.15, v2_days=60,
        recovery_latch=None, recovery_allocation="mom_gold_blend",
        vol_target_annual=0.15, vol_window=60,
    )
    result = s.run(raw)
    df, diag = result if isinstance(result, tuple) else (result, {})
    return df.loc[start:end]


def build_dyn_a(raw, start, end):
    """Dynamic A: NIFTY > 100-DMA → Mom30, else cash."""
    raw_window = raw.loc[:end]
    idx = raw.loc[start:end].index

    ret_mom = raw_window["NIFTYMOM30"].pct_change().fillna(0.0)
    ret_nif = raw_window["^NSEI"].pct_change().fillna(0.0)
    # Cash yield from RBI repo
    from strategy_lab import build_rbi_repo_rate_series
    repo = build_rbi_repo_rate_series(raw_window.index)
    haircut = (repo - 0.01).clip(lower=0)
    ret_cash = haircut / 252

    rf = RegimeFilter(window=100)
    bull = rf.bull_mask(raw_window).reindex(idx).fillna(False)
    pos = bull.astype(float)

    ret_mom = ret_mom.reindex(idx)
    ret_cash = ret_cash.reindex(idx)

    pretax = (
        pos.shift(1, fill_value=0.0) * ret_mom
        + (1 - pos.shift(1, fill_value=0.0)) * ret_cash
        - pos.diff().abs().fillna(0) * 6/10000
    )
    posttax = apply_annual_tax(pretax.fillna(0.0), tax_rate=0.15)
    return pretax, posttax, pos


def main():
    START, END = "2008-04-01", "2025-12-31"
    raw = _load_data()

    print("Running C1 baseline ...", file=sys.stderr)
    base_ss = SlowStressSignal(inr_window=20, inr_threshold=0.01,
                               vix_z_window=90, vix_z_threshold=1.5, vix_mom_window=5)
    df_c1 = run_active(base_ss, raw, START, END)

    print("Running C1 + Lock 5d ...", file=sys.stderr)
    lock5_ss = SlowStressWithLockSignal(lock_days=5, inr_window=20, inr_threshold=0.01,
                                         vix_z_window=90, vix_z_threshold=1.5, vix_mom_window=5)
    df_l5 = run_active(lock5_ss, raw, START, END)

    print("Running Dynamic A ...", file=sys.stderr)
    dyna_pretax, dyna_posttax, dyna_pos = build_dyn_a(raw, START, END)

    # NIFTY B&H — pretax + 10% LT cap gains tax
    nifty_close = raw["^NSEI"].loc[START:END]
    nifty_pretax = nifty_close.pct_change().fillna(0.0)
    nifty_posttax_lt = apply_annual_tax(nifty_pretax, tax_rate=0.10)

    out = []
    def p(s=""): print(s); out.append(s)

    p("\n" + "=" * 140)
    p("  FINAL COMPARISON — C1+Lock5d vs C1 baseline vs Dynamic A vs NIFTY B&H")
    p("=" * 140)
    p()
    p("  C1+Lock5d:  production v1.5 + V2 overlay + 5-day slow-stress lock (new candidate)")
    p("  C1:         production v1.5 + V2 overlay (current production)")
    p("  Dynamic A:  NIFTY 50 > 100-DMA → 100% Mom30, else cash. 6 bps cost. 15% tax.")
    p("  NIFTY B&H:  no rebalance; 10% long-term cap gains tax.")
    p()

    p("=" * 140)
    p("  HEADLINE METRICS (post-tax, 2008-04-01 → 2025-12-31)")
    p("=" * 140)
    p(f"  {'Variant':<18} {'CAGR':>9} {'Sharpe':>8} {'Calmar':>8} {'MaxDD':>9} {'Vol':>8} {'₹1 →':>10}")
    p("  " + "-"*18 + " " + "-"*9 + " " + "-"*8 + " " + "-"*8 + " " + "-"*9 + " " + "-"*8 + " " + "-"*10)
    for name, series in [
        ("C1+Lock5d (NEW)", df_l5["strategy_return"]),
        ("C1 baseline",     df_c1["strategy_return"]),
        ("Dynamic A",       dyna_posttax),
        ("NIFTY B&H (LT)",  nifty_posttax_lt),
    ]:
        m = metrics(series)
        cum = (1 + series).cumprod().iloc[-1]
        p(f"  {name:<18} {m['cagr']*100:+7.2f}% {m['sharpe']:>8.3f} {m['calmar']:>8.2f} {m['max_dd']*100:+8.2f}% {m['vol']*100:>7.2f}% ₹{cum:>7.2f}")
    p()

    # Δ vs Dynamic A
    p("=" * 140)
    p("  Δ vs DYNAMIC A (positive = active strategy beats benchmark)")
    p("=" * 140)
    m_dyna = metrics(dyna_posttax)
    p(f"  {'Variant':<18} {'ΔCAGR':>9} {'ΔSharpe':>9} {'ΔMaxDD':>10}")
    p("  " + "-"*18 + " " + "-"*9 + " " + "-"*9 + " " + "-"*10)
    for name, series in [
        ("C1+Lock5d (NEW)", df_l5["strategy_return"]),
        ("C1 baseline",     df_c1["strategy_return"]),
    ]:
        m = metrics(series)
        dc = m["cagr"] - m_dyna["cagr"]
        ds = m["sharpe"] - m_dyna["sharpe"]
        dd = m["max_dd"] - m_dyna["max_dd"]  # positive = active has shallower DD (better)
        p(f"  {name:<18} {dc*100:+7.2f}pp {ds:+8.3f} {dd*100:+8.2f}pp")
    p()

    p("=" * 140)
    p("  YEAR-BY-YEAR (post-tax %, all variants)")
    p("=" * 140)
    p(f"  {'Year':<6} {'C1+Lock5d':>11} {'C1 base':>10} {'Dyn A':>10} {'NIFTY':>10} {'Lock-DynA':>11} {'C1-DynA':>10}")
    p("  " + "-"*6 + " " + "-"*11 + " " + "-"*10 + " " + "-"*10 + " " + "-"*10 + " " + "-"*11 + " " + "-"*10)
    for y in sorted(set(df_c1.index.year)):
        l5 = float((1 + df_l5["strategy_return"][df_l5.index.year == y]).prod() - 1) * 100
        c1 = float((1 + df_c1["strategy_return"][df_c1.index.year == y]).prod() - 1) * 100
        da = float((1 + dyna_posttax[dyna_posttax.index.year == y]).prod() - 1) * 100
        nb = float((1 + nifty_posttax_lt[nifty_posttax_lt.index.year == y]).prod() - 1) * 100
        ld = l5 - da
        cd = c1 - da
        p(f"  {y:<6} {l5:>+9.2f}% {c1:>+8.2f}% {da:>+8.2f}% {nb:>+8.2f}% {ld:>+9.2f}pp {cd:>+8.2f}pp")
    p()

    # Win counts: which variant won each year
    p("=" * 140)
    p("  WIN COUNT — which variant had best return each year")
    p("=" * 140)
    win_counts = {"C1+Lock5d": 0, "C1 base": 0, "Dyn A": 0, "NIFTY": 0}
    for y in sorted(set(df_c1.index.year)):
        l5 = float((1 + df_l5["strategy_return"][df_l5.index.year == y]).prod() - 1)
        c1 = float((1 + df_c1["strategy_return"][df_c1.index.year == y]).prod() - 1)
        da = float((1 + dyna_posttax[dyna_posttax.index.year == y]).prod() - 1)
        nb = float((1 + nifty_posttax_lt[nifty_posttax_lt.index.year == y]).prod() - 1)
        scores = {"C1+Lock5d": l5, "C1 base": c1, "Dyn A": da, "NIFTY": nb}
        winner = max(scores, key=scores.get)
        win_counts[winner] += 1
    p(f"  Years (out of {len(set(df_c1.index.year))}) where each variant was the best:")
    for name, count in sorted(win_counts.items(), key=lambda x: -x[1]):
        p(f"    {name:<14}  {count} years")
    p()

    txt = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "results", "compare_lock5d_vs_dyna.txt")
    with open(txt, "w") as f:
        f.write("\n".join(out))
    print(f"\nSaved to {txt}", file=sys.stderr)


if __name__ == "__main__":
    main()
