"""
diagnose_false_signals_feature_separation.py — DIAGNOSTIC.

Goes deeper than the prior fix-tradeoff test: for each signal class, computes
the discriminating power of EVERY available feature for separating true from
false fires.

For each feature, we compute:
  - Mean for TRUE (correct) signal fires
  - Mean for FALSE signal fires
  - AUC (Mann-Whitney): how well the feature separates the two
  - Cohen's d (effect size): standardized mean difference
  - Whether a threshold rule would EFFECTIVELY separate them

A feature is useful if AUC > 0.7 (or < 0.3) AND |d| > 0.5. If no feature
clears these bars, the populations are not separable with current data — and
the answer to "can we keep true and remove false?" is empirically NO with
existing features.

Signal classes analyzed:
  1. Panic-short (12 events: 7 TRUE, 5 FALSE)
  2. Slow-stress → flat (36 events: 27 TRUE, 9 FALSE)
  3. Regime-bear (95 events: 68 TRUE, 27 FALSE)
  4. Re-entry to long (114 events: 76 TRUE, 38 FALSE)
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

# ─── Reload everything we need ─────────────────────────────────────────────
raw = L._load_data()
df0, _ = L.run_config("C0", L.CONFIG_CATALOG["C0"], raw, START, END, vol_target_annual=None)
target_vol = float(df0["strategy_return_pretax"].std() * np.sqrt(252))
df1, diag1 = L.run_config("C1", L.CONFIG_CATALOG["C1"], raw, START, END, vol_target_annual=target_vol)
idx = df1.index

# Asset data on idx
nifty = raw["^NSEI"].reindex(idx).ffill()
mom30 = raw["NIFTYMOM30"].reindex(idx).ffill()
gold  = raw["GOLDBEES.NS"].reindex(idx).ffill()
vix   = raw["^INDIAVIX"].reindex(idx).ffill()
inr   = raw["INR=X"].reindex(idx).ffill()
us10y = raw["^TNX"].reindex(idx).ffill()

# Build a rich feature panel (only features computable from existing data)
features = pd.DataFrame(index=idx)
features["vix_lvl"]    = vix
features["vix_5d_pct"] = vix.pct_change(5)
features["vix_10d_pct"]= vix.pct_change(10)
features["vix_20d_pct"]= vix.pct_change(20)
features["vix_90d_z"]  = (vix - vix.rolling(90).mean()) / vix.rolling(90).std()
features["inr_10d_pct"]= inr.pct_change(10)
features["inr_20d_pct"]= inr.pct_change(20)
features["inr_60d_pct"]= inr.pct_change(60)
features["nif_5d"]     = nifty.pct_change(5)
features["nif_10d"]    = nifty.pct_change(10)
features["nif_20d"]    = nifty.pct_change(20)
features["nif_60d"]    = nifty.pct_change(60)
features["mom_5d"]     = mom30.pct_change(5)
features["mom_10d"]    = mom30.pct_change(10)
features["mom_20d"]    = mom30.pct_change(20)
features["mom_60d"]    = mom30.pct_change(60)
features["gold_10d"]   = gold.pct_change(10)
features["us10y_20d"]  = us10y.pct_change(20)
features["nif_dist_100dma"] = nifty / nifty.rolling(100, min_periods=1).mean() - 1
features["mom_dist_100dma"] = mom30 / mom30.rolling(100, min_periods=1).mean() - 1
# Mom30 vs NIFTY trailing relative strength
features["rs_mom_nif_20d"] = features["mom_20d"] - features["nif_20d"]
features["rs_mom_nif_60d"] = features["mom_60d"] - features["nif_60d"]
# Spread between VIX trend and INR trend (multi-asset stress)
features["multi_stress"] = features["vix_20d_pct"] + features["inr_20d_pct"]

# Load transitions
trans_df = pd.read_csv(os.path.join(RESULTS_DIR, "all_transitions_summary.csv"),
                       parse_dates=["date"])

# ─── Helpers ───────────────────────────────────────────────────────────────
def auc(true_vals, false_vals):
    """Mann-Whitney AUC: P(true_val > false_val) for the discriminating direction."""
    t = np.array([v for v in true_vals if not np.isnan(v)])
    f = np.array([v for v in false_vals if not np.isnan(v)])
    if len(t) < 2 or len(f) < 2: return np.nan
    # Combined ranks
    combined = np.concatenate([t, f])
    ranks = pd.Series(combined).rank().values
    sum_true = ranks[:len(t)].sum()
    auc_val = (sum_true - len(t) * (len(t) + 1) / 2) / (len(t) * len(f))
    return float(auc_val)

def cohens_d(true_vals, false_vals):
    t = np.array([v for v in true_vals if not np.isnan(v)])
    f = np.array([v for v in false_vals if not np.isnan(v)])
    if len(t) < 2 or len(f) < 2: return np.nan
    pooled_sd = np.sqrt(((len(t) - 1) * t.var(ddof=1) + (len(f) - 1) * f.var(ddof=1))
                        / (len(t) + len(f) - 2))
    if pooled_sd == 0: return np.nan
    return float((t.mean() - f.mean()) / pooled_sd)

def get_feature_values(dates, col):
    return [features.loc[d, col] if d in features.index else np.nan for d in dates]

# ─── Output ────────────────────────────────────────────────────────────────
lines = []
def out(s=""): lines.append(s); print(s)

out("=" * 130)
out("  FEATURE SEPARATION ANALYSIS — can we discriminate TRUE from FALSE signal fires?")
out("=" * 130)
out()
out("  For each signal class, every available feature is tested:")
out("    - AUC > 0.7 (or < 0.3) means GOOD separation (worth building a rule on)")
out("    - |Cohen's d| > 0.5 means MODERATE effect; > 0.8 = LARGE effect")
out("    - Both should be passed for a feature to be reliable.")
out()
out("  If no feature passes both bars: the signal class cannot be cleanly filtered with")
out("  existing data, and the false-vs-true populations are statistically indistinguishable.")
out()

def analyze_class(name, true_dates, false_dates):
    out("=" * 130)
    out(f"  {name} — {len(true_dates)} TRUE fires vs {len(false_dates)} FALSE fires")
    out("=" * 130)
    if len(true_dates) < 2 or len(false_dates) < 2:
        out(f"  Sample too small for analysis.")
        out()
        return None
    results = []
    for col in features.columns:
        t_vals = get_feature_values(true_dates, col)
        f_vals = get_feature_values(false_dates, col)
        a = auc(t_vals, f_vals)
        d = cohens_d(t_vals, f_vals)
        t_mean = np.nanmean(t_vals); f_mean = np.nanmean(f_vals)
        results.append({"feature": col, "auc": a, "d": d,
                         "t_mean": t_mean, "f_mean": f_mean})
    df_r = pd.DataFrame(results)
    df_r["auc_dist"] = abs(df_r["auc"] - 0.5)
    df_r = df_r.sort_values("auc_dist", ascending=False)

    out(f"  {'Feature':<22} {'TRUE mean':>11} {'FALSE mean':>11} {'AUC':>7} {'Cohen d':>9} {'Useful?':>9}")
    out("  " + "-"*22 + " " + "-"*11 + " " + "-"*11 + " " + "-"*7 + " " + "-"*9 + " " + "-"*9)
    useful_features = []
    for _, r in df_r.iterrows():
        useful = abs(r["auc"] - 0.5) > 0.2 and abs(r["d"]) > 0.5
        mark = "✓ YES" if useful else " no"
        if useful:
            useful_features.append((r["feature"], r["auc"], r["d"], r["t_mean"], r["f_mean"]))
        out(f"  {r['feature']:<22} {r['t_mean']:+10.4f} {r['f_mean']:+10.4f} "
            f"{r['auc']:>7.3f} {r['d']:+9.3f}   {mark:<9}")
    out()
    if useful_features:
        out(f"  ✓ {len(useful_features)} feature(s) pass BOTH bars (AUC > 0.7 or < 0.3 AND |d| > 0.5):")
        for fname, a, d, tm, fm in useful_features:
            direction = "higher in TRUE" if d > 0 else "lower in TRUE"
            out(f"      - {fname}: {direction} (TRUE={tm:+.4f}, FALSE={fm:+.4f}, AUC={a:.3f})")
    else:
        out(f"  ✗ NO feature passes both bars. Populations are statistically indistinguishable")
        out(f"    with the available features.")
    out()
    return useful_features

# ─── 1. Panic-short ────────────────────────────────────────────────────────
ps_true = trans_df[(trans_df["cause"] == "panic-short") &
                   (trans_df["verdict"].str.startswith("WORKED"))]["date"].tolist()
ps_false = trans_df[(trans_df["cause"] == "panic-short") &
                    (trans_df["verdict"].str.startswith("FALSE"))]["date"].tolist()
ps_features = analyze_class("1. PANIC-SHORT", ps_true, ps_false)

# ─── 2. Slow-stress ────────────────────────────────────────────────────────
ss_true = trans_df[(trans_df["cause"] == "slow-stress") &
                   (trans_df["verdict"].str.startswith("WORKED"))]["date"].tolist()
ss_false = trans_df[(trans_df["cause"] == "slow-stress") &
                    (trans_df["verdict"].str.startswith("FALSE"))]["date"].tolist()
ss_features = analyze_class("2. SLOW-STRESS", ss_true, ss_false)

# ─── 3. Regime-bear (LONG → FLAT due to regime) ────────────────────────────
reg_true = trans_df[(trans_df["cause"].isin(["regime (bear)", "regime"])) &
                    (trans_df["verdict"].str.startswith("WORKED"))]["date"].tolist()
reg_false = trans_df[(trans_df["cause"].isin(["regime (bear)", "regime"])) &
                     (trans_df["verdict"].str.startswith("FALSE"))]["date"].tolist()
reg_features = analyze_class("3. REGIME BEAR (LONG → FLAT)", reg_true, reg_false)

# ─── 4. Re-entry (FLAT/SHORT/GOLD → LONG/LONG_V2) ─────────────────────────
ro_true = trans_df[(trans_df["from"].isin(["FLAT", "SHORT", "GOLD"])) &
                   (trans_df["to"].isin(["LONG", "LONG_V2"])) &
                   (trans_df["verdict"].str.startswith("WORKED"))]["date"].tolist()
ro_false = trans_df[(trans_df["from"].isin(["FLAT", "SHORT", "GOLD"])) &
                    (trans_df["to"].isin(["LONG", "LONG_V2"])) &
                    (trans_df["verdict"].str.startswith("FALSE"))]["date"].tolist()
ro_features = analyze_class("4. RE-ENTRY (FLAT/SHORT/GOLD → LONG)", ro_true, ro_false)

# ─── Summary ─────────────────────────────────────────────────────────────
out("=" * 130)
out("  SUMMARY — across all 4 signal classes, are there any discriminating features?")
out("=" * 130)
out()
all_useful = {
    "Panic-short": ps_features,
    "Slow-stress": ss_features,
    "Regime bear": reg_features,
    "Re-entry": ro_features,
}
any_features = False
for cls, ufs in all_useful.items():
    if ufs:
        any_features = True
        out(f"  {cls}: {len(ufs)} discriminating feature(s) — {', '.join(uf[0] for uf in ufs)}")
    else:
        out(f"  {cls}: NONE")
out()
if not any_features:
    out("  ⇒ HONEST ANSWER: with EXISTING features, no signal class has a feature that")
    out("    cleanly separates true from false fires. The populations overlap statistically.")
    out("    Filtering false signals while keeping true signals is not achievable with the")
    out("    data we have.")
    out()
    out("  This is the empirical proof of what we've been finding repeatedly: every filter")
    out("  that catches false signals also catches true signals at roughly the same rate.")
    out("  Not because the rules are wrong — because the signal-firing-day features do not")
    out("  contain the information needed to make the distinction.")
else:
    out("  ⇒ Some discriminating features exist. Next step: build a targeted rule on each,")
    out("    test with strict OOS validation, and report whether it survives.")
out()

# Save
txt = os.path.join(RESULTS_DIR, "false_signals_feature_separation.txt")
with open(txt, "w") as f:
    f.write("\n".join(lines))
print(f"\nSaved to {txt}", file=sys.stderr)
