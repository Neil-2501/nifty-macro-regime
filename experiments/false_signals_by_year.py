"""
false_signals_by_year.py — how much do FALSE bear-regime / slow-stress /
panic-short fires cost us in 2013, 2019, 2022, 2025?

Uses results/all_transitions_summary.csv. For each year, decompose by:
  - cause (regime bear, regime bull-clear, slow-stress, panic-short, v2, g10)
  - verdict (WORKED, NEUTRAL, FALSE)

Cost convention (in pp, NIFTY-relative):
  Defensive transition (LONG → FLAT/SHORT/GOLD):
    cost = NIFTY's next-20d return − strategy's next-20d return
    Positive = we missed a rally (bad). Negative = we avoided a drop (good).
  Risk-on transition (FLAT/SHORT/GOLD → LONG):
    cost = -strategy's next-20d return
    Positive = we entered before a drop (bad). Negative = we entered before a rally (good).

Sum of costs across all transitions ≈ year's underperformance vs B&H from
signal mistiming, ignoring entry-lag (which is separate).

NOTE: based on C1 baseline data. L5 production blocks ~30% of slow-stress
fires; net effect already in the year-level production returns.
"""

import os
import pandas as pd
import numpy as np

RESULTS_DIR = os.path.normpath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "results"))

trans = pd.read_csv(os.path.join(RESULTS_DIR, "all_transitions_summary.csv"),
                    parse_dates=["date"])

# Cost calc
def cost_pp(row):
    f_n = float(row["f20_n"]) if pd.notna(row["f20_n"]) else 0
    f_s = float(row["f20_strat"]) if pd.notna(row["f20_strat"]) else 0
    if row["from"] in ("LONG", "LONG_V2") and row["to"] in ("FLAT", "SHORT", "GOLD"):
        return f_n - f_s
    if row["from"] in ("FLAT", "SHORT", "GOLD") and row["to"] in ("LONG", "LONG_V2"):
        return -f_s
    if row["to"] == "SHORT":
        return 2 * f_n
    return 0.0

trans["cost_pp"] = trans.apply(cost_pp, axis=1)
trans["verdict_class"] = trans["verdict"].apply(lambda v: v.split(" ")[0])

# Normalize cause names
def norm_cause(c):
    c = str(c).lower()
    if "slow-stress" in c: return "slow-stress"
    if "panic" in c: return "panic-short"
    if "regime (bear)" in c: return "regime bear→flat"
    if "regime (bull)" in c: return "regime bull→long"
    if "v2" in c: return "v2 overlay"
    if "g10" in c or "gold" in c: return "gold rotation"
    return c

trans["cause_norm"] = trans["cause"].apply(norm_cause)

YEARS = [2013, 2019, 2022, 2025]

out = []
def p(t=""): print(t); out.append(t)

p("=" * 130)
p("  FALSE SIGNALS COST DECOMPOSITION — 2013, 2019, 2022, 2025")
p("=" * 130)
p()
p("  Each transition is classified as WORKED / NEUTRAL / FALSE based on whether")
p("  the next 20 trading days vindicated the move. Cost in pp = NIFTY-relative loss")
p("  attributable to that signal.")
p()

# Per-year breakdown
for y in YEARS:
    yt = trans[trans["year"] == y].copy()
    p("=" * 130)
    p(f"  {y} — {len(yt)} transitions total")
    p("=" * 130)
    p()

    # By cause × verdict
    by_cv = yt.groupby(["cause_norm", "verdict_class"]).agg(
        n=("date", "count"),
        cost=("cost_pp", lambda x: x.sum() * 100)
    ).reset_index()

    p(f"  {'Cause':<22} {'Verdict':<10} {'Count':>6} {'Total cost (pp)':>18}  Interpretation")
    p("  " + "-"*22 + " " + "-"*10 + " " + "-"*6 + " " + "-"*18 + "  " + "-"*30)
    for _, r in by_cv.sort_values(["cause_norm", "verdict_class"]).iterrows():
        n = int(r['n']); cost = r['cost']
        if r['verdict_class'] == "FALSE":
            interp = "WRONG signal — cost us money" if cost > 0 else "wrong direction but cheap"
        elif r['verdict_class'] == "WORKED":
            interp = "RIGHT signal — saved/made money" if cost < 0 else "right but small effect"
        else:
            interp = "neutral / mixed"
        p(f"  {r['cause_norm']:<22} {r['verdict_class']:<10} {n:>6d} {cost:>+16.2f}pp  {interp}")
    p()

    # Net signal cost (sum of all false signals)
    false_only = yt[yt["verdict_class"] == "FALSE"]
    worked_only = yt[yt["verdict_class"] == "WORKED"]
    p(f"  Total FALSE signal cost: {(false_only['cost_pp'].sum() * 100):+.2f}pp "
      f"({len(false_only)} transitions)")
    p(f"  Total WORKED signal benefit: {(worked_only['cost_pp'].sum() * 100):+.2f}pp "
      f"({len(worked_only)} transitions, negative = saved money)")
    p(f"  Net (false + worked): {((false_only['cost_pp'].sum() + worked_only['cost_pp'].sum()) * 100):+.2f}pp")
    p()

    # The WORKED signals — what saved us
    if len(worked_only):
        p(f"  Top WORKED signals in {y} (the ones that saved/made money):")
        for _, r in worked_only.nsmallest(5, "cost_pp").iterrows():
            p(f"    {r['date'].strftime('%Y-%m-%d')}: {r['from']} → {r['to']} via {r['cause']}, "
              f"saved {r['cost_pp']*100:+.2f}pp")
        p()

    # FALSE signals
    if len(false_only):
        p(f"  Top FALSE signals in {y} (the ones that cost us money):")
        for _, r in false_only.nlargest(5, "cost_pp").iterrows():
            p(f"    {r['date'].strftime('%Y-%m-%d')}: {r['from']} → {r['to']} via {r['cause']}, "
              f"cost {r['cost_pp']*100:+.2f}pp")
        p()

# Cross-year summary
p("=" * 130)
p("  CROSS-YEAR FALSE-SIGNAL COST BY CAUSE")
p("=" * 130)
p(f"  {'Year':<6} {'Slow-stress':>14} {'Bear regime':>14} {'Bull regime':>14} "
  f"{'Panic-short':>14} {'V2':>10}")
p("  " + "-"*6 + " " + "-"*14 + " " + "-"*14 + " " + "-"*14 + " " + "-"*14 + " " + "-"*10)
for y in YEARS:
    yt = trans[(trans["year"] == y) & (trans["verdict_class"] == "FALSE")]
    row = f"  {y:<6}"
    for cause in ["slow-stress", "regime bear→flat", "regime bull→long",
                  "panic-short", "v2 overlay"]:
        c = yt[yt["cause_norm"] == cause]["cost_pp"].sum() * 100
        row += f" {c:>+12.2f}pp"
    p(row)
p()

# Total false-signal cost by year
p("=" * 130)
p("  TOTAL FALSE-SIGNAL COST BY YEAR (sum of all false transitions)")
p("=" * 130)
for y in YEARS:
    yt = trans[(trans["year"] == y) & (trans["verdict_class"] == "FALSE")]
    cost = yt["cost_pp"].sum() * 100
    p(f"  {y}: {len(yt)} false transitions, total cost {cost:+.2f}pp")
p()

txt = os.path.join(RESULTS_DIR, "false_signals_by_year.txt")
with open(txt, "w") as f:
    f.write("\n".join(out))
print(f"\nSaved to {txt}")
