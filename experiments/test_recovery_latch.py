"""
test_recovery_latch.py — DIAGNOSTIC.

Tests a recovery-state blend with a one-way latch into 100% Mom30, applied
on top of base + V2. Other engines (short, panic, slow-stress, bear, V2) are
NOT touched — the new state machine only modifies the long-side allocation
on calm-long days (long state AND not inside a V2 window).

State machine (long-side only):
  NON_LONG       — strategy is in flat/short/gold; use base+V2 behavior.
  RECOVERY       — long, V2 inactive, post-stress, latch hasn't fired yet.
                   Allocation: inverse-vol Mom30/gold blend (G10 gate ON) or
                   vol-targeted Mom30 + cash (G10 gate OFF). NO NIFTY.
  ESTABLISHED    — long, V2 inactive, latch has fired. Allocation: 100% Mom30.

Transitions:
  NON_LONG → RECOVERY     : strategy re-enters long after any non-long stretch
  RECOVERY → ESTABLISHED  : latch trigger fires (one-way door, no flip back
                            unless a fresh non-long episode happens)
  ESTABLISHED → NON_LONG  : any non-long day (handled by base+V2)
  V2 active                : V2 takes precedence over state allocation; state
                            is preserved (so when V2 ends, allocation resumes)

Latch variants (pre-specified, no year-tuning):
  T3, T5, T8       — Mom30 ≥ X% above its own 100-DMA (X = 3, 5, 8)
  TM3, TM5, TM8    — same X AND macro: VIX 90d z-score < 0 AND INR 20d
                     trend not negative

Vol target (when gate OFF): base+V2 full-sample realized vol (pre-tax) —
computed, not tuned.
"""

import os, sys
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from strategy import (
    make_combiner, MacroStrategy, RegimeFilter,
    load_nse_index_csv, build_rbi_repo_rate_series,
    metrics, apply_annual_tax,
)

WARMUP, IS_START, IS_END = "2006-01-01", "2008-04-01", "2025-12-31"
LONG_BPS_MOM30, LONG_BPS_NIFTY, GOLD_BPS, SHORT_BPS, HAIRCUT_BPS = 6, 3, 5, 3, 100
TAX = 0.15
VOL_WIN = 60
GOLD_GATE_INR_THR = 0.005
GOLD_GATE_US10Y_THR = 0.0
GOLD_GATE_CAP = 0.10
OUTPUT_PATH = os.path.normpath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..",
    "test_recovery_latch_results.txt"))

LOSING_YEARS = [2011, 2013, 2014, 2022]  # vs Dyn A
MOM_LOSS_YEARS = [2018, 2022, 2025]      # Mom30 vs NIFTY structural

# ─── Data ────────────────────────────────────────────────────────────────────
PARENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
raw = pd.read_pickle(os.path.join(PARENT, "_yf_cache.pkl"))
for col in ["CL=F", "^NSEI", "INR=X", "^INDIAVIX", "^TNX"]:
    raw[col] = raw[col].ffill()
fv = raw["GOLDBEES.NS"].first_valid_index()
raw.loc[raw.index >= fv, "GOLDBEES.NS"] = raw.loc[raw.index >= fv,
                                                  "GOLDBEES.NS"].ffill()
mom30_p = load_nse_index_csv(os.path.join(PARENT, "data",
                                          "momentum30_history.csv"),
                             "NIFTYMOM30")
raw["NIFTYMOM30"] = mom30_p.reindex(raw.index).ffill()

# ─── Run base v1.5 (Mom30) and NIFTY for V2 ──────────────────────────────────
def run(long_target, long_bps):
    c = make_combiner(rotate_stress=True, use_momentum_gold=True)
    ms = MacroStrategy(c, target="^NSEI", gold_target="GOLDBEES.NS",
                       long_target=long_target, long_cost_bps=long_bps,
                       nifty_cost_bps=SHORT_BPS, gold_cost_bps=GOLD_BPS,
                       cash_yield_haircut_bps=HAIRCUT_BPS, apply_tax=False)
    return ms.run(raw)

print("Running base (Mom30) ...", file=sys.stderr)
res_mom = run("NIFTYMOM30", LONG_BPS_MOM30)
print("Running NIFTY baseline (for V2) ...", file=sys.stderr)
res_nif = run("^NSEI", LONG_BPS_NIFTY)
is_mask = (res_mom.index >= IS_START) & (res_mom.index <= IS_END)
idx = res_mom.index[is_mask]
nifty_pos = res_mom.loc[is_mask, "nifty_position"]
gold_pos  = res_mom.loc[is_mask, "gold_position"]
strat_pretax = res_mom.loc[is_mask, "strategy_return_pretax"]
nif_pretax   = res_nif.loc[is_mask, "strategy_return_pretax"]

# ─── Asset returns aligned to idx ────────────────────────────────────────────
ret_mom  = raw["NIFTYMOM30"].pct_change().reindex(idx).fillna(0.0)
ret_nif  = raw["^NSEI"].pct_change().reindex(idx).fillna(0.0)
ret_gold = raw["GOLDBEES.NS"].pct_change().reindex(idx).fillna(0.0).clip(-0.5, 0.5)
repo = build_rbi_repo_rate_series(idx)
ret_cash = ((repo - HAIRCUT_BPS / 10000).clip(lower=0) / 252).reindex(idx).fillna(0.0)
gold_available = raw["GOLDBEES.NS"].reindex(idx).notna()

# ─── V2 windows (preserved from base + V2) ───────────────────────────────────
rf = RegimeFilter(window=100)
bull_full = rf.bull_mask(raw)
bull = bull_full.reindex(idx).fillna(False)
prev_bull = bull.shift(1, fill_value=False)
flip_mask = bull & (~prev_bull)
if flip_mask.iloc[0]:
    p = bull_full.index.get_loc(idx[0])
    if p > 0 and bool(bull_full.iloc[p - 1]):
        flip_mask.iloc[0] = False
flips = idx[flip_mask.values]
def preceding_bear_dd(d):
    p = bull_full.index.get_loc(d)
    if p == 0: return None
    end = p - 1; s = end
    while s > 0 and not bool(bull_full.iloc[s - 1]): s -= 1
    w = raw["^NSEI"].iloc[s:end+1]
    if len(w) == 0: return 0.0
    return abs(float((w / w.cummax() - 1.0).min()))
v2_flips = [d for d in flips if (dd := preceding_bear_dd(d)) is not None and dd >= 0.15]
V2_DAYS = 60
v2_active = pd.Series(False, index=idx)
for f in v2_flips:
    i0 = idx.get_loc(f)
    v2_active.iloc[i0:min(i0 + V2_DAYS, len(idx))] = True

long_mask = (nifty_pos == 1.0)
base_v2_pretax = strat_pretax.where(~(long_mask & v2_active), nif_pretax)
target_vol = float(base_v2_pretax.std() * np.sqrt(252))

# ─── G10 gate per day (production thresholds) ────────────────────────────────
gold_10d  = raw["GOLDBEES.NS"].pct_change(10).reindex(idx)
inr_10d   = raw["INR=X"].pct_change(10).reindex(idx)
us10y_20d = raw["^TNX"].pct_change(20).reindex(idx)
g10_gate = (
    (gold_10d > 0) & (gold_10d <= GOLD_GATE_CAP) &
    (inr_10d > GOLD_GATE_INR_THR) &
    (us10y_20d < GOLD_GATE_US10Y_THR) &
    gold_available
).fillna(False)

# ─── Rolling vols (60-day annualized; shifted by 1 for no-lookahead) ────────
sigma_m = (ret_mom.rolling(VOL_WIN).std() * np.sqrt(252)).shift(1)
sigma_g = (ret_gold.rolling(VOL_WIN).std() * np.sqrt(252)).shift(1)

# ─── Latch trigger inputs ────────────────────────────────────────────────────
mom_close = raw["NIFTYMOM30"].reindex(idx).ffill()
mom_100dma = mom_close.rolling(100, min_periods=1).mean()
mom_dist_dma = mom_close / mom_100dma - 1.0  # signed; ≥0 = above DMA

vix = raw["^INDIAVIX"].reindex(idx).ffill()
vix_90z = (vix - vix.rolling(90).mean()) / vix.rolling(90).std()

inr = raw["INR=X"].reindex(idx).ffill()
inr_20d = inr.pct_change(20)

# ─── Latch variants ──────────────────────────────────────────────────────────
def latch_T(x_pct):
    def fn(i):
        v = mom_dist_dma.iloc[i]
        return (not pd.isna(v)) and (v >= x_pct)
    return fn

def latch_TM(x_pct):
    def fn(i):
        v = mom_dist_dma.iloc[i]
        z = vix_90z.iloc[i]
        r = inr_20d.iloc[i]
        if pd.isna(v) or pd.isna(z) or pd.isna(r): return False
        return (v >= x_pct) and (z < 0) and (r >= 0)
    return fn

VARIANTS = {
    "T3  trend ≥3%":              latch_T(0.03),
    "T5  trend ≥5%":              latch_T(0.05),
    "T8  trend ≥8%":              latch_T(0.08),
    "TM3 trend ≥3% + macro":      latch_TM(0.03),
    "TM5 trend ≥5% + macro":      latch_TM(0.05),
    "TM8 trend ≥8% + macro":      latch_TM(0.08),
}

# ─── Simulation ──────────────────────────────────────────────────────────────
ASSETS = ["mom", "nif", "gold", "cash"]
COST_BPS = {"mom": LONG_BPS_MOM30, "nif": LONG_BPS_NIFTY,
            "gold": GOLD_BPS, "cash": 0}

def base_nonlong_weights(i):
    """Weights on a non-long day reflecting base's position."""
    if nifty_pos.iloc[i] == -1.0:
        return (0.0, -1.0, 0.0, 0.0)  # short ^NSEI
    if gold_pos.iloc[i] == 1.0:
        return (0.0, 0.0, 1.0, 0.0)
    return (0.0, 0.0, 0.0, 1.0)  # flat → cash

def recovery_weights(i):
    """Recovery state allocation per spec: inverse-vol Mom30/Gold when G10
    on (uncapped), else Mom30 vol-targeted + cash. No NIFTY."""
    sm = sigma_m.iloc[i]
    if g10_gate.iloc[i]:
        sg = sigma_g.iloc[i]
        if pd.isna(sm) or pd.isna(sg) or sm <= 0 or sg <= 0:
            return (1.0, 0.0, 0.0, 0.0)
        inv_m, inv_g = 1.0/sm, 1.0/sg
        s = inv_m + inv_g
        return (inv_m/s, 0.0, inv_g/s, 0.0)
    else:
        if pd.isna(sm) or sm <= 0:
            return (1.0, 0.0, 0.0, 0.0)
        scale = min(target_vol / sm, 1.0)
        return (scale, 0.0, 0.0, 1.0 - scale)

def simulate(latch_fn):
    n = len(idx)
    state = "NON_LONG"
    w_prev = (0.0, 0.0, 0.0, 1.0)
    daily_ret = np.zeros(n)
    daily_cost = np.zeros(n)
    states = []
    weights = []
    days_in_recovery_per_window = []
    cur_recovery_start_i = None
    cur_recovery_days = 0
    cur_recovery_latched = False
    cur_recovery_window_idx_list = []
    recovery_windows = []  # list of dicts per window

    for i in range(n):
        today_long = bool(long_mask.iloc[i])
        today_v2   = bool(v2_active.iloc[i]) and today_long

        # State transitions
        if not today_long:
            if state in ("RECOVERY", "ESTABLISHED"):
                # Close out current recovery window if active
                if state == "RECOVERY" and cur_recovery_start_i is not None:
                    recovery_windows.append({
                        "start_i": cur_recovery_start_i,
                        "end_i": i - 1,
                        "days": cur_recovery_days,
                        "latched": False,
                        "indices": list(cur_recovery_window_idx_list),
                    })
                cur_recovery_start_i = None
                cur_recovery_days = 0
                cur_recovery_latched = False
                cur_recovery_window_idx_list = []
            state = "NON_LONG"
        elif today_v2:
            # V2 takes over. Preserve state, but if NON_LONG yesterday set to RECOVERY
            if state == "NON_LONG":
                state = "RECOVERY"
                cur_recovery_start_i = i
                cur_recovery_days = 0
                cur_recovery_window_idx_list = []
            # During V2, we use V2's allocation regardless of state. We DO NOT
            # check the latch (V2 NIFTY-first window suppresses the recovery
            # state's latch evaluation by spec).
        else:
            # Long state, V2 inactive
            if state == "NON_LONG":
                state = "RECOVERY"
                cur_recovery_start_i = i
                cur_recovery_days = 0
                cur_recovery_window_idx_list = []
            if state == "RECOVERY":
                cur_recovery_days += 1
                cur_recovery_window_idx_list.append(i)
                if latch_fn(i):
                    state = "ESTABLISHED"
                    cur_recovery_latched = True
                    recovery_windows.append({
                        "start_i": cur_recovery_start_i,
                        "end_i": i,
                        "days": cur_recovery_days,
                        "latched": True,
                        "indices": list(cur_recovery_window_idx_list),
                    })
                    cur_recovery_start_i = None
                    cur_recovery_days = 0
                    cur_recovery_window_idx_list = []

        # Compute target weights for today
        if not today_long:
            w_tgt = base_nonlong_weights(i)
        elif today_v2:
            w_tgt = (0.0, 1.0, 0.0, 0.0)  # V2 = 100% NIFTY
        elif state == "RECOVERY":
            w_tgt = recovery_weights(i)
        else:  # ESTABLISHED
            w_tgt = (1.0, 0.0, 0.0, 0.0)

        # Costs and PnL
        delta = [abs(w_tgt[k] - w_prev[k]) for k in range(4)]
        cost = (delta[0]*COST_BPS["mom"] + delta[1]*COST_BPS["nif"] +
                delta[2]*COST_BPS["gold"] + delta[3]*COST_BPS["cash"]) / 10000.0
        daily_cost[i] = cost
        port = (w_prev[0]*ret_mom.iloc[i] + w_prev[1]*ret_nif.iloc[i] +
                w_prev[2]*ret_gold.iloc[i] + w_prev[3]*ret_cash.iloc[i])
        daily_ret[i] = port - cost
        states.append(state)
        weights.append(w_tgt)
        w_prev = w_tgt

    # Tail: if still in RECOVERY at end, record window
    if state == "RECOVERY" and cur_recovery_start_i is not None:
        recovery_windows.append({
            "start_i": cur_recovery_start_i,
            "end_i": len(idx) - 1,
            "days": cur_recovery_days,
            "latched": False,
            "indices": list(cur_recovery_window_idx_list),
        })

    pretax = pd.Series(daily_ret, index=idx)
    cost_series = pd.Series(daily_cost, index=idx)
    state_series = pd.Series(states, index=idx)
    wdf = pd.DataFrame(weights, index=idx, columns=ASSETS)
    return pretax, cost_series, state_series, wdf, recovery_windows

# Reference: base + V2
base_v2_posttax = apply_annual_tax(base_v2_pretax.fillna(0.0), tax_rate=TAX)

# Run variants
runs = {"base + V2": {"pretax": base_v2_pretax, "posttax": base_v2_posttax,
                       "state": None, "wdf": None, "rec_windows": None,
                       "cost": None}}
for name, fn in VARIANTS.items():
    print(f"Simulating {name} ...", file=sys.stderr)
    pretax, cost, state_series, wdf, rec_windows = simulate(fn)
    posttax = apply_annual_tax(pretax.fillna(0.0), tax_rate=TAX)
    runs[name] = {"pretax": pretax, "posttax": posttax,
                  "state": state_series, "wdf": wdf,
                  "rec_windows": rec_windows, "cost": cost}

# ─── Reporting helpers ───────────────────────────────────────────────────────
def year_ret(s, y):
    sl = s[s.index.year == y]
    return float((1 + sl).prod() - 1) if len(sl) else 0.0

def year_metrics(s, years):
    sl = s[s.index.year.isin(years)]
    if len(sl) < 2: return None
    return metrics(sl)

# ─── Sanity check: short/flat P&L identical to base+V2 ──────────────────────
# We test "engine output preserved" by checking days where positions were
# CARRIED OVER (yesterday and today same state). On transition days the daily
# pnl legitimately differs because yesterday's allocation differs across
# variants (recovery blend vs 100% Mom30 etc.); this is expected.
flat_today = (nifty_pos == 0.0) & (gold_pos == 0.0)
flat_yest  = flat_today.shift(1, fill_value=False)
flat_carry = flat_today & flat_yest   # truly flat, held overnight

short_today = (nifty_pos == -1.0)
short_yest  = short_today.shift(1, fill_value=False)
short_carry = short_today & short_yest  # truly short, held overnight

gold_today = (gold_pos == 1.0)
gold_yest  = gold_today.shift(1, fill_value=False)
gold_carry = gold_today & gold_yest

# Base contributions on carry days
short_contrib_base = float((-ret_nif[short_carry]).sum())
flat_pretax_base = float(base_v2_pretax[flat_carry].sum())
gold_pretax_base = float(base_v2_pretax[gold_carry].sum())

sanity_msgs = []
for name, r in runs.items():
    if r["wdf"] is None: continue
    w = r["wdf"]
    # Short engine: yesterday's nif weight × today's nif return on short-carry days
    nif_w_yest = w["nif"].shift(1, fill_value=0.0)
    short_contrib_var = float((nif_w_yest[short_carry] * ret_nif[short_carry]).sum())
    diff_s = short_contrib_var - short_contrib_base
    sanity_msgs.append((name, "short (carry)", short_contrib_var, diff_s, abs(diff_s) < 1e-10))
    # Flat engine: pretax on flat-carry days should equal base+V2
    flat_pretax_var = float(r["pretax"][flat_carry].sum())
    diff_f = flat_pretax_var - flat_pretax_base
    sanity_msgs.append((name, "flat (carry)", flat_pretax_var, diff_f, abs(diff_f) < 1e-8))
    # Gold engine: pretax on gold-carry days should equal base+V2 (gold rotation untouched)
    gold_pretax_var = float(r["pretax"][gold_carry].sum())
    diff_g = gold_pretax_var - gold_pretax_base
    sanity_msgs.append((name, "gold (carry)", gold_pretax_var, diff_g, abs(diff_g) < 1e-8))

# ─── Output ──────────────────────────────────────────────────────────────────
lines = []
def out(s=""): lines.append(s); print(s)

out("=" * 130)
out("  RECOVERY-LATCH TEST — long-side state machine on top of base + V2")
out("=" * 130)
out(f"  IS window: {IS_START} → {IS_END}  ({len(idx)} trading days)")
out(f"  Vol estimator: {VOL_WIN}d rolling std × sqrt(252). No-lookahead.")
out(f"  Vol target (base+V2 full-sample pre-tax realized): {target_vol*100:.2f}%")
out(f"  Long days: {int(long_mask.sum())}, V2-active long days: "
    f"{int((long_mask & v2_active).sum())}, "
    f"calm-long (subject to state machine): "
    f"{int((long_mask & ~v2_active).sum())}")
out(f"  Latch variants: {list(VARIANTS.keys())}")
out()

# Sanity
out("=" * 130)
out("  SANITY — short/flat P&L identical to base + V2 across variants")
out("=" * 130)
out(f"  Short engine contribution base+V2: {short_contrib_base*100:+.4f}%")
out(f"  Flat-day total pretax base+V2:     {flat_pretax_base*100:+.4f}%")
out()
all_ok = True
out(f"  {'Variant':<30} {'Test':<6} {'Value':>10} {'Diff':>12} {'OK'}")
for name, kind, val, diff, ok in sanity_msgs:
    if not ok: all_ok = False
    flag = "✓" if ok else "❌"
    out(f"  {name:<30} {kind:<6} {val*100:+9.4f}% {diff*100:+11.6f}pp  {flag}")
out()
if all_ok:
    out("  ✓ All variants preserve short and flat-day P&L. Directional engine untouched.")
else:
    out("  ⚠️  WARNING: short or flat P&L not preserved in some variants.")
out()

# Headline metrics
out("=" * 130)
out("  HEADLINE METRICS (post-tax, 15% annual-net)")
out("=" * 130)
base_m = metrics(runs["base + V2"]["posttax"])
out(f"  {'Variant':<30} {'CAGR':>8} {'Sharpe':>8} {'Calmar':>8} {'MaxDD':>9} "
    f"{'TO/yr':>8} {'ΔCAGR':>9} {'ΔSharpe':>9}")
out("  " + "-"*30 + " " + "-"*8 + " " + "-"*8 + " " + "-"*8 + " " + "-"*9 + " " +
    "-"*8 + " " + "-"*9 + " " + "-"*9)
def annual_turnover(wdf):
    if wdf is None: return 0.0
    return float(wdf.diff().abs().sum(axis=1).sum() / (len(wdf) / 252.0))
for name, r in runs.items():
    m = metrics(r["posttax"])
    to = annual_turnover(r.get("wdf"))
    d_c = m["cagr"] - base_m["cagr"]
    d_s = m["sharpe"] - base_m["sharpe"]
    if name == "base + V2":
        out(f"  {name:<30} {m['cagr']*100:+7.2f}% {m['sharpe']:>8.3f} "
            f"{m['calmar']:>8.2f} {m['max_dd']*100:+8.2f}% {'—':>8} {'—':>9} {'—':>9}")
    else:
        out(f"  {name:<30} {m['cagr']*100:+7.2f}% {m['sharpe']:>8.3f} "
            f"{m['calmar']:>8.2f} {m['max_dd']*100:+8.2f}% {to*100:>7.0f}% "
            f"{d_c*100:+8.2f}pp {d_s:+9.3f}")
out()

# Year-by-year
out("=" * 130)
out("  YEAR-BY-YEAR (post-tax)")
out("=" * 130)
years = sorted(set(idx.year))
hdr = f"  {'Year':<6}"
for name in runs: hdr += f" {name[:14]:>14}"
out(hdr)
out("  " + "-"*6 + " " + " ".join(["-"*14]*len(runs)))
for y in years:
    row = f"  {y:<6}"
    for name, r in runs.items():
        row += f" {year_ret(r['posttax'], y)*100:>13.2f}%"
    out(row)
out()

# Recovery split: clean vs choppy
# A "clean" recovery is one that latched within 10 days; "choppy" is >10 days
# OR never latched (window ended via non-long without latching).
out("=" * 130)
out("  RECOVERY SPLIT — clean (latched ≤10d) vs choppy (>10d or never latched)")
out("=" * 130)
out(f"  {'Variant':<30} {'# clean':>8} {'# choppy':>9} {'PnL in clean':>14} "
    f"{'PnL in choppy':>15} {'Base PnL clean':>16} {'Base PnL choppy':>17}")
out("  " + "-"*30 + " " + "-"*8 + " " + "-"*9 + " " + "-"*14 + " " + "-"*15 + " " +
    "-"*16 + " " + "-"*17)
for name, r in runs.items():
    if r["rec_windows"] is None: continue
    n_clean = 0; n_choppy = 0
    pnl_clean = 0.0; pnl_choppy = 0.0
    base_clean = 0.0; base_choppy = 0.0
    for w in r["rec_windows"]:
        idx_w = idx[w["start_i"]:w["end_i"] + 1]
        if not len(idx_w): continue
        pnl_var = float(r["pretax"].loc[idx_w].sum())
        pnl_base = float(base_v2_pretax.loc[idx_w].sum())
        if w["latched"] and w["days"] <= 10:
            n_clean += 1; pnl_clean += pnl_var; base_clean += pnl_base
        else:
            n_choppy += 1; pnl_choppy += pnl_var; base_choppy += pnl_base
    out(f"  {name:<30} {n_clean:>8d} {n_choppy:>9d} "
        f"{pnl_clean*100:+13.2f}pp {pnl_choppy*100:+14.2f}pp "
        f"{base_clean*100:+15.2f}pp {base_choppy*100:+16.2f}pp")
out()
# Net effect per category (variant minus base) — show separately
out(f"  Net effect of variant vs base+V2 within each recovery category:")
out(f"  {'Variant':<30} {'Δ clean (pp)':>14} {'Δ choppy (pp)':>15}")
for name, r in runs.items():
    if r["rec_windows"] is None: continue
    d_clean = 0.0; d_choppy = 0.0
    for w in r["rec_windows"]:
        idx_w = idx[w["start_i"]:w["end_i"] + 1]
        if not len(idx_w): continue
        pnl_var = float(r["pretax"].loc[idx_w].sum())
        pnl_base = float(base_v2_pretax.loc[idx_w].sum())
        d = pnl_var - pnl_base
        if w["latched"] and w["days"] <= 10:
            d_clean += d
        else:
            d_choppy += d
    out(f"  {name:<30} {d_clean*100:+13.2f}pp {d_choppy*100:+14.2f}pp")
out()

# Gold reality check
out("=" * 130)
out("  GOLD REALITY CHECK (during recovery state days)")
out("=" * 130)
out(f"  {'Variant':<30} {'Rec days':>9} {'Gate on %':>10} {'Avg gold w':>11} "
    f"{'Max gold w':>11} {'Gold P&L':>10}")
out("  " + "-"*30 + " " + "-"*9 + " " + "-"*10 + " " + "-"*11 + " " + "-"*11 + " " + "-"*10)
for name, r in runs.items():
    if r["wdf"] is None: continue
    in_rec = (r["state"] == "RECOVERY")
    n_rec = int(in_rec.sum())
    if n_rec == 0:
        out(f"  {name:<30} {0:>9d} {'—':>10} {'—':>11} {'—':>11} {'—':>10}")
        continue
    gate_on_pct = float(g10_gate[in_rec].mean()) * 100
    w = r["wdf"]
    avg_gold = float(w["gold"][in_rec].mean()) * 100
    max_gold = float(w["gold"][in_rec].max()) * 100
    # Gold P&L contribution during recovery: sum(w_gold.shift(1) * ret_gold) on recovery days
    gold_pnl = float((w["gold"].shift(1, fill_value=0.0)[in_rec] *
                      ret_gold[in_rec]).sum())
    out(f"  {name:<30} {n_rec:>9d} {gate_on_pct:>9.1f}% "
        f"{avg_gold:>10.1f}% {max_gold:>10.1f}% {gold_pnl*100:+9.2f}pp")
out()

# Latch behavior
out("=" * 130)
out("  LATCH BEHAVIOR — time in RECOVERY state before latching")
out("=" * 130)
out(f"  {'Variant':<30} {'# windows':>10} {'# latched':>10} "
    f"{'# never latched':>16} {'Median days→latch':>20} {'Mean days→latch':>17}")
out("  " + "-"*30 + " " + "-"*10 + " " + "-"*10 + " " + "-"*16 + " " + "-"*20 + " " + "-"*17)
for name, r in runs.items():
    if r["rec_windows"] is None: continue
    n_w = len(r["rec_windows"])
    latched = [w["days"] for w in r["rec_windows"] if w["latched"]]
    never = n_w - len(latched)
    med = int(np.median(latched)) if latched else 0
    mean = float(np.mean(latched)) if latched else 0
    out(f"  {name:<30} {n_w:>10d} {len(latched):>10d} {never:>16d} "
        f"{med:>20d} {mean:>16.1f}")
out()

# Good-year check: years where ESTABLISHED state dominates → should be ~same as base+V2
out("=" * 130)
out("  GOOD-YEAR CHECK — years dominated by ESTABLISHED state (should ≈ base+V2)")
out("=" * 130)
out(f"  Year-by-year Δ vs base+V2 (post-tax pp). 'Recovery share' = % of long days")
out(f"  in RECOVERY state for representative T5 variant.")
ref_var = "T5  trend ≥5%"
ref_state = runs[ref_var]["state"] if ref_var in runs else None
out(f"  {'Year':<6} {'Rec share':>11}  " +
    "  ".join(f"{n[:14]:>14}" for n in runs if n != "base + V2"))
out("  " + "-"*6 + " " + "-"*11 + "  " +
    "  ".join(["-"*14] * (len(runs) - 1)))
for y in years:
    y_idx = idx[idx.year == y]
    if not len(y_idx): continue
    if ref_state is not None:
        long_y = long_mask.loc[y_idx]
        if int(long_y.sum()) > 0:
            rec_y = (ref_state.loc[y_idx] == "RECOVERY") & long_y
            share = int(rec_y.sum()) / int(long_y.sum()) * 100
        else:
            share = 0
    else:
        share = 0
    row = f"  {y:<6} {share:>10.0f}%  "
    base_y = year_ret(runs["base + V2"]["posttax"], y)
    for n, r in runs.items():
        if n == "base + V2": continue
        var_y = year_ret(r["posttax"], y)
        row += f"  {(var_y - base_y)*100:>+12.2f}pp"
    out(row)
out()

# Plain-English read
out("=" * 130)
out("  PLAIN-ENGLISH READ")
out("=" * 130)
out()
# Best variant by Sharpe
best = max((k for k in runs if k != "base + V2"),
           key=lambda k: metrics(runs[k]["posttax"])["sharpe"])
best_m = metrics(runs[best]["posttax"])
out(f"Best variant by post-tax Sharpe: {best}")
out(f"  CAGR {best_m['cagr']*100:+.2f}% (Δ {(best_m['cagr']-base_m['cagr'])*100:+.2f}pp)  "
    f"Sharpe {best_m['sharpe']:.3f} (Δ {best_m['sharpe']-base_m['sharpe']:+.3f})  "
    f"MaxDD {best_m['max_dd']*100:+.2f}% (Δ {(best_m['max_dd']-base_m['max_dd'])*100:+.2f}pp)")
n_beat = sum(1 for k in VARIANTS
             if metrics(runs[k]["posttax"])["cagr"] > base_m["cagr"]
             and metrics(runs[k]["posttax"])["sharpe"] > base_m["sharpe"])
out(f"Variants beating base+V2 on BOTH CAGR and Sharpe: {n_beat} of {len(VARIANTS)}")
out()
# Trend-only vs trend+macro at each X
out("Trend-only vs trend+macro at each X (post-tax):")
for x in [3, 5, 8]:
    t = next(k for k in VARIANTS if k.startswith(f"T{x} "))
    tm = next(k for k in VARIANTS if k.startswith(f"TM{x} "))
    mt = metrics(runs[t]["posttax"]); mtm = metrics(runs[tm]["posttax"])
    out(f"  X={x}%:  T={mt['cagr']*100:+.2f}% CAGR, Sharpe {mt['sharpe']:.3f}  |  "
        f"TM={mtm['cagr']*100:+.2f}% CAGR, Sharpe {mtm['sharpe']:.3f}  "
        f"(Δ from adding macro: {(mtm['cagr']-mt['cagr'])*100:+.2f}pp CAGR)")
out()

with open(OUTPUT_PATH, "w") as f:
    f.write("\n".join(lines))
print(f"\nSaved to {OUTPUT_PATH}", file=sys.stderr)
