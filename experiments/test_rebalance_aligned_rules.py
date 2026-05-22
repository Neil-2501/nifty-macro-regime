"""
test_rebalance_aligned_rules.py — DIAGNOSTIC.

Tests rebalance-aligned rules for choosing Mom30 vs NIFTY 50 as long-side
asset. NSE rebalances NIFTY 200 Momentum 30 effective first trading day of
Jan and Jul (decisions made on end-of-June and end-of-December data).

At each rebalance, the rule picks the asset to hold for the NEXT 6 months
based on conditions THROUGH the rebalance date — no lookahead. Held until
the next rebalance.

Rules grounded in finance theory:

  R1 — Daniel-Moskowitz bear state.
       If NIFTY 12m return at rebalance < 0% → hold NIFTY (momentum is a
       call option that crashes after bear). Else Mom30.
       Test thresholds: 0%, -5%, -10%.

  R2 — Deep drawdown from 12m peak.
       If NIFTY drawdown from trailing 12m peak < -X% at rebalance → hold
       NIFTY. Else Mom30. Test X = 10%, 15%, 20%.

  R3 — Composition-stale (price proxy).
       If Mom30 trailing 6m return < NIFTY 6m return − X pp → hold NIFTY
       (Mom30's current composition is already losing). Else Mom30.
       Test X = 0, 3, 5 (pp).

  R4 — Vol-scaled (Barroso-Santa-Clara proxy).
       If Mom30 trailing 6m realized vol > NIFTY 6m vol × 1.2 → hold NIFTY
       (Mom30 is in elevated-vol crash-risk regime). Else Mom30.
       Test ratios: 1.1, 1.2, 1.3.

  R5 — Combined bear + drawdown.
       If (NIFTY 12m < 0%) OR (NIFTY drawdown < -15%) → hold NIFTY. Else Mom30.

  R6 — Combined bear AND vol elevated.
       If (NIFTY 12m < 0%) AND (Mom30 6m vol > NIFTY 6m vol × 1.1) → hold
       NIFTY. Else Mom30.

Architecture: production strategy untouched. Overlay splices Cfg4 and Cfg6
pretax returns. Switch cost 9 bps on rebalance day if asset changes. Post-tax
re-applied after splice.
"""

import os, sys
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from strategy import (
    make_combiner, MacroStrategy, load_nse_index_csv,
    metrics, apply_annual_tax,
)

WARMUP, IS_START, IS_END = "2006-01-01", "2008-04-01", "2025-12-31"
LONG_BPS_NIFTY, LONG_BPS_MOM30 = 3, 6
SHORT_BPS, GOLD_BPS, HAIRCUT_BPS = 3, 5, 100
TAX = 0.15
SWAP_BPS = LONG_BPS_NIFTY + LONG_BPS_MOM30
OUTPUT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "test_rebalance_aligned_rules_results.txt")

LOSS_YEARS = [2009, 2018, 2022, 2025]
WIN_YEARS  = [2010, 2011, 2012, 2013, 2014, 2015, 2016, 2017,
              2021, 2023, 2024]

# ─── Data ────────────────────────────────────────────────────────────────────
CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_yf_cache.pkl")
raw = pd.read_pickle(CACHE)
for col in ["CL=F", "^NSEI", "INR=X", "^INDIAVIX", "^TNX"]:
    raw[col] = raw[col].ffill()
fv = raw["GOLDBEES.NS"].first_valid_index()
raw.loc[raw.index >= fv, "GOLDBEES.NS"] = raw.loc[raw.index >= fv,
                                                  "GOLDBEES.NS"].ffill()
mom30 = load_nse_index_csv(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                        "data", "momentum30_history.csv"),
                           "NIFTYMOM30")
raw["NIFTYMOM30"] = mom30.reindex(raw.index).ffill()

def run(long_target, long_bps):
    c = make_combiner(rotate_stress=True, use_momentum_gold=True)
    ms = MacroStrategy(c, target="^NSEI", gold_target="GOLDBEES.NS",
                       long_target=long_target, long_cost_bps=long_bps,
                       nifty_cost_bps=SHORT_BPS, gold_cost_bps=GOLD_BPS,
                       cash_yield_haircut_bps=HAIRCUT_BPS, apply_tax=False)
    return ms.run(raw)

r_mom = run("NIFTYMOM30", LONG_BPS_MOM30)
r_nif = run("^NSEI", LONG_BPS_NIFTY)
mask = (r_mom.index >= IS_START) & (r_mom.index <= IS_END)
idx = r_mom.index[mask]
mom_pretax = r_mom.loc[mask, "strategy_return_pretax"]
nif_pretax = r_nif.loc[mask, "strategy_return_pretax"]
nifty_pos  = r_mom.loc[mask, "nifty_position"]

# ─── Rebalance decision dates ────────────────────────────────────────────────
# NSE Momentum 30 reconstitution: effective first trading day of Jan and Jul.
# Decision made on data through last trading day of preceding Jun / Dec.
def rebalance_decision_dates():
    """Return list of (decision_date, effective_date) pairs across IS."""
    pairs = []
    years = sorted(set(idx.year))
    for y in years:
        # December decision → effective in Jan of y+1
        dec_days = idx[(idx.year == y) & (idx.month == 12)]
        jan_days = idx[(idx.year == y + 1) & (idx.month == 1)]
        if len(dec_days) and len(jan_days):
            pairs.append((dec_days[-1], jan_days[0]))
        # June decision → effective in Jul of y
        jun_days = idx[(idx.year == y) & (idx.month == 6)]
        jul_days = idx[(idx.year == y) & (idx.month == 7)]
        if len(jun_days) and len(jul_days):
            pairs.append((jun_days[-1], jul_days[0]))
    pairs.sort(key=lambda p: p[1])
    return pairs

REBAL = rebalance_decision_dates()
# Hold initial Mom30 from IS start until first effective rebalance
INITIAL_ASSET = True  # True = Mom30

# ─── Feature computation at each decision date ───────────────────────────────
nifty_price  = raw["^NSEI"]
mom30_price  = raw["NIFTYMOM30"]
nifty_ret    = nifty_price.pct_change()
mom30_ret    = mom30_price.pct_change()

def trailing_return(series, end_date, days):
    if end_date not in series.index: return np.nan
    pos = series.index.get_loc(end_date)
    if pos - days < 0: return np.nan
    return float(series.iloc[pos] / series.iloc[pos - days] - 1)

def trailing_vol(series_ret, end_date, days):
    if end_date not in series_ret.index: return np.nan
    pos = series_ret.index.get_loc(end_date)
    if pos - days < 0: return np.nan
    return float(series_ret.iloc[pos - days + 1: pos + 1].std() * np.sqrt(252))

def drawdown_from_peak(series, end_date, days):
    if end_date not in series.index: return np.nan
    pos = series.index.get_loc(end_date)
    if pos - days < 0: return np.nan
    win = series.iloc[pos - days + 1: pos + 1]
    peak = win.max()
    return float(series.iloc[pos] / peak - 1)

def features_at(dec_date):
    f = {}
    f["N_6m"]  = trailing_return(nifty_price, dec_date, 126)
    f["N_12m"] = trailing_return(nifty_price, dec_date, 252)
    f["M_6m"]  = trailing_return(mom30_price, dec_date, 126)
    f["N_dd12m"] = drawdown_from_peak(nifty_price, dec_date, 252)
    f["N_vol6m"] = trailing_vol(nifty_ret, dec_date, 126)
    f["M_vol6m"] = trailing_vol(mom30_ret, dec_date, 126)
    return f

# ─── Rule definitions ────────────────────────────────────────────────────────
def rule_R1(threshold):
    """NIFTY 12m return < threshold → hold NIFTY."""
    def f(feat):
        v = feat["N_12m"]
        if np.isnan(v): return True  # default Mom30 in warmup
        return v >= threshold  # True = Mom30
    return f

def rule_R2(threshold):
    """NIFTY drawdown from 12m peak < -threshold → hold NIFTY."""
    def f(feat):
        v = feat["N_dd12m"]
        if np.isnan(v): return True
        return v >= -threshold
    return f

def rule_R3(threshold):
    """Mom30 6m - NIFTY 6m < -threshold → hold NIFTY."""
    def f(feat):
        m, n = feat["M_6m"], feat["N_6m"]
        if np.isnan(m) or np.isnan(n): return True
        return (m - n) >= -threshold
    return f

def rule_R4(ratio):
    """Mom30 vol / NIFTY vol > ratio → hold NIFTY."""
    def f(feat):
        mv, nv = feat["M_vol6m"], feat["N_vol6m"]
        if np.isnan(mv) or np.isnan(nv): return True
        return (mv / nv) <= ratio
    return f

def rule_R5(bear_thresh, dd_thresh):
    """N_12m < bear_thresh OR N_dd12m < -dd_thresh → hold NIFTY."""
    def f(feat):
        n12 = feat["N_12m"]; ndd = feat["N_dd12m"]
        if np.isnan(n12) or np.isnan(ndd): return True
        bear = n12 < bear_thresh
        dd   = ndd < -dd_thresh
        return not (bear or dd)
    return f

def rule_R6(bear_thresh, vol_ratio):
    """N_12m < bear_thresh AND Mom30 vol/NIFTY vol > vol_ratio → NIFTY."""
    def f(feat):
        n12, mv, nv = feat["N_12m"], feat["M_vol6m"], feat["N_vol6m"]
        if np.isnan(n12) or np.isnan(mv) or np.isnan(nv): return True
        bear = n12 < bear_thresh
        vol  = (mv / nv) > vol_ratio
        return not (bear and vol)
    return f

variants = {
    "R1 bear N12m<0":          rule_R1(0.00),
    "R1 bear N12m<-5%":        rule_R1(-0.05),
    "R1 bear N12m<-10%":       rule_R1(-0.10),
    "R2 dd N_dd<-10%":         rule_R2(0.10),
    "R2 dd N_dd<-15%":         rule_R2(0.15),
    "R2 dd N_dd<-20%":         rule_R2(0.20),
    "R3 stale M6m<N6m":        rule_R3(0.00),
    "R3 stale M6m<N6m-3pp":    rule_R3(0.03),
    "R3 stale M6m<N6m-5pp":    rule_R3(0.05),
    "R4 vol M/N>1.1":          rule_R4(1.10),
    "R4 vol M/N>1.2":          rule_R4(1.20),
    "R4 vol M/N>1.3":          rule_R4(1.30),
    "R5 bear OR dd<-15%":      rule_R5(0.00, 0.15),
    "R5 N12<-5% OR dd<-20%":   rule_R5(-0.05, 0.20),
    "R6 bear AND M-vol>1.1×":  rule_R6(0.00, 1.10),
    "R6 bear AND M-vol>1.2×":  rule_R6(0.00, 1.20),
}

# ─── Build chosen-asset series for a given rule ──────────────────────────────
def chosen_for_rule(rule_fn):
    """Returns a boolean Series on idx — True = hold Mom30 today.
    Decision made at each rebalance decision date; effective on the
    corresponding effective date; held until next effective date.
    """
    out = pd.Series(INITIAL_ASSET, index=idx)
    current = INITIAL_ASSET
    # Iterate effective dates in order
    for dec_date, eff_date in REBAL:
        feat = features_at(dec_date)
        new_asset = bool(rule_fn(feat))
        # Apply from eff_date forward
        if eff_date in idx:
            mask_eff = idx >= eff_date
            out[mask_eff] = new_asset
        current = new_asset
    return out

# ─── Splice ──────────────────────────────────────────────────────────────────
def hybrid_posttax(chosen):
    chosen = chosen.reindex(idx).fillna(True).astype(bool)
    pretax = pd.Series(np.where(chosen, mom_pretax, nif_pretax), index=idx)
    swap = (chosen != chosen.shift(1)) & (nifty_pos == 1.0) & (nifty_pos.shift(1) == 1.0)
    pretax = pretax - swap.astype(float) * (SWAP_BPS / 10000)
    return apply_annual_tax(pretax.fillna(0.0), tax_rate=TAX), int(swap.sum()), swap

# ─── Run ─────────────────────────────────────────────────────────────────────
base_post  = apply_annual_tax(mom_pretax.fillna(0.0), tax_rate=TAX)
nifty_post = apply_annual_tax(nif_pretax.fillna(0.0), tax_rate=TAX)
base_metrics  = metrics(base_post)
nifty_metrics = metrics(nifty_post)

results = {}
series_for = {"base (Mom30 prod)": base_post, "NIFTY 50 always": nifty_post}
n_switches = {"base (Mom30 prod)": 0, "NIFTY 50 always": 0}
chosen_for = {}

for name, fn in variants.items():
    chosen = chosen_for_rule(fn)
    s, nsw, swap = hybrid_posttax(chosen)
    results[name] = metrics(s)
    series_for[name] = s
    n_switches[name] = nsw
    chosen_for[name] = chosen

def year_ret(s, y):
    sl = s[s.index.year == y]
    return float((1 + sl).prod() - 1) if len(sl) else 0.0

# ─── Output ──────────────────────────────────────────────────────────────────
lines = []
def out(s=""): lines.append(s); print(s)

out("=" * 130)
out("  REBALANCE-ALIGNED RULES: Mom30 ↔ NIFTY 50, semi-annual decisions")
out("  Decisions made at end of June / end of December; effective first trading day of next half.")
out("  Post-tax. Switch cost 9 bps on long days only.")
out("=" * 130)
out()

# Decision audit — show one rule's decisions over time for sanity
out("=" * 130)
out("  Section 1 — Rebalance decision dates (effective)")
out("=" * 130)
out(f"  {'Decision':<12} {'Effective':<12} {'N_6m':>8} {'N_12m':>8} {'N_dd12m':>9} "
    f"{'M_6m':>8} {'M-N_6m':>8} {'N_vol':>7} {'M_vol':>7} {'M/N vol':>8}")
out("  " + "-"*12 + " " + "-"*12 + " " + "-"*8 + " " + "-"*8 + " " + "-"*9 + " " +
    "-"*8 + " " + "-"*8 + " " + "-"*7 + " " + "-"*7 + " " + "-"*8)
for dec_date, eff_date in REBAL:
    f = features_at(dec_date)
    def fp(v): return f"{v*100:+.2f}%" if not np.isnan(v) else "  n/a"
    out(f"  {dec_date.strftime('%Y-%m-%d'):<12} {eff_date.strftime('%Y-%m-%d'):<12} "
        f"{fp(f['N_6m']):>8} {fp(f['N_12m']):>8} {fp(f['N_dd12m']):>9} "
        f"{fp(f['M_6m']):>8} {fp(f['M_6m'] - f['N_6m']) if not np.isnan(f['M_6m']) and not np.isnan(f['N_6m']) else '  n/a':>8} "
        f"{(f['N_vol6m']*100):.1f}% {(f['M_vol6m']*100):.1f}% "
        f"{(f['M_vol6m']/f['N_vol6m']):.2f}x" if not np.isnan(f['N_vol6m']) and not np.isnan(f['M_vol6m']) else "")
out()

# Headline
out("=" * 130)
out("  Section 2 — HEADLINE METRICS (sorted by Sharpe)")
out("=" * 130)
all_rows = [("base (Mom30 prod)", base_metrics, 0),
            ("NIFTY 50 always", nifty_metrics, 0)]
for name in variants:
    all_rows.append((name, results[name], n_switches[name]))
all_rows.sort(key=lambda x: -x[1]["sharpe"])
out(f"  {'Variant':<26} {'CAGR':>8} {'Sharpe':>8} {'Calmar':>8} {'MaxDD':>9} "
    f"{'Switches':>9} {'ΔCAGR':>8} {'ΔShp':>7}")
out("  " + "-"*26 + " " + "-"*8 + " " + "-"*8 + " " + "-"*8 + " " + "-"*9 + " " +
    "-"*9 + " " + "-"*8 + " " + "-"*7)
for name, m, nsw in all_rows:
    if name in ("base (Mom30 prod)", "NIFTY 50 always"):
        d_c = d_s = 0
    else:
        d_c = m["cagr"] - base_metrics["cagr"]
        d_s = m["sharpe"] - base_metrics["sharpe"]
    flag = "✓" if (d_c > 0 and d_s > 0) else " "
    out(f"  {name:<26} {m['cagr']*100:+7.2f}% {m['sharpe']:>8.3f} "
        f"{m['calmar']:>8.2f} {m['max_dd']*100:+8.2f}% {nsw:>9} "
        f"{d_c*100:+7.2f}pp {d_s:+7.3f} {flag}")
out()

# Loss/Win breakdown
out("=" * 130)
out("  Section 3 — LOSS-YEAR SAVINGS vs WIN-YEAR GIVEBACK")
out("=" * 130)
def rollup(series, years_list):
    return sum(year_ret(series, y) - year_ret(base_post, y) for y in years_list)

out(f"  {'Variant':<26} {'Loss Δ (4yr)':>14} {'Win Δ (11yr)':>14} {'Net Δ':>10} "
    f"{'ΔCAGR':>8} {'ΔShp':>7}")
out("  " + "-"*26 + " " + "-"*14 + " " + "-"*14 + " " + "-"*10 + " " + "-"*8 + " " + "-"*7)
summary = []
for name in variants:
    s = series_for[name]
    ld = rollup(s, LOSS_YEARS)
    wd = rollup(s, WIN_YEARS)
    m = results[name]
    summary.append((name, ld, wd, ld + wd,
                    m["cagr"] - base_metrics["cagr"],
                    m["sharpe"] - base_metrics["sharpe"]))
summary.sort(key=lambda x: -(x[4]))  # by ΔCAGR
for name, ld, wd, net, dc, ds in summary:
    flag = "✓" if dc > 0 and ds > 0 else " "
    out(f"  {name:<26} {ld*100:+13.2f}pp {wd*100:+13.2f}pp {net*100:+9.2f}pp "
        f"{dc*100:+7.2f}pp {ds:+7.3f} {flag}")
out()

# Year-by-year for best variant
best_name = max(variants.keys(), key=lambda k: results[k]["sharpe"])
out("=" * 130)
out(f"  Section 4 — YEAR-BY-YEAR — base vs best variant: {best_name}")
out("=" * 130)
best_s = series_for[best_name]
years = sorted(set(idx.year))
out(f"  {'Year':<6} {'Base':>9} {'Best':>9} {'Diff':>9}")
out("  " + "-"*6 + " " + "-"*9 + " " + "-"*9 + " " + "-"*9)
for y in years:
    b = year_ret(base_post, y); v = year_ret(best_s, y)
    out(f"  {y:<6} {b*100:+8.2f}% {v*100:+8.2f}% {(v-b)*100:+8.2f}pp")
out()

# Switch log for best
out("=" * 130)
out(f"  Section 5 — Switch log for best variant: {best_name}")
out("=" * 130)
chosen = chosen_for[best_name]
chg = (chosen != chosen.shift(1)) & ~chosen.isna()
chg.iloc[0] = False  # ignore initial
out(f"  {'Date':<12} {'Direction':<22}")
out("  " + "-"*12 + " " + "-"*22)
for d in idx[chg.values]:
    direction = "→ Mom30" if chosen.loc[d] else "→ NIFTY"
    out(f"  {d.strftime('%Y-%m-%d'):<12} {direction:<22}")

with open(OUTPUT_PATH, "w") as f:
    f.write("\n".join(lines))
print(f"\nSaved to {OUTPUT_PATH}", file=sys.stderr)
