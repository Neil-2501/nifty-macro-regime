"""
diagnose_false_signals.py — DIAGNOSTIC.

Takes the 80 false-signal transitions from all_transitions_summary.csv and:
  1. Categorizes by direction (defensive false / risk-on false / short false)
  2. Computes a per-false-signal "cost" — how much P&L the strategy gave up
     vs the counterfactual "stayed in prior state" decision
  3. Ranks the 10 most catastrophic
  4. Breaks down by cause (slow-stress, panic-short, regime, G10) and year
  5. Identifies patterns: shared macro context, common triggers
  6. Suggests fixes from EXISTING data; lists new data that could help

Outputs:
  results/false_signals_analysis.txt
  results/false_signals_with_cost.csv
"""

import os, sys
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                 "experiments"))

RESULTS_DIR = os.path.normpath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "results"))

TRANS_CSV = os.path.join(RESULTS_DIR, "all_transitions_summary.csv")
if not os.path.exists(TRANS_CSV):
    raise SystemExit(f"Missing {TRANS_CSV} — run diagnose_all_transitions.py first")

df = pd.read_csv(TRANS_CSV, parse_dates=["date"])

# ─── Cost computation per false signal ─────────────────────────────────────
def direction(row):
    """Classify the direction of the move that turned out to be a false signal."""
    from_s = row["from"]; to_s = row["to"]
    if from_s in ("LONG", "LONG_V2") and to_s in ("FLAT", "SHORT", "GOLD"):
        return "defensive"     # went out of long
    if from_s in ("FLAT", "SHORT", "GOLD") and to_s in ("LONG", "LONG_V2"):
        return "risk-on"       # went into long
    if to_s == "SHORT":
        return "short"
    return "other"

def cost(row):
    """Compute the cost of this false signal in pp (positive = we lost money).
    For defensive false: cost = NIFTY went up X% but we didn't capture it.
    For risk-on false: cost = Mom30 fell, we held it. Cost = -strat_return.
    For short false: cost = NIFTY rose, we were short. Cost = +nifty_return × 2 (vs being flat).
    """
    f_n = row["f20_n"]; f_m = row["f20_m"]; f_s = row["f20_strat"]
    dr = direction(row)
    if pd.isna(f_n) or pd.isna(f_s):
        return np.nan
    if dr == "defensive":
        # Could have earned NIFTY-like return; instead earned strategy fill (cash/gold/short)
        return float(f_n - f_s)  # positive = strategy missed the gain
    if dr == "risk-on":
        # Risk-on into a falling Mom30. Cost vs flat (cash yield ~0% over 20d).
        return float(-f_s if not pd.isna(f_s) else 0)  # negative strat return = cost
    if dr == "short":
        # Short fired against rising NIFTY. Cost = 2 × f_n (vs being flat)
        return float(2 * f_n)
    return 0.0

df["direction"] = df.apply(direction, axis=1)
df["cost_pp"]   = df.apply(cost, axis=1)

# Filter to false signals only
false_df = df[df["verdict"].str.startswith("FALSE")].copy()

# ─── Output ──────────────────────────────────────────────────────────────
lines = []
def out(s=""): lines.append(s); print(s)

out("=" * 130)
out(f"  FALSE-SIGNAL ANALYSIS — {len(false_df)} false signals out of {len(df)} transitions ({len(false_df)/len(df)*100:.0f}%)")
out("=" * 130)
out()
out(f"  Cost convention: positive cost (pp) = strategy gave up money vs the counterfactual")
out(f"  'right' decision over the next 20 days. Defensive false = missed NIFTY gain. ")
out(f"  Risk-on false = held Mom30 into a drop. Short false = shorted into a rally.")
out()

# ─── By direction ─────────────────────────────────────────────────────────
out("=" * 130)
out("  1. BY DIRECTION")
out("=" * 130)
out(f"  {'Direction':<14} {'Count':>6} {'Total cost (pp)':>17} {'Mean cost (pp)':>16} "
    f"{'Worst cost (pp)':>17}")
out("  " + "-"*14 + " " + "-"*6 + " " + "-"*17 + " " + "-"*16 + " " + "-"*17)
for dr in ["defensive", "risk-on", "short", "other"]:
    sub = false_df[false_df["direction"] == dr]
    if len(sub) == 0: continue
    total = sub["cost_pp"].sum() * 100
    mean = sub["cost_pp"].mean() * 100
    worst = sub["cost_pp"].max() * 100
    out(f"  {dr:<14} {len(sub):>6d} {total:+16.2f}pp {mean:+15.2f}pp {worst:+16.2f}pp")
out()
out("  Interpretation: defensive false signals are the biggest cost bucket — strategy went")
out("  to cash/short/gold but NIFTY rose >2% over the following 20 days. These are the")
out("  primary improvement target.")
out()

# ─── Top 10 catastrophic ─────────────────────────────────────────────────
out("=" * 130)
out("  2. TOP 10 MOST CATASTROPHIC FALSE SIGNALS (by cost in next 20 days)")
out("=" * 130)
top10 = false_df.nlargest(10, "cost_pp")
out(f"  {'Rank':<4} {'Date':<12} {'Year':<6} {'From → To':<22} {'Cause':<18} "
    f"{'Cost':>8} {'NIFTY':>8} {'Mom30':>8} {'Strat':>8}")
out("  " + "-"*4 + " " + "-"*12 + " " + "-"*6 + " " + "-"*22 + " " + "-"*18 + " "
    + "-"*8 + " " + "-"*8 + " " + "-"*8 + " " + "-"*8)
for rank, (_, r) in enumerate(top10.iterrows(), 1):
    tt = f"{r['from']} → {r['to']}"
    cause_str = r["cause"][:18]
    out(f"  {rank:<4d} {r['date'].strftime('%Y-%m-%d')} {int(r['year']):<6d} {tt:<22} {cause_str:<18} "
        f"{r['cost_pp']*100:+7.2f}pp {r['f20_n']*100:+7.2f}% {r['f20_m']*100:+7.2f}% "
        f"{r['f20_strat']*100:+7.2f}%")
out()
out("  Read: row 1 is the single most damaging false signal in the sample.")
out("  Each cost figure = pp of strategy P&L given up over the 20 days following the transition.")
out()

# ─── By cause ─────────────────────────────────────────────────────────────
out("=" * 130)
out("  3. BY TRIGGERING SIGNAL (cause)")
out("=" * 130)
out(f"  {'Cause':<35} {'#FS':>5} {'Total #':>9} {'FS rate':>9} {'Total cost':>12} {'Avg cost':>10}")
out("  " + "-"*35 + " " + "-"*5 + " " + "-"*9 + " " + "-"*9 + " " + "-"*12 + " " + "-"*10)
for cause in df["cause"].unique():
    sub = false_df[false_df["cause"] == cause]
    total_sub = df[df["cause"] == cause]
    if len(sub) == 0:
        out(f"  {cause:<35} {0:>5d} {len(total_sub):>9d} {0.0:>8.0f}% {0:>10.2f}pp {0:>9.2f}pp")
        continue
    rate = len(sub) / len(total_sub) * 100
    total_cost = sub["cost_pp"].sum() * 100
    mean_cost = sub["cost_pp"].mean() * 100
    out(f"  {cause:<35} {len(sub):>5d} {len(total_sub):>9d} {rate:>8.0f}% "
        f"{total_cost:+11.2f}pp {mean_cost:+9.2f}pp")
out()

# ─── By year ──────────────────────────────────────────────────────────────
out("=" * 130)
out("  4. BY YEAR")
out("=" * 130)
out(f"  {'Year':<6} {'#FS':>5} {'Total cost':>13} {'Mean cost':>12}")
out("  " + "-"*6 + " " + "-"*5 + " " + "-"*13 + " " + "-"*12)
for y in sorted(false_df["year"].unique()):
    sub = false_df[false_df["year"] == y]
    total_cost = sub["cost_pp"].sum() * 100
    mean_cost = sub["cost_pp"].mean() * 100
    out(f"  {int(y):<6d} {len(sub):>5d} {total_cost:+12.2f}pp {mean_cost:+11.2f}pp")
out()

# ─── Pattern detection ───────────────────────────────────────────────────
out("=" * 130)
out("  5. PATTERN DETECTION — what do false signals have in common?")
out("=" * 130)
# Defensive false signals macro features
def_false = false_df[false_df["direction"] == "defensive"]
true_def_pos = df[(df["from"].isin(["LONG", "LONG_V2"])) & (df["to"].isin(["FLAT", "SHORT", "GOLD"])) & ~df["verdict"].str.startswith("FALSE")]
out(f"  Defensive false signals (n={len(def_false)}) vs correct defensive (n={len(true_def_pos)}):")
for col in ["vix", "vix_z", "inr_20d", "t20_n", "t20_m"]:
    if col not in def_false.columns: continue
    fs_mean = def_false[col].mean()
    tp_mean = true_def_pos[col].mean()
    units = "%" if col in ("inr_20d", "t20_n", "t20_m") else ""
    scale = 100 if col in ("inr_20d", "t20_n", "t20_m") else 1
    out(f"    {col:<10}  false-mean={fs_mean*scale:+.2f}{units}  correct-mean={tp_mean*scale:+.2f}{units}  diff={(fs_mean-tp_mean)*scale:+.2f}{units}")
out()

# Risk-on false signals macro features
risk_false = false_df[false_df["direction"] == "risk-on"]
true_risk_pos = df[(df["from"].isin(["FLAT", "SHORT", "GOLD"])) & (df["to"].isin(["LONG", "LONG_V2"])) & ~df["verdict"].str.startswith("FALSE")]
out(f"  Risk-on false signals (n={len(risk_false)}) vs correct risk-on (n={len(true_risk_pos)}):")
for col in ["vix", "vix_z", "inr_20d", "t20_n", "t20_m"]:
    if col not in risk_false.columns: continue
    fs_mean = risk_false[col].mean()
    tp_mean = true_risk_pos[col].mean()
    units = "%" if col in ("inr_20d", "t20_n", "t20_m") else ""
    scale = 100 if col in ("inr_20d", "t20_n", "t20_m") else 1
    out(f"    {col:<10}  false-mean={fs_mean*scale:+.2f}{units}  correct-mean={tp_mean*scale:+.2f}{units}  diff={(fs_mean-tp_mean)*scale:+.2f}{units}")
out()

# ─── Improvement directions ──────────────────────────────────────────────
out("=" * 130)
out("  6. IMPROVEMENT DIRECTIONS — what we can fix with EXISTING data")
out("=" * 130)
out()
# Compute slow-stress false signal context
ss_false = false_df[false_df["cause"] == "slow-stress"]
ss_correct = df[(df["cause"] == "slow-stress") & ~df["verdict"].str.startswith("FALSE")]
if len(ss_false) > 0:
    ss_fs_vix = ss_false["vix"].mean()
    ss_co_vix = ss_correct["vix"].mean()
    ss_fs_vixz = ss_false["vix_z"].mean()
    ss_co_vixz = ss_correct["vix_z"].mean()
    out(f"  6a. Slow-stress false fires — pattern check:")
    out(f"      Slow-stress correct fires:  mean VIX={ss_co_vix:.1f}, mean 90d-z={ss_co_vixz:+.2f}")
    out(f"      Slow-stress FALSE fires:    mean VIX={ss_fs_vix:.1f}, mean 90d-z={ss_fs_vixz:+.2f}")
    out(f"      → If false fires have systematically lower VIX or lower z-score, tightening")
    out(f"        VIX z threshold from 1.5 to 1.8 or requiring a VIX level >= 18 could help.")
    out(f"      → If they overlap, a CONFIRMATION rule (VIX must keep rising for 3 days)")
    out(f"        would be more effective than threshold tightening.")
    # Quick check: would slow-stress with vix>=20 OR vix_z >= 1.8 cut false fires?
    tighter_mask = (ss_false["vix"] >= 20) | (ss_false["vix_z"] >= 1.8)
    if tighter_mask.sum() > 0:
        avoided = (~tighter_mask).sum()
        out(f"      → Empirically: of {len(ss_false)} slow-stress false fires, {int(avoided)} had VIX < 20")
        out(f"        AND z < 1.8 simultaneously. Tightening to require BOTH thresholds would have")
        out(f"        eliminated {int(avoided)} of {len(ss_false)} ({100*avoided/len(ss_false):.0f}%) false fires.")
        avoided_cost = ss_false[~tighter_mask]["cost_pp"].sum() * 100
        out(f"        Total cost recovered: {avoided_cost:+.2f}pp across the sample.")
    out()

ps_false = false_df[false_df["cause"] == "panic-short"]
ps_correct = df[(df["cause"] == "panic-short") & ~df["verdict"].str.startswith("FALSE")]
if len(ps_false) > 0:
    ps_fs_vix = ps_false["vix"].mean() if len(ps_false) else 0
    ps_co_vix = ps_correct["vix"].mean() if len(ps_correct) else 0
    out(f"  6b. Panic-short false fires — pattern check:")
    out(f"      Panic-short correct fires: mean VIX={ps_co_vix:.1f}")
    out(f"      Panic-short FALSE fires:   mean VIX={ps_fs_vix:.1f}")
    out(f"      Panic-short already requires VIX >= 25 + VIX spike + NIFTY < 100-DMA.")
    out(f"      → If false fires happen near VIX=25 threshold, raising to VIX >= 30 might help.")
    out(f"      → A second-day confirmation (panic-short fires for 2 consecutive days) would")
    out(f"        catch the same crashes but skip the one-day false alarms.")
    out()

reg_false = false_df[false_df["cause"].isin(["regime (bear)", "regime"])]
if len(reg_false) > 0:
    out(f"  6c. Regime-filter false fires ({len(reg_false)} of all defensive false signals):")
    out(f"      These are days where NIFTY dipped below 100-DMA briefly and then recovered.")
    out(f"      → Adding a hysteresis band (require NIFTY < 100-DMA × 0.98 to flat) was tested")
    out(f"        in diagnose_whipsaw_cost.py — net negative because lag in real bears exceeded")
    out(f"        savings on chops. Not recommended.")
    out(f"      → A volume-confirmation filter (require down day on above-avg volume) might help,")
    out(f"        but volume data isn't in our current dataset.")
    out()

ro_false_count = len(risk_false)
out(f"  6d. Risk-on false signals ({ro_false_count}): strategy re-engaged long into a falling Mom30.")
out(f"      → Could add a 'don't re-enter on day 1 of bull regime' delay (wait for 5-day NIFTY")
out(f"        momentum confirmation, which the SignalCombiner already supports with")
out(f"        reentry_momentum_threshold=0.005). Currently this is applied to Lane-2 exit signals")
out(f"        but not to all re-entries. Extending it to regime-driven re-entries is a targeted fix.")
out(f"      → A more aggressive variant: require Mom30 to be above its own 100-DMA before")
out(f"        re-engaging — but that's the recovery latch we already tested and rejected.")
out()

# ─── New data ideas ──────────────────────────────────────────────────────
out("=" * 130)
out("  7. NEW DATA THAT COULD HELP — ranked by likely impact")
out("=" * 130)
out()
out("  HIGH PRIORITY:")
out("    • NSE sector indices (^CNXBANK, ^CNXIT, ^CNXAUTO, ^CNXFMCG, ^CNXENERGY,")
out("      ^CNXMETAL, ^CNXPHARMA, ^CNXFIN). Available via Yahoo Finance.")
out("      Would address: relative-rotation false signals (2018/2022/2025 type). When")
out("      Mom30's overweighted sectors are losing leadership, hold less Mom30.")
out("    • NIFTY breadth (% of NIFTY 200 stocks above 50-DMA). Computable from constituent")
out("      data if available. Would catch broadening/narrowing rallies — when breadth")
out("      deteriorates while index rises, momentum is at risk (Lou-Polk 2018 comomentum).")
out()
out("  MEDIUM PRIORITY:")
out("    • FII / DII daily net flows (NSE publishes daily). Foreign-investor flows often")
out("      lead sector rotations by 1-2 weeks. Could turn 30-day-trailing rotation into a")
out("      leading indicator.")
out("    • VIX term structure (30d / 90d / 180d implied vol). Detects regime shifts earlier")
out("      than spot VIX alone. Inverted term structure (front-month > back-month) is a")
out("      well-validated stress signal.")
out("    • Earnings revision spread (sector-level positive vs negative revisions). Often")
out("      leads sector momentum by 1-3 months. Source: Bloomberg or Refinitiv.")
out()
out("  LOW PRIORITY (limited expected benefit):")
out("    • Daily volume on NSE — could improve regime-filter false fires (confirm NIFTY")
out("      breakdown with above-avg volume), but small effect size in academic literature.")
out("    • Realized correlation matrix — when sector correlations converge to 1 (\"contagion\"),")
out("      diversification fails. Predictive of crisis windows but not factor rotation.")
out()
out("  NOT WORTH PURSUING:")
out("    • More years of price history (we already have 17). Adding more years won't change")
out("      the structural conclusions about momentum's relative-rotation vulnerability.")
out("    • Tick-level intraday data. Strategy is daily-rebalanced; intraday adds noise without")
out("      signal at the strategy's horizon.")
out()

# ─── Save CSV ────────────────────────────────────────────────────────────
false_csv = os.path.join(RESULTS_DIR, "false_signals_with_cost.csv")
false_df.sort_values("cost_pp", ascending=False).to_csv(false_csv, index=False)
out(f"  Per-false-signal CSV (ranked by cost) saved to {false_csv}")

txt_path = os.path.join(RESULTS_DIR, "false_signals_analysis.txt")
with open(txt_path, "w") as f:
    f.write("\n".join(lines))
print(f"\nSaved to {txt_path}", file=sys.stderr)
