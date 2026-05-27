"""
diagnose_factor_years.py — DIAGNOSTIC.

Investigates WHY C1 (production v1.5 + V2 overlay) underperforms NIFTY B&H
in 2018, 2022, 2025 — the structural-rotation loss years.

CONFIRMED FROM CODE READ:
  - Regime filter:  RegimeFilter(window=100, target="^NSEI") — NIFTY 50's 100-DMA
  - Panic-short:    PanicShortSignal uses NIFTY 50's 100-DMA (line 72 of strategy.py)
  - G10 gold gate:  gold 10d return + INR 10d + US 10Y 20d (NO DMA)
  - Slow-stress:    INR 20d + VIX 90d z-score + VIX 5d (NO DMA)
  - NO production gate uses Mom30's own 100-DMA.

PARTS:
  1. C1 production-state breakdown per year (LONG / LONG_V2 / SHORT / GOLD / FLAT)
  2. Month-by-month decomposition of shortfall vs NIFTY B&H for each loss year
     (a) Mom30 drag        — held Mom30 while it lagged NIFTY
     (b) Defensive cost    — flat/short/gold while NIFTY rose
     (c) Override costs    — transaction costs
  3. Absolute-vs-relative blind spot test:
     Count days where Mom30 > own 100-DMA (absolute uptrend) AND Mom30 60d
     trailing return < NIFTY 60d (relative underperformance)
  4. Rebalance hypothesis test:
     For ~100 trading days after each end-of-June / end-of-December
     reconstitution, is the 100-DMA regime signal less accurate? And: would
     a 126-day window aligned to the 6-month cycle change long/flat calls?

Saves per-year per-day logs to results/diagnose_factor_years_<year>.csv.
"""

import os, sys
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                 "experiments"))
import strategy_lab as L

LOSS_YEARS = [2018, 2022, 2025]
START, END = "2008-04-01", "2025-12-31"
REBAL_WINDOW = 100
OUTPUT_PATH = os.path.normpath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..",
    "diagnose_factor_years_results.txt"))
RESULTS_DIR = os.path.normpath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "results"))
os.makedirs(RESULTS_DIR, exist_ok=True)

# ─── Load data + run C1 ──────────────────────────────────────────────────────
raw = L._load_data()

# Run C0 for target_vol (required by run_config signature)
df0, _ = L.run_config("C0", L.CONFIG_CATALOG["C0"], raw, START, END, vol_target_annual=None)
target_vol = float(df0["strategy_return_pretax"].std() * np.sqrt(252))

# Run C1
df1, diag1 = L.run_config("C1", L.CONFIG_CATALOG["C1"], raw,
                          START, END, vol_target_annual=target_vol)
idx = df1.index
nifty_pos = df1["nifty_position"]
gold_pos  = df1["gold_position"]
v2_active = diag1["v2_active"].reindex(idx).fillna(False)
weights   = diag1["weights"].reindex(idx).fillna(0.0)
strat_pretax = df1["strategy_return_pretax"]

# Asset returns aligned to idx
ret_mom  = raw["NIFTYMOM30"].pct_change().reindex(idx).fillna(0.0)
ret_nif  = raw["^NSEI"].pct_change().reindex(idx).fillna(0.0)
ret_gold = raw["GOLDBEES.NS"].pct_change().reindex(idx).fillna(0.0).clip(-0.5, 0.5)
repo = L.build_rbi_repo_rate_series(idx)
ret_cash = ((repo - 100/10000).clip(lower=0) / 252).reindex(idx).fillna(0.0)

# ─── Classify each day into one of 5 C1 states ───────────────────────────────
def classify_state(i):
    long_today = (nifty_pos.iloc[i] == 1.0)
    if not long_today:
        if nifty_pos.iloc[i] == -1.0:
            return "SHORT"
        if gold_pos.iloc[i] == 1.0:
            return "GOLD"
        return "FLAT"
    return "LONG_V2" if bool(v2_active.iloc[i]) else "LONG"

state = pd.Series([classify_state(i) for i in range(len(idx))], index=idx, name="C1_state")

# Cost per day (approximated as |Δw| × per-asset bps; matches MacroStrategyLab)
COST_BPS = {"mom": 6, "nif": 3, "gold": 5, "cash": 0}
cost_mom = weights["mom"].diff().abs().fillna(0)  * COST_BPS["mom"] / 10000
cost_nif = weights["nif"].diff().abs().fillna(0)  * COST_BPS["nif"] / 10000
cost_gold = weights["gold"].diff().abs().fillna(0) * COST_BPS["gold"] / 10000
total_cost = cost_mom + cost_nif + cost_gold

# ─── Output helper ───────────────────────────────────────────────────────────
lines = []
def out(s=""): lines.append(s); print(s)

out("=" * 130)
out("  DIAGNOSE FACTOR YEARS — 2018 / 2022 / 2025 (C1 = production v1.5 + V2)")
out("=" * 130)
out()
out("CODE READ — which DMA drives what?")
out("  Regime filter (long/flat):  NIFTY 50 100-DMA  (strategy.py:679, class default target='^NSEI')")
out("  Panic-short (short trigger): NIFTY 50 100-DMA  (strategy.py:72)")
out("  G10 gold gate:               gold 10d + INR 10d + US 10Y 20d (NO DMA)")
out("  Slow-stress:                 INR 20d + VIX 90d z + VIX 5d (NO DMA)")
out("  Mom30's own 100-DMA:         NOT used in any production gate.")
out()

# ─── Part 1: C1 production state breakdown for each loss year ───────────────
out("=" * 130)
out("  PART 1 — C1 state breakdown for each loss year")
out("=" * 130)
out(f"  {'Year':<6} {'LONG':>8} {'LONG_V2':>9} {'SHORT':>7} {'GOLD':>6} "
    f"{'FLAT':>6} {'Total':>7}")
out("  " + "-"*6 + " " + "-"*8 + " " + "-"*9 + " " + "-"*7 + " " + "-"*6 + " "
    + "-"*6 + " " + "-"*7)
for y in LOSS_YEARS:
    yrs = state[state.index.year == y]
    counts = yrs.value_counts()
    out(f"  {y:<6} {counts.get('LONG', 0):>8d} {counts.get('LONG_V2', 0):>9d} "
        f"{counts.get('SHORT', 0):>7d} {counts.get('GOLD', 0):>6d} "
        f"{counts.get('FLAT', 0):>6d} {len(yrs):>7d}")
out()

# ─── Part 2: monthly breakdown + shortfall decomposition per year ───────────
def compute_year_decomp(year):
    """
    Decompose arithmetic shortfall vs NIFTY B&H using ACTUAL HELD weights.
    pnl_total[t] = sum_assets (w_asset.shift(1)[t] × ret_asset[t]) - cost[t]
    Shortfall_t = ret_nif[t] - pnl_total[t]
    Per-asset attribution (using yesterday's held weight × today's return):
      (a) Mom30 drag    = sum_t (w_mom.shift × (ret_nif - ret_mom))
      (b) Defensive     = sum_t (w_gold.shift × (ret_nif - ret_gold)
                                + w_cash.shift × (ret_nif - ret_cash))
                          + sum_t on SHORT-held days of 2×ret_nif
      (c) Override cost = sum over ALL days of cost
    V2 contribution (held NIFTY) = sum_t (w_nif.shift(=+1) × 0) = 0
    Note: state.shift(1) classifies by what was HELD OVERNIGHT, not today's
    target. This matches how strat_pretax actually accumulates.
    """
    yr_idx = idx[idx.year == year]
    nifty_ret = ret_nif.loc[yr_idx]
    mom_ret   = ret_mom.loc[yr_idx]
    gold_ret  = ret_gold.loc[yr_idx]
    cash_ret  = ret_cash.loc[yr_idx]
    strat_ret = strat_pretax.loc[yr_idx]
    cost_yr   = total_cost.loc[yr_idx]
    w_yr      = weights.loc[yr_idx]
    # Yesterday's weight × today's return (what actually earned today)
    wm = w_yr["mom"].shift(1, fill_value=0.0)
    wn = w_yr["nif"].shift(1, fill_value=0.0)
    wg = w_yr["gold"].shift(1, fill_value=0.0)
    wc = w_yr["cash"].shift(1, fill_value=0.0)
    # Per-asset drag = held weight × (NIFTY return − asset return)
    mom_drag  = float((wm * (nifty_ret - mom_ret)).sum())
    gold_drag = float((wg * (nifty_ret - gold_ret)).sum())
    cash_drag = float((wc * (nifty_ret - cash_ret)).sum())
    # NIFTY held: when wn = +1 (V2 long) → no diff. When wn = -1 (short) →
    # diff = (1 - (-1)) × ret_nif = 2×ret_nif (we BET against NIFTY while
    # benchmark held it long).
    nif_diff_per_day = (1 - wn) * nifty_ret  # this is the "we should have held NIFTY" residual
    # But we already account for mom/gold/cash drag above (where we held those instead of NIFTY).
    # On SHORT days only, wn=-1 and the residual = 2×ret_nif. On all other days wn=0 or wn=+1.
    # Let's compute as nif_residual directly:
    # On days where wm+wn+wg+wc = 1 (fully invested), (1 - wn - wm - wg - wc) × ret_nif = 0 from this term
    # On SHORT days, sum of weights = -1, so residual ret_nif contribution = (1 - (-1)) × ret_nif = 2×ret_nif
    # Already captured via 'nif_diff_per_day' but we should only count where wn != 1 (not V2) and we're not double-counting.
    # Actually simpler: NIF-residual = (1 - wm - wn - wg - wc) × ret_nif on days where it's nonzero.
    nif_residual = float(((1 - wm - wn - wg - wc) * nifty_ret).sum())
    defensive = gold_drag + cash_drag + nif_residual  # defensive sleeve (gold/cash/short)
    override_cost = float(cost_yr.sum())
    decomp_sum = mom_drag + defensive + override_cost

    cum_nifty = float((1 + nifty_ret).prod() - 1)
    cum_strat = float((1 + strat_ret).prod() - 1)
    actual_short = cum_nifty - cum_strat
    arith_short = float((nifty_ret - strat_ret).sum())
    return {
        "year": year,
        "cum_nifty": cum_nifty,
        "cum_strat": cum_strat,
        "actual_short": actual_short,
        "arith_short": arith_short,
        "mom_drag": mom_drag,
        "defensive": defensive,
        "gold_drag": gold_drag,
        "cash_drag": cash_drag,
        "nif_residual": nif_residual,
        "override_cost": override_cost,
        "decomp_sum": decomp_sum,
        "decomp_check": decomp_sum - arith_short,
    }

out("=" * 130)
out("  PART 2 — FULL-YEAR SHORTFALL DECOMPOSITION vs NIFTY B&H")
out(f"  (Arithmetic decomposition: sum of daily 'NIFTY ret − strat ret' across buckets.")
out(f"   Will not exactly match compounded shortfall but indicates source.)")
out("=" * 130)
out(f"  {'Year':<6} {'NIFTY':>8} {'Strat':>8} {'Cum Δ':>8} {'Arith Δ':>9} "
    f"{'(a) Mom drag':>13} {'(b) Defensive':>14} {'(c) Override':>13} {'a+b+c':>9} {'check':>9}")
out("  " + "-"*6 + " " + "-"*8 + " " + "-"*8 + " " + "-"*8 + " " + "-"*9 + " "
    + "-"*13 + " " + "-"*14 + " " + "-"*13 + " " + "-"*9 + " " + "-"*9)
decomps = {}
for y in LOSS_YEARS:
    d = compute_year_decomp(y)
    decomps[y] = d
    out(f"  {y:<6} {d['cum_nifty']*100:+7.2f}% {d['cum_strat']*100:+7.2f}% "
        f"{d['actual_short']*100:+7.2f}pp {d['arith_short']*100:+8.2f}pp "
        f"{d['mom_drag']*100:+12.2f}pp {d['defensive']*100:+13.2f}pp "
        f"{d['override_cost']*100:+12.2f}pp {d['decomp_sum']*100:+8.2f}pp "
        f"{d['decomp_check']*100:+8.4f}pp")
out()
out("  Reading the buckets: positive = lost to NIFTY in that bucket; negative = saved.")
out("  (a) Mom30 drag = on LONG days: nif_ret - mom_ret  (positive = Mom30 underperformed NIFTY)")
out("  (b) Defensive  = on non-LONG days: nif_ret - asset_held_pre_cost  (positive = we missed NIFTY's gain)")
out("  (c) Override   = total transaction costs in the year")
out("  a+b+c should equal arithmetic shortfall; 'check' column shows any residual.")
out()

# Month-by-month for each loss year
for y in LOSS_YEARS:
    out("=" * 130)
    out(f"  MONTH-BY-MONTH — {y}")
    out("=" * 130)
    out(f"  {'Month':<8} {'LONG':>5} {'V2':>4} {'SH':>4} {'GLD':>4} {'FLT':>4}  "
        f"{'Mom ret':>8} {'NIFTY ret':>10} {'Strat ret':>10} {'NIFTY−Strat':>13}")
    out("  " + "-"*8 + " " + "-"*5 + " " + "-"*4 + " " + "-"*4 + " " + "-"*4 + " " + "-"*4 + "  "
        + "-"*8 + " " + "-"*10 + " " + "-"*10 + " " + "-"*13)
    yr_idx = idx[idx.year == y]
    for m in range(1, 13):
        m_idx = yr_idx[yr_idx.month == m]
        if not len(m_idx): continue
        m_state = state.loc[m_idx].value_counts()
        m_mom   = float((1 + ret_mom.loc[m_idx]).prod() - 1)
        m_nif   = float((1 + ret_nif.loc[m_idx]).prod() - 1)
        m_strat = float((1 + strat_pretax.loc[m_idx]).prod() - 1)
        out(f"  {y}-{m:02d}  {m_state.get('LONG', 0):>4d}  {m_state.get('LONG_V2', 0):>3d}  "
            f"{m_state.get('SHORT', 0):>3d}  {m_state.get('GOLD', 0):>3d}  {m_state.get('FLAT', 0):>3d}  "
            f"{m_mom*100:+7.2f}% {m_nif*100:+9.2f}% {m_strat*100:+9.2f}% "
            f"{(m_nif - m_strat)*100:+12.2f}pp")
    out()

# ─── Part 3: Absolute-vs-relative blind spot test ───────────────────────────
out("=" * 130)
out("  PART 3 — ABSOLUTE-vs-RELATIVE BLIND SPOT")
out(f"  Counts days where Mom30 looks healthy on its OWN 100-DMA but is")
out(f"  underperforming NIFTY on a trailing 60-day basis.")
out(f"  The strategy's regime filter (NIFTY 100-DMA) is blind to this case.")
out("=" * 130)

mom_close = raw["NIFTYMOM30"].reindex(idx).ffill()
mom_100dma = mom_close.rolling(100, min_periods=1).mean()
mom_above_own_dma = mom_close >= mom_100dma

mom_60d = mom_close.pct_change(60)
nif_close = raw["^NSEI"].reindex(idx).ffill()
nif_60d   = nif_close.pct_change(60)
mom_relative_loser = mom_60d < nif_60d

blind_spot = mom_above_own_dma & mom_relative_loser & (state == "LONG")

out(f"  {'Year':<6} {'LONG days':>10} {'Mom>DMA AND Mom60<NIF60':>26} "
    f"{'share':>8} {'Mom60−NIF60 mean':>20}")
out("  " + "-"*6 + " " + "-"*10 + " " + "-"*26 + " " + "-"*8 + " " + "-"*20)
for y in LOSS_YEARS:
    yr_idx = idx[idx.year == y]
    long_y = ((state.loc[yr_idx] == "LONG")).sum()
    bs_y = int(blind_spot.loc[yr_idx].sum())
    share = bs_y / max(long_y, 1) * 100
    diff_mean = float((mom_60d.loc[yr_idx] - nif_60d.loc[yr_idx])[
        (state.loc[yr_idx] == "LONG") & mom_above_own_dma.loc[yr_idx]
    ].mean())
    out(f"  {y:<6} {long_y:>10d} {bs_y:>26d} {share:>7.1f}% {diff_mean*100:+19.2f}%")
# Full sample comparison row
all_long = int((state == "LONG").sum())
all_bs   = int(blind_spot.sum())
all_share = all_bs / max(all_long, 1) * 100
all_diff = float((mom_60d - nif_60d)[(state == "LONG") & mom_above_own_dma].mean())
out(f"  {'(all)':<6} {all_long:>10d} {all_bs:>26d} {all_share:>7.1f}% {all_diff*100:+19.2f}%")
out()

# ─── Part 4a: Rebalance hypothesis test ─────────────────────────────────────
out("=" * 130)
out("  PART 4a — REBALANCE STALENESS HYPOTHESIS")
out(f"  NIFTY 200 Momentum 30 reconstitution effective on first trading day of")
out(f"  January and July. Window: next {REBAL_WINDOW} trading days marked")
out(f"  'post-rebalance'. Compare regime signal accuracy.")
out("=" * 130)

# Build post-rebal mask
post_rebal = pd.Series(False, index=idx)
years_all = sorted(set(idx.year))
rebal_dates = []
for y in years_all:
    for month in [1, 7]:
        eff = idx[(idx.year == y) & (idx.month == month)]
        if len(eff):
            d = eff[0]
            i0 = idx.get_loc(d)
            post_rebal.iloc[i0:min(i0 + REBAL_WINDOW, len(idx))] = True
            rebal_dates.append(d)

# Compare strategy hit rate (positive Mom30 day vs negative) on LONG days
# between post-rebal windows and others
long_mask_full = (state == "LONG")
ret_mom_on_long = ret_mom[long_mask_full]
state_on_long = state[long_mask_full]
post_long = long_mask_full & post_rebal
other_long = long_mask_full & ~post_rebal

def stat_block(mask, label):
    n = int(mask.sum())
    if n == 0: return None
    r = ret_mom[mask]
    hit = (r > 0).mean()
    mean = r.mean()
    sd = r.std()
    sharpe = mean/sd * np.sqrt(252) if sd > 0 else 0
    return (label, n, hit, mean*252, sd*np.sqrt(252), sharpe)

rows = []
rows.append(stat_block(post_long, "Post-rebal LONG days"))
rows.append(stat_block(other_long, "Other LONG days"))
out(f"  {'Bucket':<26} {'Days':>6} {'Hit %':>7} {'Ann.ret':>9} {'Ann.vol':>9} {'Sharpe':>8}")
out("  " + "-"*26 + " " + "-"*6 + " " + "-"*7 + " " + "-"*9 + " " + "-"*9 + " " + "-"*8)
for r in rows:
    if r is None: continue
    label, n, hit, ar, av, sh = r
    out(f"  {label:<26} {n:>6d} {hit*100:>6.1f}% {ar*100:>+8.2f}% {av*100:>8.2f}% {sh:>+8.3f}")
out()

# Per-year version for the loss years
out(f"  Per-loss-year breakdown:")
out(f"  {'Year':<6} {'Post-rebal LONG':>16} {'Hit%':>6} {'Sharpe':>8}  "
    f"{'Other LONG':>11} {'Hit%':>6} {'Sharpe':>8}")
out("  " + "-"*6 + " " + "-"*16 + " " + "-"*6 + " " + "-"*8 + "  " + "-"*11 + " "
    + "-"*6 + " " + "-"*8)
for y in LOSS_YEARS:
    yr_mask = (idx.year == y)
    p_mask = post_long & yr_mask
    o_mask = other_long & yr_mask
    p = stat_block(p_mask, "p"); o = stat_block(o_mask, "o")
    p_str = f"{p[1]} d, {p[2]*100:.1f}% hit, sh {p[5]:+.3f}" if p else "—"
    o_str = f"{o[1]} d, {o[2]*100:.1f}% hit, sh {o[5]:+.3f}" if o else "—"
    out(f"  {y:<6} {p[1] if p else 0:>15d}d "
        f"{(p[2]*100 if p else 0):>5.1f}% {(p[5] if p else 0):>+8.3f}  "
        f"{o[1] if o else 0:>10d}d {(o[2]*100 if o else 0):>5.1f}% {(o[5] if o else 0):>+8.3f}")
out()

# ─── Part 4b: 126-DMA aligned to 6-month cycle ──────────────────────────────
out("=" * 130)
out("  PART 4b — 126-DMA (≈6-month) ALTERNATIVE — would it change long/flat calls?")
out("=" * 130)
nifty_100dma = nif_close.rolling(100, min_periods=1).mean()
nifty_126dma = nif_close.rolling(126, min_periods=1).mean()
bull_100 = nif_close > nifty_100dma
bull_126 = nif_close > nifty_126dma
disagree = bull_100 != bull_126

out(f"  {'Year':<6} {'Disagree days':>14} {'% of year':>10} {'100→126 changes call to':>26} "
    f"{'NIFTY ret on changed days':>26}")
out("  " + "-"*6 + " " + "-"*14 + " " + "-"*10 + " " + "-"*26 + " " + "-"*26)
for y in LOSS_YEARS:
    yr_idx = idx[idx.year == y]
    yr_dis = disagree.loc[yr_idx]
    n_dis = int(yr_dis.sum())
    n_tot = len(yr_idx)
    share = n_dis / max(n_tot, 1) * 100
    # On disagree days, what would 126 call vs 100?
    # If 100 says bull and 126 says bear → 126 turns us flat (preventing a long)
    # If 100 says bear and 126 says bull → 126 keeps us long when 100 would have flat
    flips = bull_100.loc[yr_idx] & ~bull_126.loc[yr_idx]  # 100=long, 126=flat (126 makes us flat earlier)
    unflats = ~bull_100.loc[yr_idx] & bull_126.loc[yr_idx]  # 100=flat, 126=long (126 keeps us long)
    flip_str = f"flat early on {int(flips.sum())} d, stay-long {int(unflats.sum())} d"
    # NIFTY return on the changed days (negative if it would have helped to be flat)
    chg_nif_ret = ret_nif.loc[yr_idx][yr_dis].sum() * 100
    out(f"  {y:<6} {n_dis:>14d} {share:>9.1f}% {flip_str:<26} {chg_nif_ret:>+24.2f}pp")
out()

# ─── Plain-English verdict per year ─────────────────────────────────────────
out("=" * 130)
out("  PLAIN-ENGLISH VERDICT per loss year")
out("=" * 130)
out()
for y in LOSS_YEARS:
    d = decomps[y]
    yr_idx = idx[idx.year == y]
    long_y = int((state.loc[yr_idx] == "LONG").sum())
    bs_y = int(blind_spot.loc[yr_idx].sum())
    bs_share = bs_y / max(long_y, 1) * 100
    yr_dis = disagree.loc[yr_idx]
    chg_nif_ret = ret_nif.loc[yr_idx][yr_dis].sum() * 100

    out(f"── {y} ──")
    out(f"  NIFTY B&H: {d['cum_nifty']*100:+.2f}%   Strategy: {d['cum_strat']*100:+.2f}%   "
        f"Shortfall: {d['actual_short']*100:+.2f}pp")
    out(f"  Decomposition:  Mom30-drag {d['mom_drag']*100:+.2f}pp   "
        f"Defensive {d['defensive']*100:+.2f}pp   "
        f"Override {d['override_cost']*100:+.2f}pp")
    out(f"  Blind-spot days (Mom30 healthy on own DMA but losing to NIFTY relative): "
        f"{bs_y}/{long_y} long days = {bs_share:.1f}%")
    out(f"  126-DMA disagrees with 100-DMA on {int(yr_dis.sum())} days "
        f"({float(yr_dis.sum())/len(yr_idx)*100:.1f}% of year). "
        f"NIFTY return on those days: {chg_nif_ret:+.2f}pp.")

    # Diagnose dominant bucket
    abs_drag = abs(d['mom_drag'])
    abs_def  = abs(d['defensive'])
    abs_ovr  = abs(d['override_cost'])
    dominant = max([("Mom30-drag", abs_drag), ("Defensive", abs_def), ("Override", abs_ovr)],
                   key=lambda x: x[1])

    # Verdict
    if dominant[0] == "Mom30-drag" and bs_share > 50:
        verdict = (
            f"(a) PURE relative factor rotation. {bs_share:.0f}% of long days had Mom30 "
            f"healthy on its own DMA but losing to NIFTY relative — the absolute regime "
            f"filter had no signal to act on. A different gate (e.g., relative-strength "
            f"of Mom30 vs NIFTY) would be needed, NOT a different DMA window."
        )
    elif dominant[0] == "Mom30-drag" and abs(chg_nif_ret) > 1.0:
        verdict = (
            f"(c) MIX — primarily Mom30 drag {d['mom_drag']*100:+.1f}pp, with some "
            f"100-DMA staleness ({chg_nif_ret:+.1f}pp of NIFTY return on days where "
            f"126-DMA would have called it differently). Faster cycle alignment might "
            f"help marginally; the bigger lever is the relative-rotation signal."
        )
    elif dominant[0] == "Defensive":
        verdict = (
            f"(b) DEFENSIVE COST DOMINANT. Strategy was out of the market (flat/short/gold) "
            f"while NIFTY rose. This is a regime-filter problem — either the regime "
            f"filter cut too aggressively or a stress signal force-flatted incorrectly. "
            f"Check if 126-DMA would have kept us long during this period."
        )
    else:
        verdict = (
            f"(a) PURE relative factor rotation. Mom30 drag is the biggest single bucket "
            f"({d['mom_drag']*100:+.1f}pp). Even though the blind-spot share is "
            f"{bs_share:.0f}% which doesn't dominate, the loss mechanism is Mom30 "
            f"vs NIFTY, not regime timing."
        )
    out(f"  VERDICT: {verdict}")
    out()

# ─── Save per-day logs ──────────────────────────────────────────────────────
for y in LOSS_YEARS:
    yr_idx = idx[idx.year == y]
    log = pd.DataFrame({
        "C1_state":   state.loc[yr_idx],
        "w_mom":      weights["mom"].loc[yr_idx],
        "w_nif":      weights["nif"].loc[yr_idx],
        "w_gold":     weights["gold"].loc[yr_idx],
        "w_cash":     weights["cash"].loc[yr_idx],
        "ret_mom":    ret_mom.loc[yr_idx],
        "ret_nif":    ret_nif.loc[yr_idx],
        "ret_gold":   ret_gold.loc[yr_idx],
        "ret_cash":   ret_cash.loc[yr_idx],
        "strat_pretax": strat_pretax.loc[yr_idx],
        "daily_short": (ret_nif - strat_pretax).loc[yr_idx],
        "mom_above_own_dma": mom_above_own_dma.loc[yr_idx],
        "mom_60d":    mom_60d.loc[yr_idx],
        "nif_60d":    nif_60d.loc[yr_idx],
        "blind_spot": blind_spot.loc[yr_idx],
        "post_rebal": post_rebal.loc[yr_idx],
        "bull_100":   bull_100.loc[yr_idx],
        "bull_126":   bull_126.loc[yr_idx],
        "126_disagree": disagree.loc[yr_idx],
    })
    out_path = os.path.join(RESULTS_DIR, f"diagnose_factor_years_{y}.csv")
    log.to_csv(out_path)
out(f"  Per-day logs saved to {RESULTS_DIR}/diagnose_factor_years_<year>.csv")
out()

with open(OUTPUT_PATH, "w") as f:
    f.write("\n".join(lines))
print(f"\nSaved to {OUTPUT_PATH}", file=sys.stderr)
