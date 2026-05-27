"""
test_no_slow_stress.py — what does slow-stress actually earn the strategy?

Removes the SlowStressSignal entirely (no exit_no_cooldown signal at all).
Compares to baseline C1 across full 2008-2025 sample, year-by-year.

Other signals stay intact:
  - Entry signals: USDINR, IndiaVIX
  - Short signal: PanicShortSignal
  - Regime filter: NIFTY 100-DMA bull/bear
  - V2 overlay: NIFTY 50 hold for 60d after bear→bull flips with prior bear DD ≥15%
  - Gold rotation: only fires inside stress-flat windows, so it's effectively
    disabled too (no stress-flat = no gold)
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np
import pandas as pd

from strategy_lab import (
    MacroStrategyLab, RegimeFilter, SignalCombiner,
    USDINRSignal, IndiaVIXSignal, SlowStressSignal, PanicShortSignal,
    _load_data, metrics, build_rbi_repo_rate_series,
)


def build_combiner(include_slow_stress=True):
    rf = RegimeFilter(window=100)
    c = SignalCombiner(regime_filter=rf,
                       rotate_to_gold_on_stress_flat=True,
                       rotate_to_gold_on_panic_short=False,
                       rotate_with_momentum=True,
                       gold_gate_external=True)
    c.add_entry(USDINRSignal(window=10, threshold=0.01), weight=1.5)
    c.add_entry(IndiaVIXSignal(window=10, threshold=0.20), weight=1.5)
    if include_slow_stress:
        c.add_exit_no_cooldown(SlowStressSignal(
            inr_window=20, inr_threshold=0.01,
            vix_z_window=90, vix_z_threshold=1.5, vix_mom_window=5))
    c.add_short(PanicShortSignal(vix_level=25, vix_spike=0.50, window=10, dma=100),
                hold=False, max_hold_days=60, exit_ma_fast=5, exit_ma_slow=20)
    return c


def run_strategy(include_slow_stress, raw, start, end):
    combiner = build_combiner(include_slow_stress=include_slow_stress)
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
    return df.loc[start:end], diag


def main():
    START, END = "2008-04-01", "2025-12-31"
    raw = _load_data()

    print("Running C1 baseline (with slow-stress) ...", file=sys.stderr)
    df_base, _ = run_strategy(True, raw, START, END)
    print("Running C1 without slow-stress ...", file=sys.stderr)
    df_no_ss, _ = run_strategy(False, raw, START, END)

    out = []
    def p(s=""): print(s); out.append(s)

    p("\n" + "=" * 130)
    p("  HOW MUCH DOES SLOW-STRESS EARN THE STRATEGY?")
    p("=" * 130)
    p()
    p("  Compare C1 baseline (slow-stress ON) vs C1 with slow-stress REMOVED.")
    p("  All other signals (entry, regime, panic-short, V2, gold-rotation) intact.")
    p("  Gold rotation only fires inside stress-flat windows, so removing")
    p("  slow-stress effectively removes gold rotation too (in 2008-2025).")
    p()

    p("=" * 130)
    p("  HEADLINE METRICS (post-tax, 2008-04-01 → 2025-12-31)")
    p("=" * 130)
    p(f"  {'Variant':<28} {'CAGR':>9} {'Sharpe':>8} {'Calmar':>8} {'MaxDD':>9} {'Vol':>8} {'ΔCAGR':>9}")
    p("  " + "-"*28 + " " + "-"*9 + " " + "-"*8 + " " + "-"*8 + " " + "-"*9 + " " + "-"*8 + " " + "-"*9)
    m_base = metrics(df_base["strategy_return"])
    m_no = metrics(df_no_ss["strategy_return"])
    p(f"  {'C1 baseline (SS ON)':<28} {m_base['cagr']*100:+7.2f}% {m_base['sharpe']:>8.3f} {m_base['calmar']:>8.2f} {m_base['max_dd']*100:+8.2f}% {m_base['vol']*100:>7.2f}% {'—':>9}")
    dc = m_no['cagr'] - m_base['cagr']
    p(f"  {'C1 without slow-stress':<28} {m_no['cagr']*100:+7.2f}% {m_no['sharpe']:>8.3f} {m_no['calmar']:>8.2f} {m_no['max_dd']*100:+8.2f}% {m_no['vol']*100:>7.2f}% {dc*100:+8.2f}pp")
    p()
    p(f"  → Slow-stress earns the strategy: {-dc*100:+.2f}pp CAGR  (positive = SS helps)")
    p(f"  → Slow-stress impact on Sharpe:   {(m_base['sharpe']-m_no['sharpe']):+.3f}")
    p(f"  → Slow-stress impact on MaxDD:    {(m_no['max_dd']-m_base['max_dd'])*100:+.2f}pp  (positive = SS protects)")
    p()

    p("=" * 130)
    p("  YEAR-BY-YEAR")
    p("=" * 130)
    nifty_close = raw["^NSEI"].loc[START:END]
    p(f"  {'Year':<6} {'C1 (SS ON)':>12} {'C1 (no SS)':>12} {'Δ (no SS −SS)':>16} {'NIFTY':>9}")
    p("  " + "-"*6 + " " + "-"*12 + " " + "-"*12 + " " + "-"*16 + " " + "-"*9)
    for y in sorted(set(df_base.index.year)):
        s_base = df_base["strategy_return"][df_base.index.year == y]
        s_no = df_no_ss["strategy_return"][df_no_ss.index.year == y]
        b = float((1+s_base).prod()-1)*100
        n = float((1+s_no).prod()-1)*100
        ny = nifty_close[nifty_close.index.year == y]
        nv = float(ny.iloc[-1]/ny.iloc[0]-1)*100 if len(ny)>1 else 0
        diff = n - b
        marker = "  ← SS HELPED" if diff < -1 else ("  ← SS HURT" if diff > 1 else "")
        p(f"  {y:<6} {b:>+10.2f}% {n:>+10.2f}% {diff:>+14.2f}pp {nv:>+7.2f}%{marker}")
    p()

    # Flat-day count comparison
    p("=" * 130)
    p("  FLAT-DAY COUNTS (how often each variant was forced flat)")
    p("=" * 130)
    p(f"  {'Year':<6} {'C1 flat days':>14} {'No-SS flat days':>17} {'Difference':>12}")
    p("  " + "-"*6 + " " + "-"*14 + " " + "-"*17 + " " + "-"*12)
    for y in sorted(set(df_base.index.year)):
        np_base = df_base["nifty_position"][df_base.index.year == y]
        np_no = df_no_ss["nifty_position"][df_no_ss.index.year == y]
        f_base = int(((np_base == 0.0) & (df_base["gold_position"][df_base.index.year == y] == 0.0)).sum())
        f_no = int(((np_no == 0.0) & (df_no_ss["gold_position"][df_no_ss.index.year == y] == 0.0)).sum())
        p(f"  {y:<6} {f_base:>13d} {f_no:>16d} {(f_no - f_base):>+11d}")
    p()

    # Cumulative growth $1
    p("=" * 130)
    p("  CUMULATIVE GROWTH OF ₹1 (post-tax)")
    p("=" * 130)
    base_cum = (1 + df_base["strategy_return"]).cumprod().iloc[-1]
    no_cum = (1 + df_no_ss["strategy_return"]).cumprod().iloc[-1]
    nifty_cum = nifty_close.iloc[-1] / nifty_close.iloc[0]
    p(f"  C1 baseline (SS ON):    ₹1 → ₹{base_cum:.2f}   ({(base_cum-1)*100:+.0f}%)")
    p(f"  C1 without slow-stress: ₹1 → ₹{no_cum:.2f}   ({(no_cum-1)*100:+.0f}%)")
    p(f"  NIFTY 50 buy-and-hold:  ₹1 → ₹{nifty_cum:.2f}   ({(nifty_cum-1)*100:+.0f}%)")
    p()
    p(f"  Slow-stress contribution to ₹1: ₹{base_cum - no_cum:+.2f}  "
      f"({(base_cum/no_cum - 1)*100:+.1f}% multiplier)")
    p()

    txt = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "results", "test_no_slow_stress.txt")
    with open(txt, "w") as f:
        f.write("\n".join(out))
    print(f"\nSaved to {txt}", file=sys.stderr)


if __name__ == "__main__":
    main()
