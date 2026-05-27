"""
test_nifty_instead_of_mom30.py — what does Mom30 actually contribute?

Two parts:
  Part A: Run Strategy v2.0 (Config 7) but replace NIFTYMOM30 with NIFTY 50
          as the long-side asset. Everything else identical (gold rotation,
          panic-short, slow-stress lock, V2 overlay, costs). Compare year-by-
          year vs Mom30 production.
  Part B: Within 2009 under the Mom30 production, identify exactly when V2
          ended and the strategy switched from holding NIFTY 50 (V2 hold)
          back to Mom30.

Doesn't modify strategy.py. Self-contained experiment using the public
production class.
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd

import strategy as s
from strategy_lab import _load_data


def run_v20(raw, long_target, long_cost_bps):
    """Run Config 7 (v2.0 production) with a chosen long-side asset."""
    combiner = s.make_combiner(rotate_stress=True, rotate_panic=False,
                                use_momentum_gold=True,
                                slow_stress_lock_days=5)
    strat = s.MacroStrategy(combiner, nifty_cost_bps=3, gold_cost_bps=5,
                             long_target=long_target, long_cost_bps=long_cost_bps,
                             enable_v2=True, v2_dd_threshold=0.15, v2_days=60)
    return strat.run(raw).loc["2008-04-01":"2025-12-31"]


def main():
    raw = _load_data()

    print("Running v2.0 with NIFTYMOM30 (current production) ...", file=sys.stderr)
    df_mom = run_v20(raw, long_target="NIFTYMOM30", long_cost_bps=6)

    print("Running v2.0 with NIFTY 50 (NIFTY instead of Mom30) ...", file=sys.stderr)
    df_nif = run_v20(raw, long_target="^NSEI", long_cost_bps=3)

    out = []
    def p(text=""): print(text); out.append(text)

    # =================================================================
    # PART A — NIFTY 50 long-side vs Mom30 long-side
    # =================================================================
    p("\n" + "=" * 130)
    p("  PART A — v2.0 with NIFTY 50 long-side vs v2.0 with NIFTYMOM30 long-side")
    p("=" * 130)
    p()
    p("  Both variants identical except the long-side asset (and its cost).")
    p("    Production: NIFTYMOM30, 6 bps cost")
    p("    Variant:    ^NSEI (NIFTY 50), 3 bps cost")
    p("  V2 windows still hold NIFTY 50 in both → V2 days have same allocation.")
    p()

    m_mom = s.metrics(df_mom["strategy_return"])
    m_nif = s.metrics(df_nif["strategy_return"])
    cum_mom = (1 + df_mom["strategy_return"]).cumprod().iloc[-1]
    cum_nif = (1 + df_nif["strategy_return"]).cumprod().iloc[-1]

    p("=" * 130)
    p("  HEADLINE METRICS (post-tax, 2008-04-01 → 2025-12-31)")
    p("=" * 130)
    p(f"  {'Metric':<22} {'v2.0 (Mom30 PROD)':>20} {'v2.0 (NIFTY 50)':>18} {'Δ (NIFTY − Mom30)':>20}")
    p("  " + "-"*22 + " " + "-"*20 + " " + "-"*18 + " " + "-"*20)
    p(f"  {'CAGR':<22} {m_mom['cagr']*100:>+18.2f}%  {m_nif['cagr']*100:>+16.2f}%  {(m_nif['cagr']-m_mom['cagr'])*100:>+18.2f}pp")
    p(f"  {'Sharpe':<22} {m_mom['sharpe']:>20.3f} {m_nif['sharpe']:>18.3f} {m_nif['sharpe']-m_mom['sharpe']:>+19.3f}")
    p(f"  {'Calmar':<22} {m_mom['calmar']:>20.2f} {m_nif['calmar']:>18.2f} {m_nif['calmar']-m_mom['calmar']:>+19.2f}")
    p(f"  {'Max drawdown':<22} {m_mom['max_dd']*100:>+18.2f}% {m_nif['max_dd']*100:>+16.2f}% {(m_nif['max_dd']-m_mom['max_dd'])*100:>+18.2f}pp")
    p(f"  {'Ann. vol':<22} {m_mom['vol']*100:>+18.2f}% {m_nif['vol']*100:>+16.2f}% {(m_nif['vol']-m_mom['vol'])*100:>+18.2f}pp")
    p(f"  {'Rs1 →':<22} Rs{cum_mom:>17.2f}  Rs{cum_nif:>15.2f}  Rs{cum_nif-cum_mom:>+17.2f}")
    p()

    # Year-by-year
    p("=" * 130)
    p("  YEAR-BY-YEAR")
    p("=" * 130)
    p(f"  {'Year':<6} {'v2.0 Mom30 (PROD)':>20} {'v2.0 NIFTY 50':>16} {'Δ NIFTY − Mom30':>17}  Winner")
    p("  " + "-"*6 + " " + "-"*20 + " " + "-"*16 + " " + "-"*17 + "  " + "-"*8)
    mom_wins = 0; nif_wins = 0; ties = 0
    for y in sorted(set(df_mom.index.year)):
        mr = float((1 + df_mom["strategy_return"][df_mom.index.year == y]).prod() - 1) * 100
        nr = float((1 + df_nif["strategy_return"][df_nif.index.year == y]).prod() - 1) * 100
        diff = nr - mr
        if abs(diff) < 0.05:
            winner = "(tie)"; ties += 1
        elif mr > nr:
            winner = "Mom30 ← v2.0 wins"; mom_wins += 1
        else:
            winner = "NIFTY"; nif_wins += 1
        p(f"  {y:<6} {mr:>+18.2f}% {nr:>+14.2f}% {diff:>+16.2f}pp  {winner}")
    p()
    p(f"  Win count: Mom30-v2.0 = {mom_wins}, NIFTY-v2.0 = {nif_wins}, ties = {ties}")
    p()

    # Aggregate Mom30 contribution
    p("=" * 130)
    p("  WHERE MOM30 ADDED VS WHERE IT COST (vs holding NIFTY 50)")
    p("=" * 130)
    pos_diffs = []; neg_diffs = []
    for y in sorted(set(df_mom.index.year)):
        mr = float((1 + df_mom["strategy_return"][df_mom.index.year == y]).prod() - 1) * 100
        nr = float((1 + df_nif["strategy_return"][df_nif.index.year == y]).prod() - 1) * 100
        diff = mr - nr      # positive = Mom30 won that year
        if diff > 0.05:
            pos_diffs.append((y, diff))
        elif diff < -0.05:
            neg_diffs.append((y, diff))
    p(f"  Years Mom30 BEAT NIFTY 50 ({len(pos_diffs)}):")
    for y, d in sorted(pos_diffs, key=lambda x: -x[1]):
        p(f"      {y}: Mom30 added +{d:.2f}pp")
    p()
    p(f"  Years Mom30 LOST to NIFTY 50 ({len(neg_diffs)}):")
    for y, d in sorted(neg_diffs, key=lambda x: x[1]):
        p(f"      {y}: Mom30 cost {d:.2f}pp")
    p()
    p(f"  Net Mom30 contribution (arithmetic sum): {sum(d for _, d in pos_diffs + neg_diffs):+.2f}pp across {len(pos_diffs)+len(neg_diffs)} years")
    p()

    # =================================================================
    # PART B — when did V2 end in 2009 under v2.0 production?
    # =================================================================
    p("=" * 130)
    p("  PART B — 2009 V2 timeline (under v2.0 Mom30 production)")
    p("=" * 130)
    p()
    p("  V2 overlay = after bear→bull flip with prior bear DD ≥ 15%, hold NIFTY 50")
    p("  for 60 trading days, then revert to Mom30 (the long-side default).")
    p()
    v2_2009 = df_mom[df_mom.index.year == 2009]["v2_active"]
    v2_active_days = v2_2009[v2_2009].index
    if len(v2_active_days) == 0:
        p("  No V2-active days in 2009!")
    else:
        first_v2 = v2_active_days[0]
        last_v2 = v2_active_days[-1]
        p(f"  V2 first active day in 2009: {first_v2.date()}")
        p(f"  V2 last active day in 2009:  {last_v2.date()}")
        p(f"  V2 active days in 2009:      {len(v2_active_days)}")
        p()

        # Find the actual switch-back date — first LONG day after last V2 day
        long_2009 = df_mom[df_mom.index.year == 2009]
        # First non-V2 LONG day after V2 ends
        post_v2 = long_2009.loc[long_2009.index > last_v2]
        first_mom_day = post_v2[(post_v2["nifty_position"] == 1.0) & (~post_v2["v2_active"])]
        if len(first_mom_day) > 0:
            switch_back = first_mom_day.index[0]
            p(f"  → SWITCH BACK TO MOM30: first day v2.0 holds Mom30 again in 2009 = {switch_back.date()}")
        else:
            p(f"  → No Mom30-only LONG days after V2 ended in 2009 (V2 might extend into 2010)")
        p()

        # Show the state day-by-day around the transition
        p("  Daily state transitions around V2 end:")
        p(f"    {'Date':<12} {'Position':<10} {'V2 active?':<12} {'Asset held':<14} {'NIFTY 50':>10} {'Mom30':>10}")
        p("    " + "-"*12 + " " + "-"*10 + " " + "-"*12 + " " + "-"*14 + " " + "-"*10 + " " + "-"*10)
        # Show last 5 V2 days + next 10 days
        target_dates = list(v2_active_days[-5:])
        # Add next 10 trading days
        all_idx = df_mom.index
        last_pos = all_idx.get_loc(last_v2)
        for i in range(last_pos + 1, min(last_pos + 11, len(all_idx))):
            target_dates.append(all_idx[i])
        for d in target_dates:
            row = df_mom.loc[d]
            pos = row["nifty_position"]
            v2 = bool(row["v2_active"])
            pos_str = "LONG" if pos == 1.0 else ("SHORT" if pos == -1.0 else "FLAT")
            if pos == 1.0 and v2:
                asset = "NIFTY 50 (V2)"
            elif pos == 1.0 and not v2:
                asset = "Mom30"
            elif pos == -1.0:
                asset = "NIFTY 50 (short)"
            else:
                gold = row.get("gold_position", 0.0)
                asset = "Gold" if gold == 1.0 else "Cash"
            nif_close = raw["^NSEI"].loc[d]
            mom_close = raw["NIFTYMOM30"].loc[d]
            p(f"    {d.date()!s:<12} {pos_str:<10} {str(v2):<12} {asset:<14} {nif_close:>10.0f} {mom_close:>10.0f}")
        p()

        # Show NIFTY and Mom30 cumulative during V2 window for context
        v2_window_data = df_mom.loc[first_v2:last_v2]
        nif_cum = (raw["^NSEI"].loc[first_v2:last_v2].iloc[-1] / raw["^NSEI"].loc[first_v2]) - 1
        mom_cum = (raw["NIFTYMOM30"].loc[first_v2:last_v2].iloc[-1] / raw["NIFTYMOM30"].loc[first_v2]) - 1
        p(f"  Context — cumulative returns during V2 window ({first_v2.date()} → {last_v2.date()}):")
        p(f"    NIFTY 50: {nif_cum*100:+.2f}%   (what V2 captured)")
        p(f"    Mom30:    {mom_cum*100:+.2f}%   (counterfactual: what default would have captured)")
        p(f"    Δ:        {(mom_cum - nif_cum)*100:+.2f}pp  (positive = Mom30 would have done better; negative = V2 was right)")
        p()

    # Save
    txt = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "results", "test_nifty_instead_of_mom30.txt")
    with open(txt, "w") as f:
        f.write("\n".join(out))
    print(f"\nSaved to {txt}", file=sys.stderr)


if __name__ == "__main__":
    main()
