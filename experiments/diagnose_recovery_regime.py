"""
diagnose_recovery_regime.py — DIAGNOSTIC.

Investigates whether the strategy's losing years vs Dynamic A (2011, 2013,
2014, 2022) come from the FLAT sub-periods of stress episodes or from the
RECOVERY sub-periods (first 60 trading days after re-entering long).

Part A — localize the leak: flat vs recovery, by year.
Part B — characterize recovery windows: duration, vol, choppiness, asset returns.
Part C — regime discrimination: which signals best separate "recovery" days
         from "established-good" days?

Reads current strategy.py (v1.5 with gold-in-bull fix). Does NOT modify it.
No tuning to known bad years; reports what the data shows.
"""

import os, sys
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from strategy import (
    make_combiner, MacroStrategy, RegimeFilter, load_nse_index_csv,
    build_rbi_repo_rate_series, metrics, apply_annual_tax,
)

WARMUP, IS_START, IS_END = "2006-01-01", "2008-04-01", "2025-12-31"
LONG_BPS_MOM30, SHORT_BPS, GOLD_BPS, HAIRCUT_BPS = 6, 3, 5, 100
TAX = 0.15
RECOVERY_WINDOW = 60         # trading days after re-entry
LOSING_YEARS = [2011, 2013, 2014, 2022]   # vs Dynamic A
OUTPUT_PATH = os.path.normpath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..",
    "diagnose_recovery_regime_results.txt"))

# ─── Data ────────────────────────────────────────────────────────────────────
PARENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(PARENT, "_yf_cache.pkl")
raw = pd.read_pickle(CACHE)
for col in ["CL=F", "^NSEI", "INR=X", "^INDIAVIX", "^TNX"]:
    raw[col] = raw[col].ffill()
fv = raw["GOLDBEES.NS"].first_valid_index()
raw.loc[raw.index >= fv, "GOLDBEES.NS"] = raw.loc[raw.index >= fv,
                                                  "GOLDBEES.NS"].ffill()
mom30 = load_nse_index_csv(os.path.join(PARENT, "data",
                                        "momentum30_history.csv"),
                           "NIFTYMOM30")
raw["NIFTYMOM30"] = mom30.reindex(raw.index).ffill()

# ─── Run base v1.5 (apply_tax=False so we can splice/group cleanly) ──────────
c = make_combiner(rotate_stress=True, use_momentum_gold=True)
ms = MacroStrategy(c, target="^NSEI", gold_target="GOLDBEES.NS",
                   long_target="NIFTYMOM30", long_cost_bps=LONG_BPS_MOM30,
                   nifty_cost_bps=SHORT_BPS, gold_cost_bps=GOLD_BPS,
                   cash_yield_haircut_bps=HAIRCUT_BPS, apply_tax=False)
res = ms.run(raw)
is_mask = (res.index >= IS_START) & (res.index <= IS_END)
idx = res.index[is_mask]
nifty_pos = res.loc[is_mask, "nifty_position"]
gold_pos  = res.loc[is_mask, "gold_position"]
strat_pretax = res.loc[is_mask, "strategy_return_pretax"]

# Asset returns aligned to idx
ret_mom  = raw["NIFTYMOM30"].pct_change().reindex(idx).fillna(0.0)
ret_nif  = raw["^NSEI"].pct_change().reindex(idx).fillna(0.0)
ret_gold = raw["GOLDBEES.NS"].pct_change().reindex(idx).fillna(0.0).clip(-0.5, 0.5)
repo = build_rbi_repo_rate_series(idx)
ret_cash = ((repo - HAIRCUT_BPS / 10000).clip(lower=0) / 252).reindex(idx).fillna(0.0)

# ─── Dynamic A: bull → 100% Mom30, bear → 100% cash ─────────────────────────
rf = RegimeFilter(window=100)
bull_full = rf.bull_mask(raw)
bull = bull_full.reindex(idx).fillna(False)
dyn_a_long = bull.astype(float)
dyn_a_long_yest = dyn_a_long.shift(1, fill_value=0.0)
dyn_a_pretax = (dyn_a_long_yest * ret_mom +
                (1 - dyn_a_long_yest) * ret_cash -
                dyn_a_long.diff().abs().fillna(0) * LONG_BPS_MOM30 / 10000)

# ─── Identify stress episodes (each contiguous non-long stretch) ─────────────
long_mask = (nifty_pos == 1.0)
non_long = ~long_mask
prev_non_long = non_long.shift(1, fill_value=True)
re_entry_mask = (~non_long) & prev_non_long  # today long, yesterday not
re_entries = idx[re_entry_mask.values]

episodes = []
n = len(idx)
for re_dt in re_entries:
    i_re = idx.get_loc(re_dt)
    # Walk back to find the start of the flat stretch
    j = i_re - 1
    while j >= 0 and non_long.iloc[j]:
        j -= 1
    flat_start = idx[j + 1] if j + 1 <= i_re - 1 else None
    flat_end   = idx[i_re - 1] if i_re > 0 else None
    if flat_start is None:
        continue
    flat_len = i_re - (j + 1)
    rec_end_i = min(i_re + RECOVERY_WINDOW, n)
    rec_end_dt = idx[rec_end_i - 1]
    # Classify the flat stretch as bear-driven or bull-flat-driven (slow-stress)
    flat_idx = idx[j + 1 : i_re]
    bull_during_flat = bull.loc[flat_idx]
    bear_days = int((~bull_during_flat).sum())
    bull_flat_days = int(bull_during_flat.sum())
    label = ("bear-only" if bull_flat_days == 0 else
             "bull-flat-only" if bear_days == 0 else "mixed")
    episodes.append({
        "flat_start": flat_start, "flat_end": flat_end,
        "re_entry": re_dt, "rec_end": rec_end_dt,
        "flat_len": flat_len, "bear_days": bear_days,
        "bull_flat_days": bull_flat_days, "label": label,
        "i_re": i_re, "rec_end_i": rec_end_i,
    })

# ─── Part A: leak by sub-period, aggregated by year ─────────────────────────
def sum_in_range(series, dt_start, dt_end):
    sl = series[(series.index >= dt_start) & (series.index <= dt_end)]
    return float(sl.sum())

excess = strat_pretax - dyn_a_pretax
year_buckets = {}
for ep in episodes:
    flat_idx_range = idx[(idx >= ep["flat_start"]) & (idx <= ep["flat_end"])]
    rec_idx_range  = idx[(idx >= ep["re_entry"])   & (idx <= ep["rec_end"])]
    # Skip empty
    if len(flat_idx_range) == 0 and len(rec_idx_range) == 0:
        continue
    flat_excess = float(excess.loc[flat_idx_range].sum()) if len(flat_idx_range) else 0.0
    rec_excess  = float(excess.loc[rec_idx_range].sum())  if len(rec_idx_range)  else 0.0
    # Attribute to the year of the period midpoint
    flat_year = (ep["flat_start"].year if len(flat_idx_range)
                 else ep["re_entry"].year)
    rec_year  = ep["re_entry"].year
    yb = year_buckets.setdefault(flat_year, {"flat_excess": 0.0,
                                              "rec_excess": 0.0,
                                              "n_flat_eps": 0,
                                              "n_rec_eps": 0,
                                              "flat_days": 0,
                                              "rec_days": 0})
    yb["flat_excess"] += flat_excess
    yb["flat_days"] += len(flat_idx_range)
    yb["n_flat_eps"] += 1 if len(flat_idx_range) else 0
    yb2 = year_buckets.setdefault(rec_year, {"flat_excess": 0.0,
                                              "rec_excess": 0.0,
                                              "n_flat_eps": 0,
                                              "n_rec_eps": 0,
                                              "flat_days": 0,
                                              "rec_days": 0})
    yb2["rec_excess"] += rec_excess
    yb2["rec_days"] += len(rec_idx_range)
    yb2["n_rec_eps"] += 1 if len(rec_idx_range) else 0

# ─── Part B: recovery window characterization ───────────────────────────────
# 100-DMA on Mom30 and trailing 6-month high
mom30_close = raw["NIFTYMOM30"].reindex(idx).ffill()
mom30_100dma = mom30_close.rolling(100, min_periods=1).mean()
mom30_above_100dma_pct = mom30_close / mom30_100dma - 1.0
mom30_6m_high = mom30_close.rolling(126, min_periods=1).max()
mom30_at_new_high = mom30_close >= mom30_6m_high

def days_until_full_trend(rec_start_i, rec_end_i):
    """Days until Mom30 is back ≥3% above its 100-DMA for ≥10 consecutive days."""
    if rec_start_i >= len(idx):
        return None
    streak = 0
    for k in range(rec_start_i, min(rec_end_i, len(idx))):
        if mom30_above_100dma_pct.iloc[k] >= 0.03:
            streak += 1
            if streak >= 10:
                return k - rec_start_i + 1 - 9  # day on which streak STARTED
        else:
            streak = 0
    return None

def days_until_new_6m_high(rec_start_i, rec_end_i):
    if rec_start_i >= len(idx):
        return None
    for k in range(rec_start_i, min(rec_end_i, len(idx))):
        if mom30_at_new_high.iloc[k]:
            return k - rec_start_i + 1
    return None

recovery_window_stats = []
for ep in episodes:
    rec_i0 = ep["i_re"]
    rec_i1 = ep["rec_end_i"]
    if rec_i0 >= n: continue
    win_idx = idx[rec_i0:rec_i1]
    if len(win_idx) < 5: continue
    # Cumulative returns within window
    cr_mom  = float((1 + ret_mom.iloc[rec_i0:rec_i1]).prod() - 1)
    cr_nif  = float((1 + ret_nif.iloc[rec_i0:rec_i1]).prod() - 1)
    cr_gold = float((1 + ret_gold.iloc[rec_i0:rec_i1]).prod() - 1)
    cr_cash = float((1 + ret_cash.iloc[rec_i0:rec_i1]).prod() - 1)
    # Realized vol
    vol_mom_window = float(ret_mom.iloc[rec_i0:rec_i1].std() * np.sqrt(252))
    # Choppiness: 100-DMA crossings of NIFTY 50
    nifty_close = raw["^NSEI"].reindex(idx).ffill()
    nifty_100 = nifty_close.rolling(100, min_periods=1).mean()
    above = (nifty_close > nifty_100).iloc[rec_i0:rec_i1]
    crossings = int((above != above.shift(1)).sum() - 1)  # subtract the artificial first transition
    # Sign flips in Mom30 daily returns
    rs = ret_mom.iloc[rec_i0:rec_i1]
    sign_flips = int(((rs.shift(1) * rs) < 0).sum())
    # Time-to-full-trend
    days_3pct = days_until_full_trend(rec_i0, rec_i1)
    days_newhigh = days_until_new_6m_high(rec_i0, rec_i1)
    recovery_window_stats.append({
        "re_entry": ep["re_entry"], "label": ep["label"],
        "flat_len": ep["flat_len"],
        "cr_mom": cr_mom, "cr_nif": cr_nif,
        "cr_gold": cr_gold, "cr_cash": cr_cash,
        "vol_mom": vol_mom_window,
        "crossings": crossings, "sign_flips": sign_flips,
        "days_to_3pct_streak": days_3pct,
        "days_to_new_6m_high": days_newhigh,
        "win_len": len(win_idx),
    })

# ─── Part C: regime discrimination signals ──────────────────────────────────
vix = raw["^INDIAVIX"].reindex(idx).ffill()
inr = raw["INR=X"].reindex(idx).ffill()

vix_90z = (vix - vix.rolling(90).mean()) / vix.rolling(90).std()
vix_5d  = vix.pct_change(5)
vix_20d = vix.pct_change(20)
inr_20d = inr.pct_change(20)
# Stress-clearing inversion of legacy VIX+INR composite: higher = stress clearing
vix_10d = vix.pct_change(10)
inr_10d = inr.pct_change(10)
stress_clearing = -(vix_10d + inr_10d)
# Mom30 vs NIFTY 3-month RS
rs_3m = (mom30_close / raw["^NSEI"].reindex(idx).ffill()).pct_change(63)
# Mom30 distance above/below its 100 DMA
mom_dist_100dma = mom30_above_100dma_pct
# Days elapsed since strategy cleared stress (started long again)
days_since = np.full(len(idx), np.nan)
counter = -1
for i in range(len(idx)):
    if not long_mask.iloc[i]:
        counter = 0
    else:
        if counter < 0:
            days_since[i] = np.nan  # no prior stress
        else:
            counter += 1
            days_since[i] = counter
days_since_series = pd.Series(days_since, index=idx)

# Build labels: 1 = "recovery" (long-state, within 60 days of re-entry); 0 = "established-good"
recovery_label = pd.Series(False, index=idx)
for ep in episodes:
    rec_i0 = ep["i_re"]; rec_i1 = ep["rec_end_i"]
    for k in range(rec_i0, min(rec_i1, len(idx))):
        if long_mask.iloc[k]:
            recovery_label.iloc[k] = True
established = long_mask & (~recovery_label)
recovery_only = long_mask & recovery_label

signals = {
    "VIX level":              vix,
    "VIX 90d z-score":        vix_90z,
    "VIX 5d trend":           vix_5d,
    "VIX 20d trend":          vix_20d,
    "INR 20d trend":          inr_20d,
    "Stress-clearing (inv composite)": stress_clearing,
    "Mom30/NIFTY 3m RS":      rs_3m,
    "Mom30 dist. above 100DMA": mom_dist_100dma,
    "Days since stress cleared": days_since_series,
}

def auc_score(values, labels):
    """AUC where label=1 is 'recovery', label=0 is 'established'."""
    mask = (~values.isna()) & (labels | ~labels)  # drop NaN values
    v = values[mask]; l = labels[mask]
    n_pos = int(l.sum()); n_neg = int(len(l) - n_pos)
    if n_pos == 0 or n_neg == 0:
        return np.nan
    ranks = v.rank(method="average")
    sum_pos_ranks = float(ranks[l].sum())
    auc = (sum_pos_ranks - n_pos * (n_pos + 1) / 2) / (n_pos * n_neg)
    return auc

def smd(values, labels):
    """Standardized mean difference (recovery - established) / pooled_std."""
    mask = (~values.isna())
    v = values[mask]; l = labels[mask]
    v_pos = v[l]; v_neg = v[~l]
    if len(v_pos) == 0 or len(v_neg) == 0:
        return np.nan
    var_p = v_pos.var(); var_n = v_neg.var()
    pooled = float(np.sqrt((var_p + var_n) / 2)) if (var_p + var_n) > 0 else 0
    if pooled == 0:
        return np.nan
    return float((v_pos.mean() - v_neg.mean()) / pooled)

# ─── Output ──────────────────────────────────────────────────────────────────
lines = []
def out(s=""): lines.append(s); print(s)

out("=" * 130)
out("  RECOVERY-REGIME DIAGNOSTIC — v1.5 strategy vs Dynamic A")
out("=" * 130)
out(f"  IS window: {IS_START} → {IS_END}  ({len(idx)} trading days)")
out(f"  Stress episodes (contiguous non-long stretches): {len(episodes)}")
out(f"  Recovery window definition: first {RECOVERY_WINDOW} trading days after each re-entry to long.")
out(f"  Losing-vs-DynA years under investigation: {LOSING_YEARS}")
out()

# ─── Part A ──────────────────────────────────────────────────────────────────
out("=" * 130)
out("  PART A — LEAK LOCALIZATION (flat sub-period vs recovery sub-period, vs Dynamic A)")
out("=" * 130)
out(f"  Excess = strategy pretax − Dynamic A pretax. Aggregated by year.")
out(f"  Flat = non-long days during a stress episode (strategy in flat/short/gold).")
out(f"  Recovery = first {RECOVERY_WINDOW} trading days after each re-entry to long.")
out()
out(f"  {'Year':<6} {'Flat days':>11} {'Flat excess':>13} {'Rec days':>10} "
    f"{'Rec excess':>12} {'Total excess':>14} {'Year tag':>10}")
out(f"  {'-'*6} {'-'*11} {'-'*13} {'-'*10} {'-'*12} {'-'*14} {'-'*10}")
yearly_total_excess = {}
for y in sorted(year_buckets):
    b = year_buckets[y]
    total = b["flat_excess"] + b["rec_excess"]
    yearly_total_excess[y] = total
    tag = "LOSS-vs-A" if y in LOSING_YEARS else ""
    out(f"  {y:<6} {b['flat_days']:>11d} {b['flat_excess']*100:+12.2f}pp "
        f"{b['rec_days']:>10d} {b['rec_excess']*100:+11.2f}pp "
        f"{total*100:+13.2f}pp {tag:>10}")
out()

# Sub-totals across LOSING_YEARS
flat_loss_sum = sum(year_buckets.get(y, {}).get("flat_excess", 0) for y in LOSING_YEARS)
rec_loss_sum  = sum(year_buckets.get(y, {}).get("rec_excess", 0) for y in LOSING_YEARS)
out(f"  Sum across LOSS-vs-A years {LOSING_YEARS}:")
out(f"    flat sub-period excess:     {flat_loss_sum*100:+8.2f}pp")
out(f"    recovery sub-period excess: {rec_loss_sum*100:+8.2f}pp")
out(f"    combined:                   {(flat_loss_sum+rec_loss_sum)*100:+8.2f}pp")
out()
if abs(rec_loss_sum) > abs(flat_loss_sum):
    out("  ⇒ Leak in losing years dominated by RECOVERY sub-periods (post-re-entry).")
elif abs(flat_loss_sum) > abs(rec_loss_sum):
    out("  ⇒ Leak in losing years dominated by FLAT sub-periods (during stress).")
else:
    out("  ⇒ Leak roughly split between flat and recovery sub-periods.")
out()

# ─── Part A — episode-level detail for losing years ─────────────────────────
out("=" * 130)
out(f"  PART A.2 — Episode-by-episode for the LOSS-vs-A years ({LOSING_YEARS})")
out("=" * 130)
out(f"  {'Re-entry':<12} {'Flat→':<24} {'Flat days':>10} {'Flat lbl':<14} "
    f"{'Flat excess':>13} {'Rec end':<12} {'Rec excess':>12}")
out(f"  {'-'*12} {'-'*24} {'-'*10} {'-'*14} {'-'*13} {'-'*12} {'-'*12}")
for ep in episodes:
    if ep["re_entry"].year not in LOSING_YEARS:
        continue
    flat_idx_range = idx[(idx >= ep["flat_start"]) & (idx <= ep["flat_end"])]
    rec_idx_range  = idx[(idx >= ep["re_entry"])   & (idx <= ep["rec_end"])]
    flat_ex = float(excess.loc[flat_idx_range].sum()) if len(flat_idx_range) else 0.0
    rec_ex  = float(excess.loc[rec_idx_range].sum())  if len(rec_idx_range)  else 0.0
    flat_range = f"{ep['flat_start'].date()}→{ep['flat_end'].date()}"
    out(f"  {ep['re_entry'].date()!s:<12} {flat_range:<24} {ep['flat_len']:>10d} "
        f"{ep['label']:<14} {flat_ex*100:+12.2f}pp {ep['rec_end'].date()!s:<12} "
        f"{rec_ex*100:+11.2f}pp")
out()

# ─── Part B ──────────────────────────────────────────────────────────────────
out("=" * 130)
out("  PART B — RECOVERY WINDOW CHARACTERIZATION (one row per re-entry)")
out("=" * 130)
out(f"  Trend-established defs: (a) Mom30 ≥3% above 100-DMA for ≥10 consecutive days,")
out(f"                          (b) Mom30 makes a new 6-month high.")
out(f"  Vol = annualized realized std of Mom30 daily returns in window.")
out(f"  Choppy crossings = # of times NIFTY crosses its 100-DMA inside window.")
out(f"  Sign flips = # of times Mom30 daily return changes sign within window.")
out()
out(f"  {'Re-entry':<12} {'FlatL':>5} {'Lbl':<10} {'Win':>4} "
    f"{'Mom':>7} {'NIF':>7} {'Gold':>7} {'Cash':>6} "
    f"{'Vol':>6} {'XingsN50':>9} {'SignFl':>7} "
    f"{'D→3%MA':>7} {'D→6mHi':>7}")
out("  " + "-"*12 + " " + "-"*5 + " " + "-"*10 + " " + "-"*4 + " " +
    "-"*7 + " " + "-"*7 + " " + "-"*7 + " " + "-"*6 + " " +
    "-"*6 + " " + "-"*9 + " " + "-"*7 + " " + "-"*7 + " " + "-"*7)
for r in recovery_window_stats:
    d3 = f"{r['days_to_3pct_streak']}" if r['days_to_3pct_streak'] else "—"
    dh = f"{r['days_to_new_6m_high']}" if r['days_to_new_6m_high'] else "—"
    out(f"  {r['re_entry'].date()!s:<12} {r['flat_len']:>5d} {r['label'][:10]:<10} "
        f"{r['win_len']:>4d} "
        f"{r['cr_mom']*100:+6.2f}% {r['cr_nif']*100:+6.2f}% "
        f"{r['cr_gold']*100:+6.2f}% {r['cr_cash']*100:+5.2f}% "
        f"{r['vol_mom']*100:>5.1f}% {r['crossings']:>9d} {r['sign_flips']:>7d} "
        f"{d3:>7} {dh:>7}")
out()

# Aggregates
def agg_mean(vals): return float(np.mean([v for v in vals if v is not None]))
nrows = len(recovery_window_stats)
if nrows:
    out(f"  Aggregate across {nrows} recovery windows:")
    out(f"    Mean window cumulative return — Mom30: {agg_mean([r['cr_mom'] for r in recovery_window_stats])*100:+.2f}%, "
        f"NIFTY: {agg_mean([r['cr_nif'] for r in recovery_window_stats])*100:+.2f}%, "
        f"Gold: {agg_mean([r['cr_gold'] for r in recovery_window_stats])*100:+.2f}%, "
        f"Cash: {agg_mean([r['cr_cash'] for r in recovery_window_stats])*100:+.2f}%")
    out(f"    Mean realized vol (Mom30): {agg_mean([r['vol_mom'] for r in recovery_window_stats])*100:.1f}%")
    out(f"    Mean NIFTY 100-DMA crossings per 60d window: "
        f"{agg_mean([r['crossings'] for r in recovery_window_stats]):.2f}")
    out(f"    Mean sign-flips (Mom30 daily return) per window: "
        f"{agg_mean([r['sign_flips'] for r in recovery_window_stats]):.2f}")
    d3_vals = [r['days_to_3pct_streak'] for r in recovery_window_stats
               if r['days_to_3pct_streak'] is not None]
    dh_vals = [r['days_to_new_6m_high'] for r in recovery_window_stats
               if r['days_to_new_6m_high'] is not None]
    out(f"    Windows hitting Mom30 ≥3% above 100-DMA streak: {len(d3_vals)}/{nrows} "
        f"(median days to event: {int(np.median(d3_vals)) if d3_vals else '—'})")
    out(f"    Windows hitting new 6-month high: {len(dh_vals)}/{nrows} "
        f"(median days to event: {int(np.median(dh_vals)) if dh_vals else '—'})")
out()

# Best asset in recovery windows
mom_wins  = sum(1 for r in recovery_window_stats if r['cr_mom']  >= max(r['cr_nif'], r['cr_gold'], r['cr_cash']))
nif_wins  = sum(1 for r in recovery_window_stats if r['cr_nif']  >  max(r['cr_mom'], r['cr_gold'], r['cr_cash']))
gold_wins = sum(1 for r in recovery_window_stats if r['cr_gold'] >  max(r['cr_mom'], r['cr_nif'], r['cr_cash']))
cash_wins = sum(1 for r in recovery_window_stats if r['cr_cash'] >  max(r['cr_mom'], r['cr_nif'], r['cr_gold']))
out(f"  Per-window winning asset: Mom30 {mom_wins}, NIFTY {nif_wins}, "
    f"Gold {gold_wins}, Cash {cash_wins} (of {nrows}).")
out()

# ─── Part C ──────────────────────────────────────────────────────────────────
out("=" * 130)
out("  PART C — REGIME DISCRIMINATION SIGNALS (recovery days vs established-good days)")
out("=" * 130)
n_rec = int(recovery_only.sum()); n_est = int(established.sum())
out(f"  Population: {n_rec} recovery-window long-state days, {n_est} established-good long-state days.")
out(f"  AUC interpretation: 0.5 = no discrimination; >0.7 = useful; <0.3 = useful with sign flip.")
out(f"  |SMD| > 0.5 = moderate signal; > 0.8 = large.")
out()
out(f"  {'Signal':<32} {'mean(rec)':>11} {'mean(est)':>11} {'med(rec)':>10} "
    f"{'med(est)':>10} {'|SMD|':>7} {'AUC':>6}")
out("  " + "-"*32 + " " + "-"*11 + " " + "-"*11 + " " + "-"*10 + " " + "-"*10 + " " + "-"*7 + " " + "-"*6)
rows_p3 = []
for name, sig in signals.items():
    auc = auc_score(sig, recovery_only)
    s = smd(sig, recovery_only)
    rec_v = sig[recovery_only].dropna()
    est_v = sig[established].dropna()
    rows_p3.append((name, auc, s))
    out(f"  {name:<32} {rec_v.mean():>10.3f} {est_v.mean():>10.3f} "
        f"{rec_v.median():>9.3f} {est_v.median():>9.3f} "
        f"{abs(s) if not np.isnan(s) else float('nan'):>7.3f} "
        f"{auc:>6.3f}")
out()
# Rank by discrimination (max(AUC, 1-AUC))
rows_p3_ranked = sorted(rows_p3, key=lambda r: -max(r[1], 1 - r[1]) if not np.isnan(r[1]) else 1)
out(f"  Ranked by |AUC − 0.5| (most discriminating first):")
for name, auc, s in rows_p3_ranked:
    direction = "rec > est" if (not np.isnan(s) and s > 0) else "rec < est"
    out(f"    {name:<32}  AUC={auc:.3f}  |SMD|={abs(s):.3f}  ({direction})")
out()

# ─── Plain-English read ──────────────────────────────────────────────────────
out("=" * 130)
out("  PLAIN-ENGLISH READ")
out("=" * 130)
out()
# Verdict: flat or recovery?
abs_flat = abs(flat_loss_sum); abs_rec = abs(rec_loss_sum)
verdict_loc = "RECOVERY sub-periods" if abs_rec > abs_flat else \
              "FLAT sub-periods" if abs_flat > abs_rec else "SPLIT roughly evenly"
out(f"(1) WHERE IS THE LEAK IN LOSING YEARS {LOSING_YEARS}?")
out(f"    Combined flat-period excess: {flat_loss_sum*100:+.2f}pp")
out(f"    Combined recovery excess:    {rec_loss_sum*100:+.2f}pp")
out(f"    ⇒ Leak is dominated by {verdict_loc}.")
out()
out(f"(2) RECOVERY-WINDOW SHAPE (60 trading days post-re-entry):")
if nrows:
    out(f"    Typical window has mean ~{agg_mean([r['crossings'] for r in recovery_window_stats]):.1f} "
        f"NIFTY-100DMA crossings and ~{agg_mean([r['sign_flips'] for r in recovery_window_stats]):.1f} "
        f"Mom30 sign-flips — i.e., it is choppy.")
    out(f"    Mean Mom30 cumret in window: "
        f"{agg_mean([r['cr_mom'] for r in recovery_window_stats])*100:+.2f}% vs "
        f"NIFTY {agg_mean([r['cr_nif'] for r in recovery_window_stats])*100:+.2f}%, "
        f"Gold {agg_mean([r['cr_gold'] for r in recovery_window_stats])*100:+.2f}%, "
        f"Cash {agg_mean([r['cr_cash'] for r in recovery_window_stats])*100:+.2f}%.")
    out(f"    Best asset per window — Mom30 wins {mom_wins} of {nrows}; "
        f"NIFTY wins {nif_wins}; Gold {gold_wins}; Cash {cash_wins}.")
    if dh_vals:
        out(f"    Median days to a new 6m high: {int(np.median(dh_vals))} of 60 "
            f"(in {len(dh_vals)} of {nrows} windows).")
    if d3_vals:
        out(f"    Median days to Mom30 ≥3% above 100DMA streak: "
            f"{int(np.median(d3_vals))} (in {len(d3_vals)} of {nrows} windows).")
out()
out(f"(3) MOST DISCRIMINATING SIGNALS (recovery vs established-good):")
for name, auc, s in rows_p3_ranked[:5]:
    direction = "↑ in recovery" if (not np.isnan(s) and s > 0) else "↓ in recovery"
    out(f"    {name:<32}  AUC={auc:.3f}  |SMD|={abs(s):.3f}  ({direction})")
out()
out("    Reading: signals with AUC far from 0.5 (or |SMD| > 0.5) are candidates")
out("    for a conviction score that would let the strategy stay scaled-back")
out("    during recovery windows and scale up to full Mom30 only once the")
out("    'established-good' regime is confirmed.")
out()

with open(OUTPUT_PATH, "w") as f:
    f.write("\n".join(lines))
print(f"\nSaved to {OUTPUT_PATH}", file=sys.stderr)
