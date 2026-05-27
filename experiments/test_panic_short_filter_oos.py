"""
test_panic_short_filter_oos.py — PRE-REGISTERED OOS TEST.

═══════════════════════════════════════════════════════════════════════════════
PRE-REGISTRATION (committed BEFORE running):

  Hypothesis: Panic-short signals fire reliably when a vol spike INTERRUPTS a
  trending market, but fail (mean-revert) when the spike compounds an already-
  weak market. The state of trailing momentum at the moment of the panic
  distinguishes these two regimes.

  Academic anchor: Daniel & Moskowitz (2016), "Momentum Crashes" — momentum
  returns are state-dependent. Short positions taken after momentum has already
  broken down get caught in the mean-reversion bounce.

  RULE: Skip panic-short fire if
       Mom30 trailing 20d return  <  NIFTY 50 trailing 20d return
  (threshold = 0; no buffer).

  When the rule skips a panic-short, the strategy stays in its prior state
  (typically FLAT) for the duration that would otherwise have been SHORT.

  Training window:  2008-04-01 → 2019-12-31  (12 years)
  OOS window:       2020-01-01 → 2025-12-31  (6 years untouched)

  PASS criteria (OOS):
    - OOS CAGR Δ > 0 (rule must NOT reduce OOS CAGR)
    - OOS MaxDD Δ > -1.0pp (rule must NOT worsen MaxDD by more than 1pp)
    BOTH must hold for the rule to be deemed shippable.

  FAIL: If either fails, the rule is abandoned. No further tuning allowed.
═══════════════════════════════════════════════════════════════════════════════

This script does NOT modify strategy.py. It builds the variant as a post-
processing overlay on C1's position vector.
"""

import os, sys
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                 "experiments"))
import strategy_lab as L

START, END = "2008-04-01", "2025-12-31"
TRAIN_END   = "2019-12-31"
OOS_START   = "2020-01-01"
RESULTS_DIR = os.path.normpath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "results"))

# ─── Run C1 baseline ────────────────────────────────────────────────────────
raw = L._load_data()
df0, _ = L.run_config("C0", L.CONFIG_CATALOG["C0"], raw, START, END, vol_target_annual=None)
target_vol = float(df0["strategy_return_pretax"].std() * np.sqrt(252))
df1, diag1 = L.run_config("C1", L.CONFIG_CATALOG["C1"], raw, START, END, vol_target_annual=target_vol)

idx = df1.index
nifty_pos = df1["nifty_position"].copy()
gold_pos  = df1["gold_position"].copy()
v2_active = diag1["v2_active"].reindex(idx).fillna(False)
weights_c1 = diag1["weights"].reindex(idx).fillna(0.0)
c1_pretax = df1["strategy_return_pretax"].copy()

# Asset returns
nifty = raw["^NSEI"].reindex(idx).ffill()
mom30 = raw["NIFTYMOM30"].reindex(idx).ffill()
ret_nif  = nifty.pct_change().fillna(0.0)
ret_mom  = mom30.pct_change().fillna(0.0)
gold = raw["GOLDBEES.NS"].reindex(idx).ffill()
ret_gold = gold.pct_change().fillna(0.0).clip(-0.5, 0.5)
repo = L.build_rbi_repo_rate_series(idx)
ret_cash = ((repo - 100/10000).clip(lower=0) / 252).reindex(idx).fillna(0.0)

# Trailing 20-day returns for the filter
mom_20d = mom30.pct_change(20)
nif_20d = nifty.pct_change(20)

# ─── Identify panic-short entries ──────────────────────────────────────────
short_today = (nifty_pos == -1.0)
short_yest  = short_today.shift(1, fill_value=False)
short_entry = short_today & ~short_yest    # day the strategy turns short
short_exit  = (~short_today) & short_yest  # day the strategy exits short

short_entries = idx[short_entry.values]
print(f"Found {len(short_entries)} panic-short entries in the sample", file=sys.stderr)

# ─── Apply the filter to each entry ────────────────────────────────────────
# For each short entry, check the rule. If rule says skip, mark entire short
# stretch as "skipped" (replace with FLAT).
skipped_dates = set()  # dates where the strategy would have been short but is now flat
skipped_stretches = []

for entry_dt in short_entries:
    i_entry = idx.get_loc(entry_dt)
    # Compute rule features at entry day (using prior 20-day data — no lookahead)
    m20 = mom_20d.iloc[i_entry] if i_entry < len(mom_20d) else np.nan
    n20 = nif_20d.iloc[i_entry] if i_entry < len(nif_20d) else np.nan
    if pd.isna(m20) or pd.isna(n20):
        continue
    # Filter: skip if Mom30 < NIFTY
    skip = m20 < n20
    if not skip:
        continue
    # Find the end of this short stretch
    j = i_entry
    while j < len(idx) and nifty_pos.iloc[j] == -1.0:
        j += 1
    stretch_idx = idx[i_entry:j]
    skipped_dates.update(stretch_idx)
    skipped_stretches.append((entry_dt, idx[j-1] if j > i_entry else entry_dt,
                              len(stretch_idx), m20, n20))

# ─── Build variant returns ─────────────────────────────────────────────────
# On skipped days, replace the strategy's pretax with cash yield (and add a small
# entry/exit cost reversal).
variant_pretax = c1_pretax.copy()
# On skipped days, the strategy should have been flat (cash). Replace with cash return.
# The cost of NOT entering/exiting short is also saved.
skipped_mask = pd.Series(False, index=idx)
for d in skipped_dates:
    skipped_mask.loc[d] = True

# Replace pretax on skipped days with cash yield
variant_pretax.loc[skipped_mask] = ret_cash.loc[skipped_mask]
# Recover the short entry cost (3 bps) on the entry day and exit cost (3 bps) on the day after exit
# C1's pretax includes both. By replacing with cash, the entry-day cost is already removed; the
# exit-day cost is on a day OUTSIDE the short stretch (the first non-short day) — but that day
# already shows up as a regular non-short day. C1's recorded cost on the exit day comes from
# short_pos.diff() = -1 → cost = 3 bps. By skipping the short stretch entirely, that cost
# wouldn't have been incurred either. We approximate by adding back 3 bps on the day after the
# stretch ends (where C1 charged the exit cost).
for entry_dt, exit_dt, length, m20, n20 in skipped_stretches:
    i_exit = idx.get_loc(exit_dt)
    if i_exit + 1 < len(idx):
        next_day = idx[i_exit + 1]
        variant_pretax.loc[next_day] += 3 / 10000  # recover exit cost

# ─── Apply tax separately for train/OOS ────────────────────────────────────
def apply_tax_subset(series, tax_rate=0.15):
    return L.apply_annual_tax(series.fillna(0.0), tax_rate=tax_rate)

variant_posttax = apply_tax_subset(variant_pretax)
c1_posttax = apply_tax_subset(c1_pretax)

# ─── Compute metrics for training, OOS, and full sample ────────────────────
def metrics_window(series, start, end):
    sub = series[(series.index >= start) & (series.index <= end)]
    if len(sub) < 5: return None
    m = L.metrics(sub)
    cum = float((1 + sub).prod() - 1)
    return {"cagr": m["cagr"], "sharpe": m["sharpe"], "max_dd": m["max_dd"],
            "vol": m["vol"], "cum": cum, "n_days": len(sub)}

train_c1   = metrics_window(c1_posttax, START, TRAIN_END)
train_var  = metrics_window(variant_posttax, START, TRAIN_END)
oos_c1     = metrics_window(c1_posttax, OOS_START, END)
oos_var    = metrics_window(variant_posttax, OOS_START, END)
full_c1    = metrics_window(c1_posttax, START, END)
full_var   = metrics_window(variant_posttax, START, END)

# ─── Output ─────────────────────────────────────────────────────────────────
lines = []
def out(s=""): lines.append(s); print(s)

out("=" * 130)
out("  PANIC-SHORT MOMENTUM-FILTER — OOS DISCIPLINED TEST")
out("=" * 130)
out()
out("  PRE-REGISTERED HYPOTHESIS:")
out("    Skip panic-short fire if Mom30 trailing 20d return < NIFTY trailing 20d return.")
out("    (threshold = 0, no buffer)")
out()
out("  ECONOMIC RATIONALE:")
out("    Real panic-shorts work when interrupting a trending market (Mom30 was leading).")
out("    False panic-shorts occur in already-weak markets (Mom30 was lagging) — these are")
out("    mean-reversion traps. Daniel-Moskowitz 'Momentum Crashes' (2016).")
out()
out("  TRAINING WINDOW:    " + START + " → " + TRAIN_END)
out("  OOS WINDOW:         " + OOS_START + " → " + END + "  (NEVER touched before this test)")
out()
out(f"  Panic-short entries in full sample: {len(short_entries)}")
out(f"  Entries the filter would SKIP:      {len(skipped_stretches)}")
out()

# ─── Skipped stretches detail ──────────────────────────────────────────────
out("=" * 130)
out("  WHICH PANIC-SHORTS DID THE FILTER SKIP?")
out("=" * 130)
out(f"  {'Entry':<12} {'Exit':<12} {'Days':>5} {'Mom30 20d':>11} {'NIFTY 20d':>11} {'RS (M-N)':>10} {'Window':<10}")
out("  " + "-"*12 + " " + "-"*12 + " " + "-"*5 + " " + "-"*11 + " " + "-"*11 + " " + "-"*10 + " " + "-"*10)
for entry_dt, exit_dt, length, m20, n20 in skipped_stretches:
    window = "TRAIN" if entry_dt <= pd.Timestamp(TRAIN_END) else "OOS"
    rs = m20 - n20
    out(f"  {entry_dt.strftime('%Y-%m-%d')} {exit_dt.strftime('%Y-%m-%d')} {length:>5d} "
        f"{m20*100:+10.2f}% {n20*100:+10.2f}% {rs*100:+9.2f}% {window:<10}")
out()

# ─── Metrics summary ──────────────────────────────────────────────────────
out("=" * 130)
out("  METRICS — C1 (baseline) vs Variant (C1 with panic-short filter)")
out("=" * 130)
def print_window(name, m_c1, m_var):
    out(f"  {name}:")
    out(f"    {'Metric':<14} {'C1':>10} {'Variant':>10} {'Δ':>10}")
    out("    " + "-"*14 + " " + "-"*10 + " " + "-"*10 + " " + "-"*10)
    out(f"    {'CAGR':<14} {m_c1['cagr']*100:+9.2f}% {m_var['cagr']*100:+9.2f}% "
        f"{(m_var['cagr']-m_c1['cagr'])*100:+9.2f}pp")
    out(f"    {'Sharpe':<14} {m_c1['sharpe']:>9.3f}  {m_var['sharpe']:>9.3f}  "
        f"{m_var['sharpe']-m_c1['sharpe']:+9.3f}")
    out(f"    {'MaxDD':<14} {m_c1['max_dd']*100:+9.2f}% {m_var['max_dd']*100:+9.2f}% "
        f"{(m_var['max_dd']-m_c1['max_dd'])*100:+9.2f}pp")
    out(f"    {'Vol':<14} {m_c1['vol']*100:+9.2f}% {m_var['vol']*100:+9.2f}% "
        f"{(m_var['vol']-m_c1['vol'])*100:+9.2f}pp")
    out(f"    {'Cum return':<14} {m_c1['cum']*100:+9.1f}% {m_var['cum']*100:+9.1f}% "
        f"{(m_var['cum']-m_c1['cum'])*100:+9.1f}pp")
    out()

print_window("TRAINING (2008-04-01 → 2019-12-31)", train_c1, train_var)
print_window("OOS (2020-01-01 → 2025-12-31)",      oos_c1,   oos_var)
print_window("FULL SAMPLE (2008-04-01 → 2025-12-31)", full_c1, full_var)

# ─── Pass/Fail evaluation ─────────────────────────────────────────────────
out("=" * 130)
out("  PRE-REGISTERED PASS/FAIL VERDICT (OOS only)")
out("=" * 130)
out()
d_cagr = (oos_var["cagr"] - oos_c1["cagr"]) * 100
d_maxdd = (oos_var["max_dd"] - oos_c1["max_dd"]) * 100
out(f"  Criterion 1 — OOS CAGR Δ > 0:")
out(f"    Variant CAGR {oos_var['cagr']*100:+.2f}%  vs  C1 CAGR {oos_c1['cagr']*100:+.2f}%")
out(f"    Δ = {d_cagr:+.2f}pp")
crit1 = d_cagr > 0
out(f"    {'PASS ✓' if crit1 else 'FAIL ✗'}")
out()
out(f"  Criterion 2 — OOS MaxDD Δ > -1.0pp:")
out(f"    Variant MaxDD {oos_var['max_dd']*100:+.2f}%  vs  C1 MaxDD {oos_c1['max_dd']*100:+.2f}%")
out(f"    Δ = {d_maxdd:+.2f}pp")
crit2 = d_maxdd > -1.0
out(f"    {'PASS ✓' if crit2 else 'FAIL ✗'}")
out()
overall = "PASS ✓" if (crit1 and crit2) else "FAIL ✗"
out(f"  OVERALL VERDICT: {overall}")
if crit1 and crit2:
    out(f"  → The rule survives OOS validation. Candidate for v1.6 integration.")
else:
    out(f"  → The rule does NOT survive OOS validation. Per pre-registration, do NOT iterate.")
    out(f"    Improvement direction is data-bounded; C1 remains the production candidate.")
out()

# ─── Save ────────────────────────────────────────────────────────────────
txt = os.path.join(RESULTS_DIR, "panic_short_filter_oos_results.txt")
with open(txt, "w") as f:
    f.write("\n".join(lines))
print(f"\nSaved to {txt}", file=sys.stderr)
