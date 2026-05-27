"""
diagnose_whipsaw_cost.py — DIAGNOSTIC.

Quantifies the cost of brief long→flat→long round-trips caused by the
100-DMA regime filter, and tests whether simple hysteresis rules would net
positive once lag-cost is paid in genuine downturns.

Part A — measure the whipsaw cost.
  Whipsaw episode = long→flat→long round-trip where the strategy re-enters
  long within 20 trading days of exiting. For each: round-trip cost, price-
  action P&L vs counterfactual (stayed long Mom30 through the chop), and
  100-DMA crossings inside the episode.

Part B — would a fix be worth it?
  Pre-specified hysteresis rules applied to the regime filter ONLY:
    R1 — symmetric band ±2% around the 100-DMA
    R2 — symmetric band ±3% around the 100-DMA
    R3 — minimum hold of 5 trading days, with a −5% escape (drop from re-entry)
    R4 — minimum hold of 10 trading days, with a −5% escape
  For each rule: how much whipsaw cost avoided (gross savings on the regime-
  driven whipsaws the rule would have skipped), minus the lag cost it would
  add (later exit in genuine downturns), net effect on post-tax CAGR / Sharpe
  / MaxDD vs base + V2. Pre-specified — not tuned to specific years.

Slow-stress and panic-short overrides are NOT modified by any rule. Only
regime-filter-driven flat episodes are subject to hysteresis. Verified by
checking these other signals' contributions don't change.
"""

import os, sys
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from strategy import (
    make_combiner, MacroStrategy, RegimeFilter, SlowStressSignal,
    PanicShortSignal, load_nse_index_csv, build_rbi_repo_rate_series,
    metrics, apply_annual_tax,
)

WARMUP, IS_START, IS_END = "2006-01-01", "2008-04-01", "2025-12-31"
LONG_BPS_MOM30, SHORT_BPS, GOLD_BPS, HAIRCUT_BPS = 6, 3, 5, 100
LONG_BPS_NIFTY = 3
TAX = 0.15
WHIPSAW_WINDOW = 20
OUTPUT_PATH = os.path.normpath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..",
    "diagnose_whipsaw_cost_results.txt"))
RECOVERY_LEAK_PP = -2.13  # from diagnose_recovery_regime.py (Part A)

# ─── Data ────────────────────────────────────────────────────────────────────
PARENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(PARENT, "_yf_cache.pkl")
raw = pd.read_pickle(CACHE)
for col in ["CL=F", "^NSEI", "INR=X", "^INDIAVIX", "^TNX"]:
    raw[col] = raw[col].ffill()
fv = raw["GOLDBEES.NS"].first_valid_index()
raw.loc[raw.index >= fv, "GOLDBEES.NS"] = raw.loc[raw.index >= fv,
                                                  "GOLDBEES.NS"].ffill()
mom30_p = load_nse_index_csv(os.path.join(PARENT, "data",
                                          "momentum30_history.csv"),
                             "NIFTYMOM30")
raw["NIFTYMOM30"] = mom30_p.reindex(raw.index).ffill()

# ─── Run base v1.5 + NIFTY baseline for V2 splice ───────────────────────────
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

# Asset returns
ret_mom  = raw["NIFTYMOM30"].pct_change().reindex(idx).fillna(0.0)
ret_nif  = raw["^NSEI"].pct_change().reindex(idx).fillna(0.0)
ret_gold = raw["GOLDBEES.NS"].pct_change().reindex(idx).fillna(0.0).clip(-0.5, 0.5)
repo = build_rbi_repo_rate_series(idx)
ret_cash = ((repo - HAIRCUT_BPS / 10000).clip(lower=0) / 252).reindex(idx).fillna(0.0)

# ─── Regime + slow-stress + panic-short masks ────────────────────────────────
rf = RegimeFilter(window=100)
bull_full = rf.bull_mask(raw)
bull = bull_full.reindex(idx).fillna(False)

# Re-evaluate slow-stress and panic-short signals on raw data
sss = SlowStressSignal(inr_window=20, inr_threshold=0.01,
                       vix_z_window=90, vix_z_threshold=1.5, vix_mom_window=5)
slow_stress_fires_full = (sss.compute(raw) < 0)
slow_stress = slow_stress_fires_full.reindex(idx).fillna(False)

psg = PanicShortSignal(vix_level=25, vix_spike=0.50, window=10, dma=100)
panic_short_fires_full = (psg.compute(raw) < 0)
panic_short = panic_short_fires_full.reindex(idx).fillna(False)

# NIFTY distance from 100-DMA
nifty_close = raw["^NSEI"].reindex(idx).ffill()
nifty_100dma = nifty_close.rolling(100, min_periods=1).mean()
nifty_dist_dma = nifty_close / nifty_100dma - 1.0  # signed, >0 = above DMA

# ─── V2 windows (for the base + V2 reference) ────────────────────────────────
prev_bull = bull.shift(1, fill_value=False)
flip_mask = bull & (~prev_bull)
if flip_mask.iloc[0]:
    pre = bull_full
    p = pre.index.get_loc(idx[0])
    if p > 0 and bool(pre.iloc[p - 1]):
        flip_mask.iloc[0] = False
flips = idx[flip_mask.values]

def preceding_bear_dd(flip_date):
    p = bull_full.index.get_loc(flip_date)
    if p == 0: return None
    end = p - 1; start = end
    while start > 0 and not bool(bull_full.iloc[start - 1]): start -= 1
    w = raw["^NSEI"].iloc[start:end + 1]
    if len(w) == 0: return 0.0
    return abs(float((w / w.cummax() - 1.0).min()))

v2_flips = [d for d in flips if (dd := preceding_bear_dd(d)) is not None and dd >= 0.15]
V2_DAYS = 60
v2_active = pd.Series(False, index=idx)
for f in v2_flips:
    i0 = idx.get_loc(f)
    v2_active.iloc[i0:min(i0 + V2_DAYS, len(idx))] = True

# base + V2 daily pretax
long_mask = (nifty_pos == 1.0)
base_v2_pretax = strat_pretax.where(~(long_mask & v2_active), nif_pretax)
base_v2_posttax = apply_annual_tax(base_v2_pretax.fillna(0.0), tax_rate=TAX)

# ─── Identify long→flat episodes and classify ───────────────────────────────
exits = long_mask.shift(1, fill_value=False) & (~long_mask)   # day that goes flat (or short/gold)
n = len(idx)

episodes = []  # each: dict with exit_dt, re_dt (or None), len, classification
i = 0
while i < n:
    if exits.iloc[i]:
        exit_dt = idx[i]
        # Find next long day
        j = i
        while j < n and not long_mask.iloc[j]:
            j += 1
        if j == n:
            re_dt = None; ep_len = n - i
        else:
            re_dt = idx[j]; ep_len = j - i
        ep_idx = idx[i:j]
        # Classify the exit cause
        # Check signals on exit day i
        ss_on_exit = bool(slow_stress.iloc[i])
        ps_on_exit = bool(panic_short.iloc[i])
        regime_on_exit = bool(~bull.iloc[i])  # bear today
        # Primary cause: if any of slow-stress/panic-short firing, attribute to them;
        # else attribute to regime (the only other source of flat in strategy.py)
        if ps_on_exit:
            cause = "panic-short"
        elif ss_on_exit:
            cause = "slow-stress"
        elif regime_on_exit:
            cause = "regime"
        else:
            cause = "unknown"
        # Min NIFTY dist from DMA during episode (most negative)
        if len(ep_idx):
            min_dist = float(nifty_dist_dma.loc[ep_idx].min())
        else:
            min_dist = np.nan
        # Mom30 cum return during the flat days (counterfactual for staying long)
        cf_mom_ret = float((1 + ret_mom.loc[ep_idx]).prod() - 1) if len(ep_idx) else 0.0
        # Actual cum strategy return during the flat days (whatever fills happened)
        actual_ret = float((1 + strat_pretax.loc[ep_idx]).prod() - 1) if len(ep_idx) else 0.0
        # Number of 100-DMA crossings inside episode (NIFTY)
        if len(ep_idx) > 1:
            sign = (nifty_dist_dma.loc[ep_idx] > 0).astype(int)
            crossings = int((sign != sign.shift(1)).iloc[1:].sum())
        else:
            crossings = 0
        episodes.append({
            "exit_dt": exit_dt, "re_dt": re_dt, "len": ep_len,
            "cause": cause, "ss_on_exit": ss_on_exit,
            "ps_on_exit": ps_on_exit, "regime_on_exit": regime_on_exit,
            "min_dist": min_dist, "crossings": crossings,
            "cf_mom_ret": cf_mom_ret, "actual_ret": actual_ret,
        })
        i = j if j > i else i + 1
    else:
        i += 1

# Whipsaw: re-entered within WHIPSAW_WINDOW days
whipsaws = [e for e in episodes if e["re_dt"] is not None and e["len"] <= WHIPSAW_WINDOW]
genuine_bears = [e for e in episodes if e["re_dt"] is None or e["len"] > WHIPSAW_WINDOW]

# ─── Part A: whipsaw cost computation ───────────────────────────────────────
# Per-whipsaw cost: cost paid on round-trip (exit + re-enter, each 6 bps for
# Mom30 long-side) + (counterfactual − actual) price-action diff.
# Positive = strategy lost money to the whipsaw. Negative = strategy saved.
ROUNDTRIP_BPS = 2 * LONG_BPS_MOM30  # 12 bps
for w in whipsaws:
    # Sign: counterfactual (staying long) earns cf_mom_ret; actual fill earns actual_ret.
    # Whipsaw cost = (cf − actual) − transaction costs paid (already in actual).
    # The 12 bps in transaction costs is already inside actual_ret implicitly
    # (since strategy.py charges on exit and re-entry). We add ROUNDTRIP_BPS
    # again here to make the cost EXPLICIT: cost paid + opportunity cost.
    # Cleanest: cost = cf_mom_ret_GROSS − actual_ret_INCLUDING_TRANSACTION_COSTS.
    # If positive, strategy lost. We do not double-count: actual_ret already
    # subtracts the 12 bps. So cost = cf_mom_ret − actual_ret.
    w["whipsaw_cost"] = w["cf_mom_ret"] - w["actual_ret"]
    # Decompose: price-action component vs cost component
    w["price_action_comp"] = w["cf_mom_ret"] - (w["actual_ret"] + ROUNDTRIP_BPS / 10000)
    w["cost_comp"] = ROUNDTRIP_BPS / 10000

# Aggregate
total_whip_cost = sum(w["whipsaw_cost"] for w in whipsaws)
total_whip_cost_regime = sum(w["whipsaw_cost"] for w in whipsaws if w["cause"] == "regime")
total_whip_cost_ss     = sum(w["whipsaw_cost"] for w in whipsaws if w["cause"] == "slow-stress")
total_whip_cost_ps     = sum(w["whipsaw_cost"] for w in whipsaws if w["cause"] == "panic-short")

# Per-year aggregation
year_whip = {}
for w in whipsaws:
    y = w["exit_dt"].year
    year_whip.setdefault(y, {"n": 0, "cost": 0.0, "by_cause": {}})
    year_whip[y]["n"] += 1
    year_whip[y]["cost"] += w["whipsaw_cost"]
    year_whip[y]["by_cause"].setdefault(w["cause"], 0)
    year_whip[y]["by_cause"][w["cause"]] += 1

# Frequency stats
n_years = (idx[-1] - idx[0]).days / 365.25
eps_per_year = len(whipsaws) / n_years
mean_crossings_per_ep = float(np.mean([w["crossings"] for w in whipsaws])) if whipsaws else 0
median_len = float(np.median([w["len"] for w in whipsaws])) if whipsaws else 0

# ─── Part B: hysteresis rules — simulate net effect ─────────────────────────
# For each rule, classify each episode as "would be avoided" or "would still happen"
# (with potential lag in the latter case for genuine bears).
#
# We simulate the rule's net effect on base+V2 daily pretax by:
#   1. For each regime-driven WHIPSAW the rule avoids: add cf_mom_ret to the
#      flat-day window's pretax (i.e., we would have earned Mom30 instead of
#      cash/gold). This is the savings.
#   2. For each regime-driven GENUINE BEAR exit the rule delays: on the lag
#      days (between original exit and rule-triggered exit), subtract the cash
#      yield contribution and add the Mom30 contribution. Net: lag cost is the
#      Mom30 drawdown over those lag days (since Mom30 typically falls during
#      the lag in a real bear).
#
# Pre-specified rules:
RULES = {
    "R1 band ±2%":             {"kind": "band", "x": 0.02},
    "R2 band ±3%":             {"kind": "band", "x": 0.03},
    "R3 min-hold 5d + -5% escape": {"kind": "minhold", "n": 5,  "escape": -0.05},
    "R4 min-hold 10d + -5% escape": {"kind": "minhold", "n": 10, "escape": -0.05},
}

# For each regime-driven episode, decide rule behavior
def rule_effects(rule):
    avoided = []  # list of regime-driven whipsaws the rule would have avoided
    lag_days_total = 0
    lag_cost_total = 0.0  # cumulative Mom30 return during lag in genuine bears
    lag_episodes = []
    # We need the re-entry-side hysteresis for band rules: re-engage requires +X% above DMA.
    # For min-hold: this is an exit-side rule only.
    for e in episodes:
        if e["cause"] != "regime":
            continue
        ep_idx = idx[idx.get_loc(e["exit_dt"]) : idx.get_loc(e["exit_dt"]) + e["len"]]
        if rule["kind"] == "band":
            x = rule["x"]
            # Exit-side: rule says exit only when dist < -x. Strategy already exited;
            # rule would have AVOIDED the exit iff NIFTY never went below -x within the episode.
            if e["min_dist"] >= -x:
                # Avoided whipsaw (if it was a whipsaw) or never exited at all
                if e["re_dt"] is not None and e["len"] <= WHIPSAW_WINDOW:
                    avoided.append(e)
                continue
            # If genuine bear: rule still exits but later. Find first day in episode
            # where dist < -x. Lag = days from exit_dt to that day.
            dist_in_ep = nifty_dist_dma.loc[ep_idx]
            below = dist_in_ep[dist_in_ep < -x]
            if len(below) == 0:
                # Shouldn't happen given min_dist check, defensive
                continue
            rule_exit_dt = below.index[0]
            lag = idx.get_loc(rule_exit_dt) - idx.get_loc(e["exit_dt"])
            if lag <= 0:
                continue
            lag_idx = idx[idx.get_loc(e["exit_dt"]) : idx.get_loc(rule_exit_dt)]
            # Mom30 return during lag (we'd be holding Mom30 instead of strategy's fill)
            mom_during_lag = float((1 + ret_mom.loc[lag_idx]).prod() - 1)
            actual_during_lag = float((1 + strat_pretax.loc[lag_idx]).prod() - 1)
            lag_cost_total += (mom_during_lag - actual_during_lag)
            lag_days_total += lag
            lag_episodes.append(e)
        elif rule["kind"] == "minhold":
            N = rule["n"]; escape = rule["escape"]
            # Min-hold: after a re-entry to long, can't exit for N days unless NIFTY drops
            # by `escape` from entry price. The episode in question is an EXIT; the rule
            # cares whether that exit happened within N days of the most recent re-entry.
            # If so AND NIFTY didn't drop ≥|escape| from entry, rule prevents exit.
            #
            # Find most recent re-entry before this exit.
            ex_i = idx.get_loc(e["exit_dt"])
            # Walk backward to last day that was a long re-entry (i.e., long today, flat yesterday)
            prev_re_i = None
            for k in range(ex_i - 1, -1, -1):
                if k > 0 and long_mask.iloc[k] and not long_mask.iloc[k - 1]:
                    prev_re_i = k
                    break
                if k == 0 and long_mask.iloc[0]:
                    prev_re_i = 0
                    break
            if prev_re_i is None:
                continue
            held_days = ex_i - prev_re_i  # days held (exit_dt − last_re_entry)
            if held_days >= N:
                continue  # rule doesn't apply, exit allowed
            # NIFTY drop since re-entry
            entry_px = float(nifty_close.iloc[prev_re_i])
            exit_px = float(nifty_close.iloc[ex_i - 1])  # close the day before exit
            drop = exit_px / entry_px - 1.0
            if drop <= escape:
                continue  # large enough drop, rule allows exit
            # Otherwise, rule prevents the exit. The strategy stays long for the rest
            # of (N − held_days) days OR until the episode would naturally end.
            # Effectively: rule AVOIDS this exit if it's a whipsaw.
            if e["re_dt"] is not None and e["len"] <= WHIPSAW_WINDOW:
                avoided.append(e)
            else:
                # Genuine bear that started inside min-hold window. Rule delays exit
                # by (N − held_days) days.
                lag = N - held_days
                lag_end_i = min(ex_i + lag, n)
                lag_idx = idx[ex_i:lag_end_i]
                mom_during_lag = float((1 + ret_mom.loc[lag_idx]).prod() - 1)
                actual_during_lag = float((1 + strat_pretax.loc[lag_idx]).prod() - 1)
                lag_cost_total += (mom_during_lag - actual_during_lag)
                lag_days_total += len(lag_idx)
                lag_episodes.append(e)
    return avoided, lag_days_total, lag_cost_total, lag_episodes

def simulate_rule(rule):
    """Return modified pretax series, gross savings, lag cost, net effect."""
    avoided, lag_days, lag_cost, lag_eps = rule_effects(rule)
    # Build a modified pretax series:
    modified = base_v2_pretax.copy()
    gross_savings = 0.0
    for e in avoided:
        ep_idx = idx[idx.get_loc(e["exit_dt"]) : idx.get_loc(e["exit_dt"]) + e["len"]]
        if not len(ep_idx):
            continue
        # Replace actual fill with Mom30 returns ONLY on days where neither
        # slow-stress nor panic-short is firing (those overrides still apply).
        replaced_any = False
        for d in ep_idx:
            if bool(slow_stress.loc[d]) or bool(panic_short.loc[d]):
                continue
            modified.loc[d] = ret_mom.loc[d]
            replaced_any = True
        if replaced_any:
            if e["exit_dt"] in modified.index:
                modified.loc[e["exit_dt"]] += ROUNDTRIP_BPS / 10000
            gross_savings += e["whipsaw_cost"] + ROUNDTRIP_BPS / 10000
    # Apply lag cost: subtract Mom30 underperf during lag windows
    for e in lag_eps:
        if rule["kind"] == "band":
            x = rule["x"]
            ep_idx = idx[idx.get_loc(e["exit_dt"]) : idx.get_loc(e["exit_dt"]) + e["len"]]
            dist_in_ep = nifty_dist_dma.loc[ep_idx]
            below = dist_in_ep[dist_in_ep < -x]
            if len(below) == 0: continue
            rule_exit_dt = below.index[0]
            lag_idx = idx[idx.get_loc(e["exit_dt"]) : idx.get_loc(rule_exit_dt)]
        else:
            ex_i = idx.get_loc(e["exit_dt"])
            prev_re_i = None
            for k in range(ex_i - 1, -1, -1):
                if k > 0 and long_mask.iloc[k] and not long_mask.iloc[k - 1]:
                    prev_re_i = k; break
            if prev_re_i is None: continue
            held_days = ex_i - prev_re_i
            N = rule["n"]
            lag = N - held_days
            lag_end_i = min(ex_i + lag, n)
            lag_idx = idx[ex_i:lag_end_i]
        # Replace actual fill with Mom30 returns on lag days where neither
        # slow-stress nor panic-short is firing.
        for d in lag_idx:
            if bool(slow_stress.loc[d]) or bool(panic_short.loc[d]):
                continue
            modified.loc[d] = ret_mom.loc[d]
    modified_posttax = apply_annual_tax(modified.fillna(0.0), tax_rate=TAX)
    return modified, modified_posttax, gross_savings, lag_cost, len(avoided), lag_days

# ─── Sanity: panic-short/slow-stress contribution preserved ──────────────────
# The hysteresis only modifies REGIME-driven flat episodes. To verify, we check
# that pretax on slow-stress firing days and panic-short firing days is
# unchanged from base+V2.
ss_days_mask = slow_stress
ps_days_mask = panic_short
base_ss_sum = float(base_v2_pretax[ss_days_mask].sum())
base_ps_sum = float(base_v2_pretax[ps_days_mask].sum())

# ─── Output ──────────────────────────────────────────────────────────────────
lines = []
def out(s=""): lines.append(s); print(s)

out("=" * 130)
out("  WHIPSAW COST DIAGNOSTIC — long→flat→long round-trips ≤ 20 days, "
    "and pre-specified hysteresis rules")
out("=" * 130)
out(f"  IS window: {IS_START} → {IS_END}  ({len(idx)} trading days)")
out(f"  Total exit→flat episodes: {len(episodes)}")
out(f"  Whipsaw episodes (re-entry ≤ {WHIPSAW_WINDOW} days): {len(whipsaws)}")
out(f"  Genuine bear episodes (no re-entry within {WHIPSAW_WINDOW} days): {len(genuine_bears)}")
out(f"  Years covered: ~{n_years:.1f}.  Whipsaw frequency: "
    f"{eps_per_year:.1f} episodes/year.  Mean 100-DMA crossings per whipsaw: "
    f"{mean_crossings_per_ep:.2f}.  Median episode length: {median_len:.0f} days.")
out()

out("=" * 130)
out("  PART A — WHIPSAW COST BY CAUSE (positive = strategy lost vs counterfactual stay-long)")
out("=" * 130)
def fmt_cause(c):
    eps = [w for w in whipsaws if w["cause"] == c]
    if not eps:
        return f"  {c:<14} 0 episodes"
    total = sum(e["whipsaw_cost"] for e in eps)
    return f"  {c:<14} {len(eps):>4d} episodes,  total cost: {total*100:+7.2f}pp"
out(fmt_cause("regime"))
out(fmt_cause("slow-stress"))
out(fmt_cause("panic-short"))
out(fmt_cause("unknown"))
out(f"  All causes      {len(whipsaws):>4d} episodes,  total cost: {total_whip_cost*100:+7.2f}pp")
out()
out(f"  Recovery-window leak vs Dyn A in loss years (from prior diagnostic): "
    f"{RECOVERY_LEAK_PP:+.2f}pp")
out(f"  Regime-driven whipsaw cost: {total_whip_cost_regime*100:+.2f}pp")
denom = abs(RECOVERY_LEAK_PP)
share = (abs(total_whip_cost_regime * 100) / denom) if denom > 0 else 0
out(f"  Fraction of leak explained by regime-driven whipsaws: "
    f"{share*100:.0f}%  (uses regime-driven cost / |leak|)")
out()

out("=" * 130)
out("  PART A.2 — WHIPSAW COST BY YEAR (all causes)")
out("=" * 130)
out(f"  {'Year':<6} {'# eps':>6} {'Total cost':>11} {'Regime':>10} {'SlowStress':>11} {'PanicShort':>11}")
out("  " + "-"*6 + " " + "-"*6 + " " + "-"*11 + " " + "-"*10 + " " + "-"*11 + " " + "-"*11)
for y in sorted(year_whip):
    b = year_whip[y]
    by_cause = {c: 0.0 for c in ("regime", "slow-stress", "panic-short")}
    for w in whipsaws:
        if w["exit_dt"].year == y:
            by_cause[w["cause"]] = by_cause.get(w["cause"], 0) + w["whipsaw_cost"]
    out(f"  {y:<6} {b['n']:>6d} {b['cost']*100:+10.2f}pp "
        f"{by_cause['regime']*100:+9.2f}pp "
        f"{by_cause['slow-stress']*100:+10.2f}pp "
        f"{by_cause['panic-short']*100:+10.2f}pp")
out()

# Show a sample of regime-driven whipsaws
regime_whips = sorted([w for w in whipsaws if w["cause"] == "regime"],
                     key=lambda w: -abs(w["whipsaw_cost"]))
out("=" * 130)
out("  PART A.3 — Top 15 regime-driven whipsaws by absolute cost")
out("=" * 130)
out(f"  {'Exit':<12} {'Re-entry':<12} {'Len':>4} {'DMAxings':>9} "
    f"{'min dist':>10} {'CF Mom30':>10} {'Actual fill':>12} {'Cost':>9}")
out("  " + "-"*12 + " " + "-"*12 + " " + "-"*4 + " " + "-"*9 + " " + "-"*10 + " " +
    "-"*10 + " " + "-"*12 + " " + "-"*9)
for w in regime_whips[:15]:
    re_dt_str = w["re_dt"].strftime("%Y-%m-%d") if w["re_dt"] else "—"
    out(f"  {w['exit_dt'].strftime('%Y-%m-%d'):<12} {re_dt_str:<12} {w['len']:>4d} "
        f"{w['crossings']:>9d} {w['min_dist']*100:>+9.2f}% "
        f"{w['cf_mom_ret']*100:>+9.2f}% {w['actual_ret']*100:>+11.2f}% "
        f"{w['whipsaw_cost']*100:>+8.2f}%")
out()

# ─── Part B: simulate hysteresis rules ──────────────────────────────────────
out("=" * 130)
out("  PART B — HYSTERESIS RULES (pre-specified, applied to regime filter ONLY)")
out("=" * 130)
base_v2_m = metrics(base_v2_posttax)
out(f"  Reference base + V2 (post-tax):  CAGR {base_v2_m['cagr']*100:+.2f}%   "
    f"Sharpe {base_v2_m['sharpe']:.3f}   MaxDD {base_v2_m['max_dd']*100:+.2f}%")
out()
out(f"  {'Rule':<32} {'#avoid':>7} {'gross save':>11} {'lag days':>10} "
    f"{'lag cost':>10} {'net Δ':>9} {'ΔCAGR':>9} {'ΔSharpe':>9} {'ΔMaxDD':>9}")
out("  " + "-"*32 + " " + "-"*7 + " " + "-"*11 + " " + "-"*10 + " " + "-"*10 + " " +
    "-"*9 + " " + "-"*9 + " " + "-"*9 + " " + "-"*9)

# Sanity check accumulators
ss_check_ok = True; ps_check_ok = True

for name, rule in RULES.items():
    modified, modified_posttax, gross, lag_cost, n_avoid, lag_days = simulate_rule(rule)
    rule_m = metrics(modified_posttax)
    d_cagr = rule_m["cagr"] - base_v2_m["cagr"]
    d_sh   = rule_m["sharpe"] - base_v2_m["sharpe"]
    d_dd   = rule_m["max_dd"] - base_v2_m["max_dd"]
    net = gross - lag_cost
    # Sanity: slow-stress and panic-short day sums must equal base+V2
    ss_sum = float(modified[ss_days_mask].sum())
    ps_sum = float(modified[ps_days_mask].sum())
    ss_ok = abs(ss_sum - base_ss_sum) < 1e-10
    ps_ok = abs(ps_sum - base_ps_sum) < 1e-10
    if not ss_ok: ss_check_ok = False
    if not ps_ok: ps_check_ok = False
    out(f"  {name:<32} {n_avoid:>7d} {gross*100:+10.2f}pp {lag_days:>10d} "
        f"{lag_cost*100:+9.2f}pp {net*100:+8.2f}pp "
        f"{d_cagr*100:+8.2f}pp {d_sh:+9.3f} {d_dd*100:+8.2f}pp")
out()

# ─── Sanity: panic-short/slow-stress engine unchanged ────────────────────────
out("=" * 130)
out("  SANITY — panic-short/slow-stress engine unchanged by hysteresis rules")
out("=" * 130)
out(f"  Sum of pretax on slow-stress firing days (base+V2): {base_ss_sum*100:+.4f}%")
out(f"  Sum of pretax on panic-short firing days (base+V2): {base_ps_sum*100:+.4f}%")
out(f"  Slow-stress days untouched across all rules: {'✓' if ss_check_ok else '❌ DIFFERED'}")
out(f"  Panic-short days untouched across all rules: {'✓' if ps_check_ok else '❌ DIFFERED'}")
out()

# ─── Plain-English read ──────────────────────────────────────────────────────
out("=" * 130)
out("  PLAIN-ENGLISH READ")
out("=" * 130)
out()
out(f"(1) Total cost of regime-driven whipsaws over {n_years:.1f} years: "
    f"{total_whip_cost_regime*100:+.2f}pp (cumulative pre-tax).")
out(f"    The recovery-window leak vs Dyn A in the loss years was {RECOVERY_LEAK_PP:+.2f}pp.")
if abs(total_whip_cost_regime * 100) >= 0.5 * abs(RECOVERY_LEAK_PP):
    out(f"    ⇒ Regime-driven whipsaws explain a meaningful share of the recovery leak.")
else:
    out(f"    ⇒ Regime-driven whipsaws are only a small share of the recovery leak; "
        f"most of the leak comes from somewhere else.")
out()
out(f"    Whipsaw frequency: {eps_per_year:.1f} episodes/year, mean "
    f"{mean_crossings_per_ep:.1f} 100-DMA crossings per episode, "
    f"median episode length {median_len:.0f} days.")
out()
out("(2) Hysteresis rules net effect (vs base + V2):")
rule_results = {}
for name, rule in RULES.items():
    modified, modified_posttax, gross, lag_cost, n_avoid, lag_days = simulate_rule(rule)
    rule_m = metrics(modified_posttax)
    rule_results[name] = (rule_m, gross, lag_cost, n_avoid, lag_days)
    sign = "POS" if (rule_m["cagr"] > base_v2_m["cagr"] and
                     rule_m["sharpe"] > base_v2_m["sharpe"]) else "NEG"
    out(f"    {name:<32}  ΔCAGR {(rule_m['cagr']-base_v2_m['cagr'])*100:+5.2f}pp  "
        f"ΔSharpe {rule_m['sharpe']-base_v2_m['sharpe']:+.3f}  "
        f"ΔMaxDD {(rule_m['max_dd']-base_v2_m['max_dd'])*100:+5.2f}pp  → {sign}")
out()
n_net_pos = sum(1 for n, r in rule_results.items()
                if r[0]["cagr"] > base_v2_m["cagr"] and r[0]["sharpe"] > base_v2_m["sharpe"])
out(f"    Rules netting positive on BOTH CAGR and Sharpe: {n_net_pos} of {len(RULES)}.")
out()
out("(3) Panic-short / slow-stress engine: untouched (verified by holding total")
out("    pretax on their firing days constant across all rules).")
out()

with open(OUTPUT_PATH, "w") as f:
    f.write("\n".join(lines))
print(f"\nSaved to {OUTPUT_PATH}", file=sys.stderr)
