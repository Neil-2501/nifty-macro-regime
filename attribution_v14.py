"""
attribution_v14.py — DIAGNOSTIC ONLY (strategy.py NOT modified).

Decomposes v1.4 strategy performance into:
  1. ASSET SELECTION P&L: Mom30 vs NIFTY on long days (same signals, swap
     long_target). Isolates the cost/benefit of holding Mom30 instead of
     NIFTY-50 as the long-side asset.
  2. REGIME CALL P&L: counterfactual-NIFTY-long-with-same-signals vs NIFTY
     buy-and-hold. Isolates the value created by the strategy's signals
     (when to be long, flat, short, in gold) independent of asset choice.

Decomposition logic:
  Let S    = actual v1.4 strategy (Mom30 as long asset)
      C    = counterfactual: SAME signals/positions, NIFTY as long asset
      N    = NIFTY 50 buy-and-hold

  (S - N) = (S - C) + (C - N)
            |--asset selection--| |--regime call--|

Hypothesis: in years like 2018 / 2022 / 2025 where strategy underperforms
NIFTY, the asset-selection bucket (S - C) is negative (Mom30 was bad) while
the regime-call bucket (C - N) is small or positive (signals worked). This
would confirm the framing "signals work, asset choice has known limitations
in momentum-crash years."

Pre-tax attribution throughout (apply_tax=False).
"""

import os
import sys
import numpy as np
import pandas as pd
import yfinance as yf

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from strategy import (
    make_combiner, MacroStrategy, load_nse_index_csv,
    build_rbi_repo_rate_series, metrics,
)

WARMUP, IS_START, IS_END, OOS_START = "2006-01-01", "2008-04-01", "2025-12-31", "2026-01-01"
TICKERS = ["CL=F", "^NSEI", "INR=X", "^INDIAVIX", "GOLDBEES.NS", "^TNX"]
LONG_BPS, SHORT_BPS, GOLD_BPS, HAIRCUT_BPS = 6, 3, 5, 100
OUTPUT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "attribution_v14_results.txt")


# ─────────────────────────────────────────────────────────────────────────
# Data loading
# ─────────────────────────────────────────────────────────────────────────

print("Downloading data ...", file=sys.stderr)
raw = yf.download(TICKERS, start=WARMUP, end=None, auto_adjust=True,
                  progress=False)["Close"]
raw.dropna(how="all", inplace=True)
for col in ["CL=F", "^NSEI", "INR=X", "^INDIAVIX", "^TNX"]:
    raw[col] = raw[col].ffill()
fv = raw["GOLDBEES.NS"].first_valid_index()
raw.loc[raw.index >= fv, "GOLDBEES.NS"] = raw.loc[raw.index >= fv,
                                                  "GOLDBEES.NS"].ffill()
_data_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "data", "momentum30_history.csv")
mom30 = load_nse_index_csv(_data_path, "NIFTYMOM30")
raw["NIFTYMOM30"] = mom30.reindex(raw.index).ffill()


# ─────────────────────────────────────────────────────────────────────────
# Step 1: Run v1.4 production AND counterfactual (same signals, NIFTY long)
# ─────────────────────────────────────────────────────────────────────────

print("Running v1.4 production (Mom30 long) ...", file=sys.stderr)
s_v14 = MacroStrategy(
    make_combiner(rotate_stress=True, rotate_panic=False, use_momentum_gold=True),
    nifty_cost_bps=SHORT_BPS, gold_cost_bps=GOLD_BPS,
    long_target="NIFTYMOM30", long_cost_bps=LONG_BPS,
    apply_tax=False,   # pre-tax attribution
)
res_v14 = s_v14.run(raw)

print("Running counterfactual (same signals, NIFTY long) ...", file=sys.stderr)
s_counter = MacroStrategy(
    make_combiner(rotate_stress=True, rotate_panic=False, use_momentum_gold=True),
    nifty_cost_bps=SHORT_BPS, gold_cost_bps=GOLD_BPS,
    long_target="^NSEI", long_cost_bps=LONG_BPS,  # SAME cost bps to isolate asset effect
    apply_tax=False,
)
res_counter = s_counter.run(raw)

# Confirm position chains are identical (same signals)
pos_diff = (res_v14["nifty_position"] != res_counter["nifty_position"]).sum()
gold_diff = (res_v14["gold_position"] != res_counter["gold_position"]).sum()
print(f"  Position chain check: nifty_diff={pos_diff}, gold_diff={gold_diff}",
      file=sys.stderr)
if pos_diff > 0 or gold_diff > 0:
    print("WARNING: position chains differ — counterfactual not pure asset swap",
          file=sys.stderr)


# ─────────────────────────────────────────────────────────────────────────
# Step 2: Per-day attribution dataframe
# ─────────────────────────────────────────────────────────────────────────

nifty_daily   = raw["^NSEI"].pct_change().fillna(0.0)
mom30_daily   = raw["NIFTYMOM30"].pct_change().fillna(0.0)
gold_avail    = raw["GOLDBEES.NS"].notna()
gold_daily    = raw["GOLDBEES.NS"].pct_change().fillna(0.0).where(gold_avail, 0.0)
strat_daily   = res_v14["strategy_return_pretax"].fillna(0.0)
counter_daily = res_counter["strategy_return_pretax"].fillna(0.0)

# Shifted position chain (yesterday's position determines today's return)
prev_nifty = res_v14["nifty_position"].shift(1, fill_value=0)
prev_gold  = res_v14["gold_position"].shift(1, fill_value=0)

# State per day (what's earning today's return)
def classify(prev_n, prev_g):
    if prev_n == 1.0: return "long_mom30"
    if prev_n == -1.0: return "short_nifty"
    if prev_g == 1.0: return "gold"
    return "cash"

state = pd.Series([classify(n, g) for n, g in zip(prev_nifty, prev_gold)],
                  index=strat_daily.index, name="state")


# ─────────────────────────────────────────────────────────────────────────
# Step 3: Annual attribution table
# ─────────────────────────────────────────────────────────────────────────

lines = []
def out(s=""): lines.append(s)

out("=" * 135)
out("  ANNUAL ATTRIBUTION DECOMPOSITION (pre-tax)")
out(f"  S = v1.4 actual (Mom30 long), C = counterfactual (same signals, NIFTY long), N = NIFTY buy-and-hold")
out(f"  Asset selection = S - C,  Regime call = C - N,  Total = S - N = (S-C) + (C-N)")
out("=" * 135)
out()
out(f"  {'Year':<6s}{'S (actual)':>11s}{'C (cf-NIFTY)':>14s}{'N (NIFTY BH)':>14s}"
    f"{'Asset (S-C)':>13s}{'Regime (C-N)':>14s}{'Total (S-N)':>14s}"
    f"{'L':>4s}{'C':>4s}{'S':>4s}{'G':>4s}")
out("  " + "-" * 121)

years_to_show = list(range(2008, 2027))
annual_results = []
for y in years_to_show:
    mask = (strat_daily.index.year == y) & (strat_daily.index >= pd.Timestamp(IS_START))
    if not mask.any():
        continue
    s_y = (1 + strat_daily[mask]).prod() - 1
    c_y = (1 + counter_daily[mask]).prod() - 1
    n_y = (1 + nifty_daily[mask]).prod() - 1
    asset_y = s_y - c_y
    regime_y = c_y - n_y
    total_y = s_y - n_y

    state_y = state[mask]
    n_long  = int((state_y == "long_mom30").sum())
    n_cash  = int((state_y == "cash").sum())
    n_short = int((state_y == "short_nifty").sum())
    n_gold  = int((state_y == "gold").sum())

    annual_results.append({
        "year": y, "S": s_y, "C": c_y, "N": n_y,
        "asset": asset_y, "regime": regime_y, "total": total_y,
        "long": n_long, "cash": n_cash, "short": n_short, "gold": n_gold,
    })
    mark = "  <<" if y in (2018, 2022, 2025) else ""
    out(f"  {y:<6d}{s_y*100:>+10.2f}%{c_y*100:>+13.2f}%{n_y*100:>+13.2f}%"
        f"{asset_y*100:>+12.2f}{regime_y*100:>+13.2f}{total_y*100:>+13.2f}"
        f"{n_long:>4d}{n_cash:>4d}{n_short:>4d}{n_gold:>4d}{mark}")

# Full-period totals (IS only)
mask_is = (strat_daily.index >= pd.Timestamp(IS_START)) & (strat_daily.index <= pd.Timestamp(IS_END))
S_is = (1 + strat_daily[mask_is]).prod() - 1
C_is = (1 + counter_daily[mask_is]).prod() - 1
N_is = (1 + nifty_daily[mask_is]).prod() - 1
out("  " + "-" * 121)
out(f"  {'IS tot':<6s}{S_is*100:>+10.2f}%{C_is*100:>+13.2f}%{N_is*100:>+13.2f}%"
    f"{(S_is-C_is)*100:>+12.2f}{(C_is-N_is)*100:>+13.2f}{(S_is-N_is)*100:>+13.2f}")
# CAGR
n_years_is = mask_is.sum() / 252
out(f"  {'CAGR':<6s}{((1+S_is)**(1/n_years_is)-1)*100:>+10.2f}%"
    f"{((1+C_is)**(1/n_years_is)-1)*100:>+13.2f}%"
    f"{((1+N_is)**(1/n_years_is)-1)*100:>+13.2f}%")


# ─────────────────────────────────────────────────────────────────────────
# Step 4: Deep dive on 2018, 2022, 2025
# ─────────────────────────────────────────────────────────────────────────

out()
out("=" * 110)
out("  DEEP DIVE — focus years (2018, 2022, 2025)")
out("=" * 110)

for y in [2018, 2022, 2025]:
    mask = strat_daily.index.year == y
    if not mask.any():
        continue
    s_y = (1 + strat_daily[mask]).prod() - 1
    c_y = (1 + counter_daily[mask]).prod() - 1
    n_y = (1 + nifty_daily[mask]).prod() - 1
    m_y = (1 + mom30_daily[mask]).prod() - 1

    asset_pp = (s_y - c_y) * 100
    regime_pp = (c_y - n_y) * 100
    total_pp = (s_y - n_y) * 100

    state_y = state[mask]
    long_mask = mask & (state == "long_mom30")
    cash_mask = mask & (state == "cash")
    short_mask = mask & (state == "short_nifty")
    gold_mask = mask & (state == "gold")

    # NIFTY return per state
    nifty_on_long  = (1 + nifty_daily[long_mask]).prod() - 1 if long_mask.any() else 0
    nifty_on_cash  = (1 + nifty_daily[cash_mask]).prod() - 1 if cash_mask.any() else 0
    nifty_on_short = (1 + nifty_daily[short_mask]).prod() - 1 if short_mask.any() else 0
    nifty_on_gold  = (1 + nifty_daily[gold_mask]).prod() - 1 if gold_mask.any() else 0

    # Mom30 return on long days
    mom30_on_long = (1 + mom30_daily[long_mask]).prod() - 1 if long_mask.any() else 0
    # Gold return on gold days
    gold_on_gold  = (1 + gold_daily[gold_mask]).prod() - 1 if gold_mask.any() else 0

    out(f"\n  ── {y} ──")
    out(f"  Buy-and-hold context:")
    out(f"    NIFTY 50 (benchmark): {n_y*100:+.2f}%")
    out(f"    Mom30 (long asset):   {m_y*100:+.2f}%")
    out(f"    Mom30 vs NIFTY drag:  {(m_y-n_y)*100:+.2f}pp")
    out()
    out(f"  Strategy variants:")
    out(f"    S = actual v1.4 (Mom30 long):              {s_y*100:+.2f}%")
    out(f"    C = counterfactual (same signals, NIFTY):  {c_y*100:+.2f}%")
    out(f"    N = NIFTY buy-and-hold:                    {n_y*100:+.2f}%")
    out()
    out(f"  Attribution decomposition:")
    out(f"    Asset selection (S - C):   {asset_pp:+.2f}pp  "
        f"{'Mom30 hurt' if asset_pp < 0 else 'Mom30 helped'}")
    out(f"    Regime call    (C - N):    {regime_pp:+.2f}pp  "
        f"{'signals helped' if regime_pp > 0 else 'signals hurt'}")
    out(f"    Total          (S - N):    {total_pp:+.2f}pp")
    out(f"    Reconciliation: ({asset_pp:+.2f}) + ({regime_pp:+.2f}) = {asset_pp+regime_pp:+.2f}pp  "
        f"vs actual total {total_pp:+.2f}pp (match within rounding)")
    out()
    out(f"  Per-state day counts:")
    out(f"    Long Mom30:   {int(long_mask.sum()):3d} days ({long_mask.sum()/mask.sum()*100:.1f}%)")
    out(f"    Cash:         {int(cash_mask.sum()):3d} days ({cash_mask.sum()/mask.sum()*100:.1f}%)")
    out(f"    Short NIFTY:  {int(short_mask.sum()):3d} days ({short_mask.sum()/mask.sum()*100:.1f}%)")
    out(f"    Gold:         {int(gold_mask.sum()):3d} days ({gold_mask.sum()/mask.sum()*100:.1f}%)")
    out()
    out(f"  Per-state asset performance:")
    out(f"    On LONG days  ({int(long_mask.sum())} days): Mom30 {mom30_on_long*100:+.2f}%  "
        f"vs NIFTY {nifty_on_long*100:+.2f}% → asset diff {(mom30_on_long-nifty_on_long)*100:+.2f}pp")
    out(f"    On CASH days  ({int(cash_mask.sum())} days): NIFTY {nifty_on_cash*100:+.2f}% "
        f"(missed by being in cash; '+' here = cash call avoided NIFTY loss)")
    if short_mask.any():
        out(f"    On SHORT days ({int(short_mask.sum())} days): NIFTY {nifty_on_short*100:+.2f}% "
            f"(strategy gained the negative)")
    if gold_mask.any():
        out(f"    On GOLD days  ({int(gold_mask.sum())} days): Gold {gold_on_gold*100:+.2f}%  "
            f"vs NIFTY {nifty_on_gold*100:+.2f}%")
    out()
    # Hypothesis verdict for the year
    if asset_pp < -1 and regime_pp > -1:
        verdict = "HYPOTHESIS HOLDS — asset selection hurt, regime call was neutral or helped"
    elif asset_pp > -1 and regime_pp < -1:
        verdict = "HYPOTHESIS REJECTED — regime call hurt, asset selection was neutral"
    elif asset_pp < 0 and regime_pp < 0:
        verdict = "BOTH HURT — asset selection AND regime call both contributed negatively"
    else:
        verdict = "MIXED"
    out(f"  Verdict: {verdict}")


# ─────────────────────────────────────────────────────────────────────────
# Step 5: Verification of specific claims
# ─────────────────────────────────────────────────────────────────────────

out()
out("=" * 110)
out("  VERIFICATION — specific claims from earlier analysis")
out("=" * 110)

# 2018 cash days share
mask_18 = strat_daily.index.year == 2018
state_18 = state[mask_18]
cash_18 = (state_18 == "cash").sum()
total_18 = len(state_18)
out(f"\n  Claim: 2018 days in cash ~41% (~107 of ~261 days)")
out(f"  Actual: {cash_18} of {total_18} days = {cash_18/total_18*100:.1f}%")

# 2018 NIFTY return on cash days
cash_mask_18 = mask_18 & (state == "cash")
nifty_on_cash_18 = (1 + nifty_daily[cash_mask_18]).prod() - 1 if cash_mask_18.any() else 0
out(f"\n  Claim: 2018 NIFTY return on cash days ~ -5.85%")
out(f"  Actual: {nifty_on_cash_18*100:+.2f}%")

# 2018 Mom30 vs NIFTY full year
n_2018 = (1 + nifty_daily[mask_18]).prod() - 1
m_2018 = (1 + mom30_daily[mask_18]).prod() - 1
out(f"\n  Claim: 2018 Mom30 ~ -2.45%, NIFTY ~ +3.15%")
out(f"  Actual: Mom30 {m_2018*100:+.2f}%, NIFTY {n_2018*100:+.2f}%")


# ─────────────────────────────────────────────────────────────────────────
# Step 6: Counterfactual strategy with NIFTY-as-long — full year-by-year
# ─────────────────────────────────────────────────────────────────────────

out()
out("=" * 110)
out("  COUNTERFACTUAL STRATEGY (same signals, NIFTY long-side) — year-by-year vs NIFTY-BH")
out("=" * 110)
out()
out(f"  {'Year':<6s}{'C-strategy':>14s}{'N-buyhold':>13s}{'C - N':>11s}"
    f"{'C > N?':>10s}")
out("  " + "-" * 54)
n_outperform = 0
n_total = 0
for r in annual_results:
    c, n = r["C"], r["N"]
    diff = (c - n) * 100
    win = "YES" if c > n else "no"
    if c > n: n_outperform += 1
    n_total += 1
    out(f"  {r['year']:<6d}{c*100:>+13.2f}%{n*100:>+12.2f}%{diff:>+10.2f}{win:>10s}")
out("  " + "-" * 54)
out()
out(f"  Years counterfactual outperformed NIFTY-BH: {n_outperform}/{n_total}")
out(f"  (this isolates the value of the SIGNALS, independent of asset choice)")


# ─────────────────────────────────────────────────────────────────────────
# Output 7: aggregate summary for hypothesis check
# ─────────────────────────────────────────────────────────────────────────

out()
out("=" * 110)
out("  AGGREGATE SUMMARY — asset vs regime contribution across all years")
out("=" * 110)
out()
total_asset = sum(r["asset"] for r in annual_results) * 100
total_regime = sum(r["regime"] for r in annual_results) * 100
out(f"  Sum of annual asset-selection contributions:  {total_asset:+.2f}pp")
out(f"  Sum of annual regime-call contributions:      {total_regime:+.2f}pp")
out(f"  (these are arithmetic sums of annual diffs, not compound — useful as a rough total)")
out()

# Hypothesis check on focus years
out(f"  Focus-year hypothesis check (2018 / 2022 / 2025):")
out(f"  Hypothesis: in years strategy underperforms NIFTY, asset selection")
out(f"  is the dominant negative contributor; regime call is small or positive.")
out()
out(f"  {'Year':<6s}{'Asset (S-C)':>14s}{'Regime (C-N)':>14s}{'Holds?':>10s}")
out("  " + "-" * 44)
for y in [2018, 2022, 2025]:
    r = next((x for x in annual_results if x["year"] == y), None)
    if r is None: continue
    a = r["asset"] * 100
    rg = r["regime"] * 100
    holds = "YES" if (a < -1 and rg > -1) else ("NO" if (a > -1 and rg < -1) else "MIXED")
    out(f"  {y:<6d}{a:>+13.2f}{rg:>+13.2f}{holds:>10s}")


# ─────────────────────────────────────────────────────────────────────────
# Save + print
# ─────────────────────────────────────────────────────────────────────────

text = "\n".join(lines)
print(text)
with open(OUTPUT_PATH, "w") as f:
    f.write(text + "\n")
print(f"\nSaved to {OUTPUT_PATH}", file=sys.stderr)
