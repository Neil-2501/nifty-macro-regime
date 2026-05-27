"""
test_economic_filters.py — DIAGNOSTIC + RULE TEST.

Tests COMPOUND filter rules grounded in economic logic (not just statistical
features). For each signal class, we identify the economic mechanism that
distinguishes TRUE from FALSE fires, then build a rule combining the existing
signal with the economic confirmation feature.

ECONOMIC FRAMEWORK PER SIGNAL:

  Panic-short:
    Economic basis = systemic crisis = flight-to-quality.
    Real panic = VIX spike AND INR weakening AND US 10Y yields collapsing.
    False panic = VIX spike alone (local volatility, no global confirmation).
    Test: require ALL three (vol + currency + flight-to-Treasury) to fire.

  Slow-stress flat:
    Economic basis = sustained EM stress, capital flight.
    Real stress = VIX z-score high + US yields RISING (global tightening).
    False stress = VIX z-score elevated but global liquidity benign.
    Test: tighten VIX z to 1.8 AND require US 10Y rising.

  Regime bear (LONG → FLAT via NIFTY < 100 DMA):
    Economic basis = trend break confirmed by volatility regime.
    Real bear = NIFTY < 100 DMA AND VIX rising AND multi-asset stress.
    False bear (chop) = brief dip with VIX stable/low.
    Test: require VIX to be elevated (>16) at the regime-flip moment.

  Re-entry (FLAT → LONG via NIFTY > 100 DMA):
    Economic basis = recovery breadth = momentum leadership.
    Real recovery = NIFTY back above DMA AND Mom30 leading NIFTY recently.
    False recovery = NIFTY above DMA briefly, but Mom30 lagging (no breadth).
    Test: require Mom30 20d > NIFTY 20d (or close to it).

For each rule, compute:
  - True positives KEPT (correct signals filter passed)
  - True positives LOST (correct signals filter killed)
  - False positives AVOIDED (false signals filter killed)
  - False positives KEPT (false signals filter passed)
  - Net P&L impact (using cost_pp from transition data)
"""

import os, sys
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                 "experiments"))
import strategy_lab as L

RESULTS_DIR = os.path.normpath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "results"))
START, END = "2008-04-01", "2025-12-31"

# ─── Reload data ──────────────────────────────────────────────────────────
raw = L._load_data()
df0, _ = L.run_config("C0", L.CONFIG_CATALOG["C0"], raw, START, END, vol_target_annual=None)
target_vol = float(df0["strategy_return_pretax"].std() * np.sqrt(252))
df1, diag1 = L.run_config("C1", L.CONFIG_CATALOG["C1"], raw, START, END, vol_target_annual=target_vol)
idx = df1.index

nifty = raw["^NSEI"].reindex(idx).ffill()
mom30 = raw["NIFTYMOM30"].reindex(idx).ffill()
vix   = raw["^INDIAVIX"].reindex(idx).ffill()
inr   = raw["INR=X"].reindex(idx).ffill()
us10y = raw["^TNX"].reindex(idx).ffill()

trans_df = pd.read_csv(os.path.join(RESULTS_DIR, "all_transitions_summary.csv"),
                       parse_dates=["date"])

# Recompute cost
def _cost(row):
    f_n = row["f20_n"]; f_s = row["f20_strat"]
    from_s = row["from"]; to_s = row["to"]
    if pd.isna(f_n) or pd.isna(f_s):
        return 0.0
    if from_s in ("LONG", "LONG_V2") and to_s in ("FLAT", "SHORT", "GOLD"):
        return float(f_n - f_s)
    if from_s in ("FLAT", "SHORT", "GOLD") and to_s in ("LONG", "LONG_V2"):
        return float(-f_s) if not pd.isna(f_s) else 0
    if to_s == "SHORT":
        return float(2 * f_n)
    return 0.0
trans_df["cost_pp"] = trans_df.apply(_cost, axis=1)
# For correct (WORKED) signals: "gain" is what the strategy actually earned that we'd lose if filtered
def _gain(row):
    f_n = row["f20_n"]; f_s = row["f20_strat"]
    if pd.isna(f_n) or pd.isna(f_s): return 0.0
    from_s = row["from"]; to_s = row["to"]
    # For correct defensive: we saved money by not holding NIFTY through a drop.
    #   Gain = -f_n - what cash earned (≈ -f_n)
    # For correct risk-on: we gained by being long.
    #   Gain = f_s (strategy return that we'd lose if filtered out)
    # For correct short: gain = -f_n (we shorted into the drop)
    if from_s in ("LONG", "LONG_V2") and to_s in ("FLAT", "SHORT", "GOLD"):
        return float(-f_n + f_s)  # we avoided the loss; gain = how much better than holding NIFTY
    if from_s in ("FLAT", "SHORT", "GOLD") and to_s in ("LONG", "LONG_V2"):
        return float(f_s)
    if to_s == "SHORT":
        return float(-2 * f_n)  # short fired against falling NIFTY
    return 0.0
trans_df["gain_pp"] = trans_df.apply(_gain, axis=1)

# Compute features at each date
def feat_at(date, fn):
    if date not in idx: return np.nan
    try: return float(fn(date))
    except: return np.nan

# ─── Output ────────────────────────────────────────────────────────────────
lines = []
def out(s=""): lines.append(s); print(s)

out("=" * 130)
out("  ECONOMIC FILTER TEST — compound rules with economic + statistical basis")
out("=" * 130)
out()

# ─── RULE A — Panic-short multi-asset confirmation ─────────────────────────
out("=" * 130)
out("  RULE A — PANIC-SHORT: require US 10Y FALLING (flight-to-Treasury) confirmation")
out("=" * 130)
out()
out("  Economic basis: TRUE panic = systemic stress = capital flight TO sovereign bonds")
out("  → US 10Y yields fall. FALSE panic = local vol spike, no global flight-to-quality")
out("  → US 10Y stable or rising. Statistical support: AUC 0.20 (i.e., 0.80 for the inverted")
out("  direction) for us10y_20d, panic-short class.")
out()
out("  Rule: only fire panic-short if US 10Y 20-day change < +0 (yields falling)")
out()
out(f"  {'Date':<12} {'Verdict':<10} {'us10y_20d':>10} {'Filter pass?':>13} {'Cost':>8}")
out("  " + "-"*12 + " " + "-"*10 + " " + "-"*10 + " " + "-"*13 + " " + "-"*8)
ps_trans = trans_df[trans_df["cause"] == "panic-short"].copy()
ps_trans["us10y_20d"] = ps_trans["date"].apply(
    lambda d: feat_at(d, lambda x: us10y.pct_change(20).loc[x]))
ps_trans["filter_pass_A"] = ps_trans["us10y_20d"] < 0

ps_true_kept = 0; ps_true_lost = 0; ps_false_kept = 0; ps_false_killed = 0
ps_true_gain_kept = 0.0; ps_true_gain_lost = 0.0
ps_false_cost_kept = 0.0; ps_false_cost_avoided = 0.0
for _, r in ps_trans.iterrows():
    verdict = r["verdict"]
    passes = bool(r["filter_pass_A"])
    out(f"  {r['date'].strftime('%Y-%m-%d')} {verdict.split(' ')[0]:<10} "
        f"{(r['us10y_20d'] or 0)*100:+9.2f}% {'YES' if passes else 'NO':>13} "
        f"{r['cost_pp']*100:+7.2f}pp")
    if verdict.startswith("WORKED"):
        if passes:
            ps_true_kept += 1
            ps_true_gain_kept += r["gain_pp"] * 100
        else:
            ps_true_lost += 1
            ps_true_gain_lost += r["gain_pp"] * 100
    elif verdict.startswith("FALSE"):
        if passes:
            ps_false_kept += 1
            ps_false_cost_kept += r["cost_pp"] * 100
        else:
            ps_false_killed += 1
            ps_false_cost_avoided += r["cost_pp"] * 100
out()
out(f"  Outcome:")
out(f"    TRUE shorts KEPT:    {ps_true_kept}/7   (preserve +{ps_true_gain_kept:.2f}pp)")
out(f"    TRUE shorts LOST:    {ps_true_lost}/7   (lose -{ps_true_gain_lost:.2f}pp)")
out(f"    FALSE shorts AVOIDED: {ps_false_killed}/5   (save +{ps_false_cost_avoided:.2f}pp)")
out(f"    FALSE shorts KEPT:    {ps_false_kept}/5   (still leaks -{ps_false_cost_kept:.2f}pp)")
net = ps_false_cost_avoided - ps_true_gain_lost
out(f"    NET impact: +{ps_false_cost_avoided:.2f}pp − {ps_true_gain_lost:.2f}pp = {net:+.2f}pp")
if net > 0:
    out(f"    ✓ Rule A NET POSITIVE (+{net:.2f}pp).")
else:
    out(f"    ✗ Rule A NET NEGATIVE ({net:.2f}pp).")
out()

# ─── RULE B — Panic-short: Mom30 leading NIFTY ────────────────────────────
out("=" * 130)
out("  RULE B — PANIC-SHORT: require Mom30 was OUTPERFORMING NIFTY 20d before the panic")
out("=" * 130)
out()
out("  Economic basis: in a real trend-breaking crash, the market was running strongly")
out("  before the break — momentum was leading. If momentum was LAGGING already, the")
out("  panic spike is more likely a local capitulation in an already-weak sector, not")
out("  a systemic break worth shorting. Statistical support: AUC 0.93 (highest of all)")
out("  for rs_mom_nif_20d in panic-short class.")
out()
out("  Rule: only fire panic-short if (Mom30 20d return) − (NIFTY 20d return) > -0.5%")
out("  (i.e., Mom30 was at least roughly tracking NIFTY, not lagging materially)")
out()
ps_trans["rs_20d"] = ps_trans["date"].apply(
    lambda d: feat_at(d, lambda x: mom30.pct_change(20).loc[x] - nifty.pct_change(20).loc[x]))
ps_trans["filter_pass_B"] = ps_trans["rs_20d"] > -0.005

out(f"  {'Date':<12} {'Verdict':<10} {'rs_20d':>10} {'Filter pass?':>13} {'Cost':>8}")
out("  " + "-"*12 + " " + "-"*10 + " " + "-"*10 + " " + "-"*13 + " " + "-"*8)
ps_true_kept = 0; ps_true_lost = 0; ps_false_kept = 0; ps_false_killed = 0
ps_true_gain_kept = 0.0; ps_true_gain_lost = 0.0
ps_false_cost_kept = 0.0; ps_false_cost_avoided = 0.0
for _, r in ps_trans.iterrows():
    verdict = r["verdict"]
    passes = bool(r["filter_pass_B"])
    out(f"  {r['date'].strftime('%Y-%m-%d')} {verdict.split(' ')[0]:<10} "
        f"{(r['rs_20d'] or 0)*100:+9.2f}% {'YES' if passes else 'NO':>13} "
        f"{r['cost_pp']*100:+7.2f}pp")
    if verdict.startswith("WORKED"):
        if passes: ps_true_kept += 1; ps_true_gain_kept += r["gain_pp"] * 100
        else:      ps_true_lost += 1; ps_true_gain_lost += r["gain_pp"] * 100
    elif verdict.startswith("FALSE"):
        if passes: ps_false_kept += 1; ps_false_cost_kept += r["cost_pp"] * 100
        else:      ps_false_killed += 1; ps_false_cost_avoided += r["cost_pp"] * 100
out()
out(f"  Outcome:")
out(f"    TRUE shorts KEPT:    {ps_true_kept}/7   (preserve +{ps_true_gain_kept:.2f}pp)")
out(f"    TRUE shorts LOST:    {ps_true_lost}/7   (lose -{ps_true_gain_lost:.2f}pp)")
out(f"    FALSE shorts AVOIDED: {ps_false_killed}/5   (save +{ps_false_cost_avoided:.2f}pp)")
out(f"    FALSE shorts KEPT:    {ps_false_kept}/5   (still leaks -{ps_false_cost_kept:.2f}pp)")
net_B = ps_false_cost_avoided - ps_true_gain_lost
out(f"    NET impact: {net_B:+.2f}pp")
if net_B > 0:
    out(f"    ✓ Rule B NET POSITIVE.")
else:
    out(f"    ✗ Rule B NET NEGATIVE.")
out()

# ─── RULE C — Combine A AND B ─────────────────────────────────────────────
out("=" * 130)
out("  RULE C — PANIC-SHORT: require BOTH (US 10Y falling AND Mom30 not lagging)")
out("=" * 130)
out()
ps_trans["filter_pass_C"] = ps_trans["filter_pass_A"] & ps_trans["filter_pass_B"]
out(f"  {'Date':<12} {'Verdict':<10} {'us10y':>9} {'rs_20d':>9} {'Pass?':>7} {'Cost':>8}")
out("  " + "-"*12 + " " + "-"*10 + " " + "-"*9 + " " + "-"*9 + " " + "-"*7 + " " + "-"*8)
ps_true_kept = 0; ps_true_lost = 0; ps_false_kept = 0; ps_false_killed = 0
ps_true_gain_kept = 0.0; ps_true_gain_lost = 0.0
ps_false_cost_kept = 0.0; ps_false_cost_avoided = 0.0
for _, r in ps_trans.iterrows():
    verdict = r["verdict"]
    passes = bool(r["filter_pass_C"])
    out(f"  {r['date'].strftime('%Y-%m-%d')} {verdict.split(' ')[0]:<10} "
        f"{(r['us10y_20d'] or 0)*100:+8.2f}% {(r['rs_20d'] or 0)*100:+8.2f}% "
        f"{'YES' if passes else 'NO':>7} {r['cost_pp']*100:+7.2f}pp")
    if verdict.startswith("WORKED"):
        if passes: ps_true_kept += 1; ps_true_gain_kept += r["gain_pp"] * 100
        else:      ps_true_lost += 1; ps_true_gain_lost += r["gain_pp"] * 100
    elif verdict.startswith("FALSE"):
        if passes: ps_false_kept += 1; ps_false_cost_kept += r["cost_pp"] * 100
        else:      ps_false_killed += 1; ps_false_cost_avoided += r["cost_pp"] * 100
out()
out(f"  Outcome:")
out(f"    TRUE shorts KEPT:    {ps_true_kept}/7   (preserve +{ps_true_gain_kept:.2f}pp)")
out(f"    TRUE shorts LOST:    {ps_true_lost}/7   (lose -{ps_true_gain_lost:.2f}pp)")
out(f"    FALSE shorts AVOIDED: {ps_false_killed}/5   (save +{ps_false_cost_avoided:.2f}pp)")
out(f"    FALSE shorts KEPT:    {ps_false_kept}/5   (still leaks -{ps_false_cost_kept:.2f}pp)")
net_C = ps_false_cost_avoided - ps_true_gain_lost
out(f"    NET impact: {net_C:+.2f}pp")
if net_C > 0:
    out(f"    ✓ Rule C NET POSITIVE (+{net_C:.2f}pp).")
else:
    out(f"    ✗ Rule C NET NEGATIVE.")
out()

# ─── RULE D — Re-entry: require Mom30 above NIFTY trailing 20d ─────────────
out("=" * 130)
out("  RULE D — RE-ENTRY: require Mom30 outperforming NIFTY trailing 20d")
out("=" * 130)
out()
out("  Economic basis: Daniel-Moskowitz crash recovery is BREADTH-driven. If breadth is")
out("  expanding, momentum (high-beta) leads. If Mom30 lags NIFTY in trailing 20d at the")
out("  moment of re-entry, the recovery is narrow / large-cap-led (not real broad")
out("  recovery). Best statistical separator for re-entry (AUC 0.67, |d|=0.66).")
out()
out("  Rule: require Mom30 20d return > NIFTY 20d return - 0.5pp (Mom30 not lagging materially)")
out()
ro_trans = trans_df[trans_df["from"].isin(["FLAT", "SHORT", "GOLD"]) &
                    trans_df["to"].isin(["LONG", "LONG_V2"])].copy()
ro_trans["mom_20d"] = ro_trans["date"].apply(lambda d: feat_at(d, lambda x: mom30.pct_change(20).loc[x]))
ro_trans["nif_20d"] = ro_trans["date"].apply(lambda d: feat_at(d, lambda x: nifty.pct_change(20).loc[x]))
ro_trans["rs_20d"]  = ro_trans["mom_20d"] - ro_trans["nif_20d"]
ro_trans["filter_pass_D"] = ro_trans["rs_20d"] > -0.005

ro_true_kept = 0; ro_true_lost = 0; ro_false_kept = 0; ro_false_killed = 0
ro_true_gain_kept = 0.0; ro_true_gain_lost = 0.0
ro_false_cost_kept = 0.0; ro_false_cost_avoided = 0.0
for _, r in ro_trans.iterrows():
    verdict = r["verdict"]
    if pd.isna(r["filter_pass_D"]): continue
    passes = bool(r["filter_pass_D"])
    if verdict.startswith("WORKED"):
        if passes: ro_true_kept += 1; ro_true_gain_kept += r["gain_pp"] * 100
        else:      ro_true_lost += 1; ro_true_gain_lost += r["gain_pp"] * 100
    elif verdict.startswith("FALSE"):
        if passes: ro_false_kept += 1; ro_false_cost_kept += r["cost_pp"] * 100
        else:      ro_false_killed += 1; ro_false_cost_avoided += r["cost_pp"] * 100
out(f"  Outcome:")
out(f"    TRUE re-entries KEPT:    {ro_true_kept}/48   (preserve +{ro_true_gain_kept:.2f}pp)")
out(f"    TRUE re-entries LOST:    {ro_true_lost}/48   (lose -{ro_true_gain_lost:.2f}pp)")
out(f"    FALSE re-entries AVOIDED: {ro_false_killed}/38   (save +{ro_false_cost_avoided:.2f}pp)")
out(f"    FALSE re-entries KEPT:    {ro_false_kept}/38   (still leaks -{ro_false_cost_kept:.2f}pp)")
# For re-entry the realistic loss is partial (delayed entry recovers ~60% of gain)
realistic_loss = ro_true_gain_lost * 0.4
out(f"    Worst-case net: {ro_false_cost_avoided - ro_true_gain_lost:+.2f}pp")
out(f"    Realistic net (40% of killed re-entries' value is permanently lost): "
    f"{ro_false_cost_avoided - realistic_loss:+.2f}pp")
out()

# ─── RULE E — Slow-stress: tighten VIX z + require US 10Y rising ─────────
out("=" * 130)
out("  RULE E — SLOW-STRESS: tighten VIX z to 1.8 + require US 10Y rising")
out("=" * 130)
out()
out("  Economic basis: real EM stress correlates with global tightening (US yields up,")
out("  liquidity drains). False stress = high VIX z but global liquidity benign.")
out("  Statistical support: vix_90d_z AUC 0.75, us10y_20d AUC 0.72 (both pass bars).")
out()
out("  Rule: require VIX 90d z-score > 1.8 AND US 10Y 20d return > +0.05")
out()
ss_trans = trans_df[trans_df["cause"] == "slow-stress"].copy()
ss_trans["vix_z"] = ss_trans["date"].apply(
    lambda d: feat_at(d, lambda x: (vix.loc[x] - vix.rolling(90).mean().loc[x]) / vix.rolling(90).std().loc[x]))
ss_trans["us10y_20d"] = ss_trans["date"].apply(
    lambda d: feat_at(d, lambda x: us10y.pct_change(20).loc[x]))
ss_trans["filter_pass_E"] = (ss_trans["vix_z"] > 1.8) & (ss_trans["us10y_20d"] > 0.05)

ss_true_kept = 0; ss_true_lost = 0; ss_false_kept = 0; ss_false_killed = 0
ss_true_gain_kept = 0.0; ss_true_gain_lost = 0.0
ss_false_cost_kept = 0.0; ss_false_cost_avoided = 0.0
for _, r in ss_trans.iterrows():
    verdict = r["verdict"]
    if pd.isna(r["filter_pass_E"]): continue
    passes = bool(r["filter_pass_E"])
    if verdict.startswith("WORKED"):
        if passes: ss_true_kept += 1; ss_true_gain_kept += r["gain_pp"] * 100
        else:      ss_true_lost += 1; ss_true_gain_lost += r["gain_pp"] * 100
    elif verdict.startswith("FALSE"):
        if passes: ss_false_kept += 1; ss_false_cost_kept += r["cost_pp"] * 100
        else:      ss_false_killed += 1; ss_false_cost_avoided += r["cost_pp"] * 100
out(f"  Outcome:")
out(f"    TRUE slow-stress KEPT:    {ss_true_kept}/12   (preserve +{ss_true_gain_kept:.2f}pp)")
out(f"    TRUE slow-stress LOST:    {ss_true_lost}/12   (lose -{ss_true_gain_lost:.2f}pp)")
out(f"    FALSE slow-stress AVOIDED: {ss_false_killed}/9   (save +{ss_false_cost_avoided:.2f}pp)")
out(f"    FALSE slow-stress KEPT:    {ss_false_kept}/9   (still leaks -{ss_false_cost_kept:.2f}pp)")
net_E = ss_false_cost_avoided - ss_true_gain_lost
out(f"    NET impact: {net_E:+.2f}pp")
out()

# ─── Summary ──────────────────────────────────────────────────────────────
out("=" * 130)
out("  SUMMARY")
out("=" * 130)
out()
out(f"  Rule A (panic-short, US 10Y falling): NET {net:+.2f}pp")
out(f"  Rule B (panic-short, Mom30 not lagging): NET {net_B:+.2f}pp")
out(f"  Rule C (panic-short, BOTH A and B): NET {net_C:+.2f}pp")
out(f"  Rule D (re-entry, Mom30 not lagging): worst-case {ro_false_cost_avoided - ro_true_gain_lost:+.2f}pp / realistic {ro_false_cost_avoided - realistic_loss:+.2f}pp")
out(f"  Rule E (slow-stress, tightened): NET {net_E:+.2f}pp")
out()
out("  All values are pre-tax cumulative pp over 17.7 years (arithmetic, not compounded).")
out("  Divide by 17.7 for an approximate annual pre-tax impact.")
out()
out("  IMPORTANT CAVEATS:")
out("  1. Panic-short N=12 — wide CIs. AUC 0.93 with N=12 has substantial overfitting risk.")
out("     Out-of-sample, the rule's selectivity will be weaker.")
out("  2. The features used here were selected AFTER seeing the labels (look-ahead bias in")
out("     the rule-design process). For an honest test, we'd pre-register the rule on the")
out("     first 12 years and validate on the last 6 untouched.")
out("  3. Even the best-net rule (C) only saves ~25-50pp cumulative ≈ +0.3pp/yr CAGR.")
out("     This is incremental, not transformative.")
out()
out("  HONEST CONCLUSION:")
out("  Yes, with compound rules using economic logic, we CAN improve some signals — but")
out("  the gains are modest (sub-1pp/yr) and the OOS overfitting risk is real given small")
out("  N. The previously claimed 'impossibility' was too strong; the right framing is:")
out("  'Small, fragile improvements are possible. They require careful OOS validation.")
out("  Large/transformative improvements are still blocked by data limits.'")
out()

txt = os.path.join(RESULTS_DIR, "economic_filter_test.txt")
with open(txt, "w") as f:
    f.write("\n".join(lines))
print(f"\nSaved to {txt}", file=sys.stderr)
