"""
test_recovery_rotation.py — DIAGNOSTIC.

Tests "NIFTY-first on bear→bull re-entry" overlay. After a regime flip from
bear to bull (NIFTY crosses above 100 DMA), hold NIFTY 50 (cyclicals tend to
lead the V-recovery) for the first N trading days of the new bull regime,
then switch to NIFTY 200 Momentum 30. Rationale: momentum indices rebalance
semi-annually, so just after a crash they still hold pre-crash winners
(defensives) while the recovery is led by beaten-down cyclicals
(Daniel-Moskowitz 2016 momentum-crash result).

Architecture: production strategy.py is NOT modified. The overlay works by
running the strategy twice (once with long-side asset = Mom30 — current
production; once with long-side asset = NIFTY 50 — Cfg4) and splicing the
pre-tax daily returns on the NIFTY-first window. Tax is re-applied to the
spliced series, and a swap-back transaction cost (3 bps exit NIFTY 50 + 6
bps enter Mom30 = 9 bps) is charged on the day the window ends.

Variants:
  V1 — apply NIFTY-first on ALL bear→bull flips.
  V2 — apply only when the preceding bear regime saw NIFTY fall >15% (skip
       minor oscillations).
Switch delays N: 60, 90, 120, 180 trading days.

NOTE: "v1.4" in the prompt refers to the production strategy. Current
production is v1.5 (gold_require_bear=True default). This overlay runs on
top of v1.5 — all stress / panic-short / gold-rotation signals unchanged.
"""

import os, sys
import numpy as np
import pandas as pd
import yfinance as yf

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from strategy import (
    make_combiner, MacroStrategy, RegimeFilter, load_nse_index_csv,
    build_rbi_repo_rate_series, metrics, apply_annual_tax,
)

WARMUP, IS_START, IS_END = "2006-01-01", "2008-04-01", "2025-12-31"
TICKERS = ["CL=F", "^NSEI", "INR=X", "^INDIAVIX", "GOLDBEES.NS", "^TNX"]
LONG_BPS_NIFTY, LONG_BPS_MOM30 = 3, 6
SHORT_BPS, GOLD_BPS, HAIRCUT_BPS = 3, 5, 100
TAX = 0.15
DELAYS = [60, 90, 120, 180]
V2_DRAWDOWN_THRESHOLD = 0.15
OUTPUT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "test_recovery_rotation_results.txt")

# ─── Load data (with on-disk cache to dodge yfinance rate limits) ────────────
CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                     "_yf_cache.pkl")
if os.path.exists(CACHE):
    print(f"Loading cached data from {CACHE} ...", file=sys.stderr)
    raw = pd.read_pickle(CACHE)
else:
    print("Downloading data ...", file=sys.stderr)
    raw = yf.download(TICKERS, start=WARMUP, end="2026-05-12", auto_adjust=True,
                      progress=False)["Close"]
    raw.dropna(how="all", inplace=True)
    if raw.empty or raw["^NSEI"].dropna().empty:
        raise RuntimeError("yfinance returned empty data — re-run later or "
                           "rate limit hit; do NOT cache empty result.")
    raw.to_pickle(CACHE)
for col in ["CL=F", "^NSEI", "INR=X", "^INDIAVIX", "^TNX"]:
    raw[col] = raw[col].ffill()
fv = raw["GOLDBEES.NS"].first_valid_index()
raw.loc[raw.index >= fv, "GOLDBEES.NS"] = raw.loc[raw.index >= fv,
                                                  "GOLDBEES.NS"].ffill()
mom30_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "data", "momentum30_history.csv")
mom30 = load_nse_index_csv(mom30_path, "NIFTYMOM30")
raw["NIFTYMOM30"] = mom30.reindex(raw.index).ffill()

# ─── Run two baselines (Mom30 & NIFTY 50 long-side; everything else identical) ─
def run_baseline(long_target, long_bps):
    c = make_combiner(rotate_stress=True, use_momentum_gold=True)
    ms = MacroStrategy(c, target="^NSEI", gold_target="GOLDBEES.NS",
                       long_target=long_target, long_cost_bps=long_bps,
                       nifty_cost_bps=SHORT_BPS, gold_cost_bps=GOLD_BPS,
                       cash_yield_haircut_bps=HAIRCUT_BPS,
                       apply_tax=False)
    return ms.run(raw)

print("Running baseline (Mom30, current production) ...", file=sys.stderr)
res_mom30 = run_baseline("NIFTYMOM30", LONG_BPS_MOM30)
print("Running baseline (NIFTY 50 long-side) ...", file=sys.stderr)
res_nifty = run_baseline("^NSEI", LONG_BPS_NIFTY)

# Trim to in-sample window
mask = (res_mom30.index >= IS_START) & (res_mom30.index <= IS_END)
mom30_pretax = res_mom30.loc[mask, "strategy_return_pretax"]
nifty_pretax = res_nifty.loc[mask, "strategy_return_pretax"]
nifty_pos    = res_mom30.loc[mask, "nifty_position"]
idx_is       = mom30_pretax.index

# ─── Identify bear→bull regime flips ─────────────────────────────────────────
rf = RegimeFilter(window=100)
bull = rf.bull_mask(raw).loc[idx_is]
prev_bull = bull.shift(1, fill_value=False)
flip_mask = bull & (~prev_bull)
# Drop the first day if it's just because the series started in bull
if len(flip_mask) > 0 and flip_mask.iloc[0]:
    # If the day before (in pre-IS data) was already bull, drop this.
    pre = rf.bull_mask(raw)
    pos_pre = pre.index.get_loc(idx_is[0])
    if pos_pre > 0 and bool(pre.iloc[pos_pre - 1]):
        flip_mask.iloc[0] = False
flips = idx_is[flip_mask.values]

# Drawdown of preceding bear regime, computed on NIFTY 50 close
def preceding_bear_drawdown(flip_date):
    pre = rf.bull_mask(raw)
    pos = pre.index.get_loc(flip_date)
    if pos == 0:
        return None
    end = pos - 1  # last bear day
    start = end
    while start > 0 and not bool(pre.iloc[start - 1]):
        start -= 1
    window = raw["^NSEI"].iloc[start:end + 1]
    if len(window) == 0:
        return 0.0
    peak = window.cummax()
    dd = (window / peak - 1.0).min()
    return abs(float(dd))

flip_dds = {d: preceding_bear_drawdown(d) for d in flips}

flips_v1 = list(flips)
flips_v2 = [d for d, dd in flip_dds.items()
            if dd is not None and dd >= V2_DRAWDOWN_THRESHOLD]

# ─── Build NIFTY-first overlay ───────────────────────────────────────────────
SWAP_BACK_BPS = LONG_BPS_NIFTY + LONG_BPS_MOM30  # 3 + 6 = 9

def nifty_first_mask_for(flips_to_use, N):
    m = pd.Series(False, index=idx_is)
    for f in flips_to_use:
        if f not in idx_is:
            continue
        i0 = idx_is.get_loc(f)
        i1 = min(i0 + N, len(idx_is))
        m.iloc[i0:i1] = True
    return m

def hybrid_posttax(flips_to_use, N):
    nfm = nifty_first_mask_for(flips_to_use, N)
    h = mom30_pretax.copy()
    h[nfm] = nifty_pretax[nfm]
    # Swap-back cost on the day after the NIFTY-first window ends, if the
    # strategy is still long that day (otherwise no asset to rebalance).
    end_day = nfm & ~nfm.shift(-1, fill_value=False)
    swap_back_day = end_day.shift(1, fill_value=False)
    swap_back = swap_back_day & (nifty_pos == 1.0)
    h = h - swap_back.astype(float) * (SWAP_BACK_BPS / 10000)
    return apply_annual_tax(h.fillna(0.0), tax_rate=TAX)

mom30_posttax = apply_annual_tax(mom30_pretax.fillna(0.0), tax_rate=TAX)
nifty_posttax = apply_annual_tax(nifty_pretax.fillna(0.0), tax_rate=TAX)

# ─── Metrics & helpers ───────────────────────────────────────────────────────
def m4(ret):
    m = metrics(ret)
    return {
        "CAGR":   m["cagr"],
        "Sharpe": m["sharpe"],
        "Calmar": m["calmar"],
        "MaxDD":  m["max_dd"],
    }

def year_return(ret, year):
    s = ret[ret.index.year == year]
    return float((1 + s).prod() - 1) if len(s) else 0.0

# ─── Run all variants ────────────────────────────────────────────────────────
results = {}
results["base (Mom30 v1.5)"]      = m4(mom30_posttax)
results["NIFTY 50 only (no rot.)"] = m4(nifty_posttax)
series_for = {
    "base (Mom30 v1.5)":       mom30_posttax,
    "NIFTY 50 only (no rot.)": nifty_posttax,
}
for N in DELAYS:
    lbl1 = f"V1 all flips,  N={N}"
    lbl2 = f"V2 ≥15% DD,   N={N}"
    s1 = hybrid_posttax(flips_v1, N)
    s2 = hybrid_posttax(flips_v2, N)
    results[lbl1] = m4(s1); series_for[lbl1] = s1
    results[lbl2] = m4(s2); series_for[lbl2] = s2

# Best variant by Sharpe (exclude pure NIFTY 50)
best_label, best_metrics = max(
    [(k, v) for k, v in results.items() if k != "NIFTY 50 only (no rot.)"],
    key=lambda kv: kv[1]["Sharpe"],
)

# ─── Write output ────────────────────────────────────────────────────────────
lines = []
def out(s=""):
    lines.append(s); print(s)

out("=" * 110)
out("  RECOVERY ROTATION TEST: NIFTY-first on bear→bull re-entry")
out("  Post-tax throughout (Indian short-term capital gains, 15% annual-net)")
out(f"  IS window: {IS_START} → {IS_END}")
out(f"  Overlay built atop current production (v1.5 — gold_require_bear=True).")
out("=" * 110)
out()
out("Bear→bull regime flips detected (using 100 DMA on NIFTY 50):")
out(f"  {'Date':<12} {'Prev-bear MaxDD':>16} {'V1':>6} {'V2 (≥15%)':>12}")
for f in flips:
    dd = flip_dds[f]
    dd_str = f"{(dd or 0.0)*100:.1f}%" if dd is not None else "n/a"
    v2q = "yes" if (dd is not None and dd >= V2_DRAWDOWN_THRESHOLD) else "no"
    out(f"  {f.strftime('%Y-%m-%d'):<12} {dd_str:>16} {'yes':>6} {v2q:>12}")
out()
out(f"V1 triggers on {len(flips_v1)} flips; V2 triggers on {len(flips_v2)} flips.")
out()

out("=" * 110)
out("  FULL-PERIOD METRICS (post-tax)")
out("=" * 110)
out(f"  {'Variant':<28} {'CAGR':>9} {'Sharpe':>8} {'Calmar':>8} {'MaxDD':>9}")
out(f"  {'-'*28} {'-'*9} {'-'*8} {'-'*8} {'-'*9}")
for label, mm in results.items():
    out(f"  {label:<28} {mm['CAGR']*100:+8.2f}% {mm['Sharpe']:>8.3f} "
        f"{mm['Calmar']:>8.2f} {mm['MaxDD']*100:+8.2f}%")
out()

out("=" * 110)
out("  RECOVERY-YEAR FOCUS — 2009 (GFC recovery) and 2020 (COVID recovery)")
out("=" * 110)
base_2009 = year_return(mom30_posttax, 2009)
base_2020 = year_return(mom30_posttax, 2020)
out(f"  {'Variant':<28} {'2009':>9} {'vs base':>10} {'2020':>9} {'vs base':>10}")
out(f"  {'-'*28} {'-'*9} {'-'*10} {'-'*9} {'-'*10}")
for label in results:
    s = series_for[label]
    r9 = year_return(s, 2009); r20 = year_return(s, 2020)
    out(f"  {label:<28} {r9*100:+8.2f}% {(r9-base_2009)*100:+9.2f}pp "
        f"{r20*100:+8.2f}% {(r20-base_2020)*100:+9.2f}pp")
out()

out("=" * 110)
out(f"  YEAR-BY-YEAR — base (Mom30 v1.5) vs best variant by Sharpe: {best_label}")
out("=" * 110)
best_series = series_for[best_label]
years = sorted(set(idx_is.year))
out(f"  {'Year':<6} {'Base':>10} {'Best':>10} {'Diff':>10}")
out(f"  {'-'*6} {'-'*10} {'-'*10} {'-'*10}")
for y in years:
    b = year_return(mom30_posttax, y)
    s = year_return(best_series, y)
    out(f"  {y:<6} {b*100:+9.2f}% {s*100:+9.2f}% {(s-b)*100:+9.2f}pp")
out()

# Stability / robustness scan: V1 across N values
out("=" * 110)
out("  ROBUSTNESS — does the result hold across a range of N? (V1, V2)")
out("=" * 110)
out(f"  {'N':>5} {'V1 CAGR':>10} {'V1 Sharpe':>11} {'V2 CAGR':>10} {'V2 Sharpe':>11}")
for N in DELAYS:
    r1 = results[f"V1 all flips,  N={N}"]
    r2 = results[f"V2 ≥15% DD,   N={N}"]
    out(f"  {N:>5} {r1['CAGR']*100:+9.2f}% {r1['Sharpe']:>11.3f} "
        f"{r2['CAGR']*100:+9.2f}% {r2['Sharpe']:>11.3f}")
out()

# V2 deep-dive: year-by-year for every N
out("=" * 110)
out("  V2 (≥15% prev-bear DD) — year-by-year for every N (vs base)")
out("=" * 110)
hdr = f"  {'Year':<6} {'Base':>10}"
for N in DELAYS:
    hdr += f" {('N='+str(N)):>10} {('Δ '+str(N)):>9}"
out(hdr)
sep = f"  {'-'*6} {'-'*10}" + (f" {'-'*10} {'-'*9}" * len(DELAYS))
out(sep)
for y in years:
    b = year_return(mom30_posttax, y)
    row = f"  {y:<6} {b*100:+9.2f}%"
    for N in DELAYS:
        s = series_for[f"V2 ≥15% DD,   N={N}"]
        v = year_return(s, y)
        row += f" {v*100:+9.2f}% {(v-b)*100:+8.2f}pp"
    out(row)

with open(OUTPUT_PATH, "w") as f:
    f.write("\n".join(lines))
print(f"\nSaved to {OUTPUT_PATH}", file=sys.stderr)
