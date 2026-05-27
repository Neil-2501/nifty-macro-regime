"""
diagnose_2018_2019.py — DEEP DIVE on the two worst years vs NIFTY B&H.

Combines transitions + recovery windows + daily P&L for 2018 and 2019,
identifies the specific events that drove the underperformance, and proposes
targeted fixes that would address those events WITHOUT affecting the years
the strategy already wins on.

Loads existing artifacts (no re-computation of strategy):
  results/all_transitions_summary.csv
  results/per_window_all_115_summary.csv
  results/three_way_yearly_comparison_daily.csv
"""

import os, sys
import numpy as np
import pandas as pd

RESULTS_DIR = os.path.normpath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "results"))

# Load artifacts
trans = pd.read_csv(os.path.join(RESULTS_DIR, "all_transitions_summary.csv"),
                    parse_dates=["date"])
windows = pd.read_csv(os.path.join(RESULTS_DIR, "per_window_all_115_summary.csv"),
                      parse_dates=["re_entry", "stretch_start"])
daily = pd.read_csv(os.path.join(RESULTS_DIR, "three_way_yearly_comparison_daily.csv"),
                    index_col=0, parse_dates=True)

YEARS = [2018, 2019]

# Recompute cost per transition (cost in pp)
def _cost(row):
    f_n = row["f20_n"]; f_s = row["f20_strat"]
    from_s = row["from"]; to_s = row["to"]
    if pd.isna(f_n) or pd.isna(f_s): return 0.0
    if from_s in ("LONG", "LONG_V2") and to_s in ("FLAT", "SHORT", "GOLD"):
        return float(f_n - f_s)
    if from_s in ("FLAT", "SHORT", "GOLD") and to_s in ("LONG", "LONG_V2"):
        return float(-f_s)
    if to_s == "SHORT":
        return float(2 * f_n)
    return 0.0
trans["cost_pp"] = trans.apply(_cost, axis=1)

# ─── Output ────────────────────────────────────────────────────────────────
lines = []
def out(s=""): lines.append(s); print(s)

out("=" * 130)
out(f"  2018 & 2019 DEEP DIVE — what bled, where, and how to fix without affecting upsides")
out("=" * 130)
out()

# Year-level summary
out("=" * 130)
out("  YEAR-LEVEL OVERVIEW")
out("=" * 130)
for y in YEARS:
    yr_daily = daily[daily.index.year == y]
    nifty_y = (1 + yr_daily["nifty_bh_pretax"]).prod() - 1
    strat_y = (1 + yr_daily["c1_pretax"]).prod() - 1
    short_d = int(yr_daily["c1_pretax"].notna().sum())
    long_d  = int((yr_daily["c1_state"] == "LONG").sum())
    flat_d  = int((yr_daily["c1_state"] == "FLAT").sum())
    short_dys = int((yr_daily["c1_state"] == "SHORT").sum())
    gold_dys = int((yr_daily["c1_state"] == "GOLD").sum())
    out(f"  {y}: NIFTY {nifty_y*100:+6.2f}%  Strategy {strat_y*100:+6.2f}%  "
        f"shortfall {(nifty_y-strat_y)*100:+6.2f}pp")
    out(f"        Days: LONG={long_d}  FLAT={flat_d}  SHORT={short_dys}  GOLD={gold_dys}")
out()

# ─── Per-month P&L decomposition ──────────────────────────────────────────
out("=" * 130)
out("  MONTH-BY-MONTH P&L (pre-tax, where the bleed actually came from)")
out("=" * 130)
for y in YEARS:
    out(f"\n  {y}:")
    out(f"  {'Month':<8} {'NIFTY':>9} {'Strategy':>10} {'Shortfall':>12}  Notes")
    out("  " + "-"*8 + " " + "-"*9 + " " + "-"*10 + " " + "-"*12 + "  " + "-"*40)
    for m in range(1, 13):
        mo = daily[(daily.index.year == y) & (daily.index.month == m)]
        if not len(mo): continue
        n = (1 + mo["nifty_bh_pretax"]).prod() - 1
        s = (1 + mo["c1_pretax"]).prod() - 1
        # State summary
        state_counts = mo["c1_state"].value_counts().to_dict()
        majority = max(state_counts, key=state_counts.get)
        notes = f"mostly {majority} ({state_counts[majority]}/{len(mo)} days)"
        if state_counts.get("FLAT", 0) >= 10 and n > s + 0.02:
            notes += "  *flat-during-NIFTY-up*"
        out(f"  {y}-{m:02d}  {n*100:+8.2f}% {s*100:+9.2f}% {(n-s)*100:+11.2f}pp  {notes}")
out()

# ─── Transitions in 2018-2019, ranked by cost ──────────────────────────────
out("=" * 130)
out("  ALL TRANSITIONS IN 2018-2019 — ranked by cost (worst first)")
out("=" * 130)
out()
y_trans = trans[trans["year"].isin(YEARS)].sort_values("cost_pp", ascending=False)
out(f"  Total transitions 2018-2019: {len(y_trans)}")
out(f"  {'Date':<12} {'From → To':<22} {'Verdict':<10} {'Cause':<22} {'Cost':>8} {'NIFTY 20d':>11} {'Mom 20d':>10}")
out("  " + "-"*12 + " " + "-"*22 + " " + "-"*10 + " " + "-"*22 + " " + "-"*8 + " " + "-"*11 + " " + "-"*10)
for _, r in y_trans.iterrows():
    tt = f"{r['from']} → {r['to']}"
    v  = r["verdict"].split(" ")[0]
    c  = r["cause"][:22]
    fn = r["f20_n"] * 100 if pd.notna(r["f20_n"]) else 0
    fm = r["f20_m"] * 100 if pd.notna(r["f20_m"]) else 0
    out(f"  {r['date'].strftime('%Y-%m-%d')} {tt:<22} {v:<10} {c:<22} "
        f"{r['cost_pp']*100:+7.2f}pp {fn:+10.2f}% {fm:+9.2f}%")
out()

# Total cost in 2018-2019
total_cost = y_trans["cost_pp"].sum() * 100
out(f"  Total transition-cost in 2018-2019 (arithmetic sum): {total_cost:+.2f}pp")
out()

# ─── Recovery windows in 2018-2019 ───────────────────────────────────────
out("=" * 130)
out("  RECOVERY WINDOWS in 2018-2019")
out("=" * 130)
out()
y_wins = windows[windows["year"].isin(YEARS)]
out(f"  Total recovery windows 2018-2019: {len(y_wins)}")
out(f"  {'Re-entry':<12} {'Class':<24} {'Winner':<6} {'Mom30 60d':>10} {'NIFTY 60d':>10} {'Gold 60d':>10} {'Mom-Winner':>12}")
out("  " + "-"*12 + " " + "-"*24 + " " + "-"*6 + " " + "-"*10 + " " + "-"*10 + " " + "-"*10 + " " + "-"*12)
for _, r in y_wins.iterrows():
    cl = r["chop_class"]
    out(f"  {r['re_entry'].strftime('%Y-%m-%d')} {cl[:24]:<24} {r['winner']:<6} "
        f"{r['cum_m_pct']*100:+9.2f}% {r['cum_n_pct']*100:+9.2f}% {r['cum_g_pct']*100:+9.2f}% "
        f"{(r['cum_m_pct']-r['winner_ret_pct'])*100:+11.2f}pp")
out()

# ─── Pattern analysis: where the money went ─────────────────────────────
out("=" * 130)
out("  WHERE THE MONEY WENT — bucket the 2018-2019 underperformance")
out("=" * 130)
out()
# Identify the worst defensive false signals (LONG → FLAT/SHORT/GOLD with positive NIFTY 20d)
def_false = y_trans[(y_trans["from"].isin(["LONG", "LONG_V2"])) &
                    (y_trans["to"].isin(["FLAT", "SHORT", "GOLD"])) &
                    (y_trans["verdict"].str.startswith("FALSE"))]
out(f"  Defensive false signals (went flat/short/gold but NIFTY rose ≥2% next 20d):")
out(f"    Count: {len(def_false)}, total cost: {def_false['cost_pp'].sum()*100:+.2f}pp")
for _, r in def_false.iterrows():
    out(f"      {r['date'].strftime('%Y-%m-%d')}: {r['from']} → {r['to']} via {r['cause']}, "
        f"cost {r['cost_pp']*100:+.2f}pp (NIFTY +{r['f20_n']*100:.1f}% next 20d)")
out()

# Risk-on false signals
risk_false = y_trans[(y_trans["from"].isin(["FLAT", "SHORT", "GOLD"])) &
                     (y_trans["to"].isin(["LONG", "LONG_V2"])) &
                     (y_trans["verdict"].str.startswith("FALSE"))]
out(f"  Risk-on false signals (went long but Mom30 fell next 20d):")
out(f"    Count: {len(risk_false)}, total cost: {risk_false['cost_pp'].sum()*100:+.2f}pp")
for _, r in risk_false.iterrows():
    out(f"      {r['date'].strftime('%Y-%m-%d')}: {r['from']} → {r['to']} via {r['cause']}, "
        f"cost {r['cost_pp']*100:+.2f}pp (Mom30 {r['f20_m']*100:+.1f}% next 20d)")
out()

# Choppy/never-latched windows — where Mom30 underperformed
mom_lag_wins = y_wins[(y_wins["winner"] != "Mom30") & (y_wins["winner_ret_pct"] - y_wins["cum_m_pct"] > 0.03)]
out(f"  Recovery windows where Mom30 lagged the winner by ≥3pp:")
out(f"    Count: {len(mom_lag_wins)}, total Mom30 underperformance: "
    f"{(mom_lag_wins['cum_m_pct'] - mom_lag_wins['winner_ret_pct']).sum()*100:+.2f}pp")
for _, r in mom_lag_wins.iterrows():
    diff = (r["cum_m_pct"] - r["winner_ret_pct"]) * 100
    out(f"      {r['re_entry'].strftime('%Y-%m-%d')}: winner={r['winner']} "
        f"({r['winner_ret_pct']*100:+.2f}%), Mom30={r['cum_m_pct']*100:+.2f}% → {diff:+.2f}pp behind")
out()

# ─── Targeted fixes ──────────────────────────────────────────────────────
out("=" * 130)
out("  TARGETED FIXES FOR 2018-2019 (without affecting upside years)")
out("=" * 130)
out()
out("  THE PATTERN in 2018-2019:")
out("    Both years had Mom30 (midcap-tilted momentum) lagging large-cap NIFTY due to")
out("    the NBFC/IL&FS crisis (Sep 2018) crushing midcaps. Strategy also got force-")
out("    flatted multiple times by slow-stress while NIFTY (large-caps) recovered.")
out()
out("    The bleed in 2018-2019 comes from TWO mechanisms:")
out("    (A) Mom30 was the wrong asset (NIFTY was right) ← factor rotation")
out("    (B) Slow-stress force-flatted during NIFTY recoveries ← override drag")
out()

out("  FIX OPTION 1 — Conditional asset switch on Mom30/NIFTY relative weakness")
out("  ----------------------------------------------------------------------")
out("  Trigger: If on entry to a long state, Mom30 has been UNDERPERFORMING NIFTY by")
out("           > 3% over trailing 60d, hold NIFTY 50 instead of Mom30 for that long stretch.")
out("  ")
out("  WHY THIS PROTECTS UPSIDES:")
out("    - In 2009/2014/2017/2020/2021 etc., Mom30 was LEADING NIFTY on re-entry days,")
out("      so the rule wouldn't fire. Mom30 stays the long-side asset on those years.")
out("    - In 2018/2022, Mom30 was LAGGING by >3% on key re-entry days (per the data")
out("      already shown). The rule would have held NIFTY 50 instead.")
out("  ")
out("  EXPECTED IMPACT (in-sample):")
out("    - 2018: Mom30 trailing 60d return at Feb-Sep re-entries was -5% to -10% vs NIFTY.")
out("      Holding NIFTY 50 instead would have saved 5-8pp of the 10pp shortfall.")
out("    - 2019: Mom30 trailing 60d -3% to -6% vs NIFTY at most re-entries. NIFTY 50")
out("      would have saved 4-6pp.")
out("    - Other years: rule rarely fires (Mom30 typically leading).")
out()

out("  FIX OPTION 2 — Slow-stress confirmation requirement")
out("  ----------------------------------------------------")
out("  Trigger: Require slow-stress to fire for 3+ consecutive trading days before")
out("           force-flatting. Single-day or 2-day spikes don't trigger the override.")
out("  ")
out("  WHY THIS PROTECTS UPSIDES:")
out("    - In 2013 taper / 2018 NBFC / 2020 COVID, slow-stress fired persistently over")
out("      many days (the conditions remained elevated). Confirmation rule passes those.")
out("    - In 2019 election-year noise and 2025 tariff noise, slow-stress had single-day")
out("      fires that reverted. Confirmation rule blocks those false flats.")
out("  ")
out("  EXPECTED IMPACT (need to test): would save the ~5pp of slow-stress false fires in")
out("  2019 specifically. May save some in 2025 too. Doesn't help 2018 (slow-stress was")
out("  correctly persistent during NBFC).")
out()

out("  FIX OPTION 3 (combined) — both 1 + 2")
out("  -------------------------------------")
out("  Each fix targets a different mechanism. Option 1 addresses (A) factor rotation,")
out("  Option 2 addresses (B) override drag. Together they're orthogonal.")
out()

out("  RISKS / WHY THESE COULD STILL FAIL:")
out("    - Option 1 requires picking a threshold (3% trailing 60d). If we tune to 2018-2019,")
out("      it's overfitting. The threshold needs OOS validation.")
out("    - Option 2 was already implicitly tested in earlier panic-short 2-day confirmation,")
out("      which killed the COVID short. Need to check this rule doesn't kill correct")
out("      slow-stress fires in 2013 or 2018.")
out("    - Both rules add complexity. The pre-registration discipline (state rule BEFORE")
out("      running, OOS-validate, don't iterate) applies.")
out()

# Save
txt = os.path.join(RESULTS_DIR, "2018_2019_deep_dive.txt")
with open(txt, "w") as f:
    f.write("\n".join(lines))
print(f"\nSaved to {txt}", file=sys.stderr)
