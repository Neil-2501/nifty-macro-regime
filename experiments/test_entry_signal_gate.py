"""
test_entry_signal_gate.py — TEST ONLY.

Proposed modification: require an entry signal (USDINR or VIX) to have fired
during a flat period before re-engaging long. The original code goes long
the moment NIFTY > 100 DMA regardless of entry signals. The modified gate
makes entry signals actually matter.

This is a POST-PROCESSING test — strategy.py is not modified. We import the
strategy's standard outputs, then rewrite the position series with the new
re-entry rule, then recompute PnL with the modified positions.

Rule:
  - When the strategy is "long" (position = +1) and was already long
    yesterday → continue (no gate, this is the hold state).
  - When the strategy is "long" (position = +1) but was NOT long yesterday
    (transitioning from flat/short to long) → check the gate:
      * If an entry signal fired any day during the prior flat period
        (or today), allow the long.
      * Otherwise, keep position = 0 and wait for a signal to fire.

Tested against the v1.3 Config 6 production setup (Mom30 long-side,
momentum-gated gold rotation, 100bps repo haircut).
"""

import os
import sys
import pandas as pd
import numpy as np
import yfinance as yf

# Add parent directory to path so we can import strategy.py from the project root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from strategy import (
    make_combiner, MacroStrategy, metrics, position_breakdown,
    load_nse_index_csv, USDINRSignal, IndiaVIXSignal,
    build_rbi_repo_rate_series,
)

# ────────────────────────────────────────────────────────────────────────
# Data loading (same as production)
# ────────────────────────────────────────────────────────────────────────

WARMUP    = "2006-01-01"
IS_START  = "2008-04-01"
IS_END    = "2025-12-31"
OOS_START = "2026-01-01"
TICKERS   = ["CL=F", "^NSEI", "INR=X", "^INDIAVIX", "GOLDBEES.NS"]

print("Downloading data...", file=sys.stderr)
raw = yf.download(TICKERS, start=WARMUP, end=None, auto_adjust=True, progress=False)["Close"]
raw.dropna(how="all", inplace=True)
for col in ["CL=F", "^NSEI", "INR=X", "^INDIAVIX"]:
    raw[col] = raw[col].ffill()
fv = raw["GOLDBEES.NS"].first_valid_index()
raw.loc[raw.index >= fv, "GOLDBEES.NS"] = raw.loc[raw.index >= fv, "GOLDBEES.NS"].ffill()
_data_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                          "data", "momentum30_history.csv")
mom30 = load_nse_index_csv(_data_path, "NIFTYMOM30")
raw["NIFTYMOM30"] = mom30.reindex(raw.index).ffill()

# ────────────────────────────────────────────────────────────────────────
# Run original Config 6 (the production strategy)
# ────────────────────────────────────────────────────────────────────────

s6 = MacroStrategy(
    make_combiner(rotate_stress=True, rotate_panic=False, use_momentum_gold=True),
    nifty_cost_bps=3, gold_cost_bps=5,
    long_target="NIFTYMOM30", long_cost_bps=6,
)
orig_res = s6.run(raw)

# ────────────────────────────────────────────────────────────────────────
# Apply the modified re-entry gate as POST-PROCESSING
# ────────────────────────────────────────────────────────────────────────

# Compute the entry signal score series (same as Lane 1 internal)
usdinr_sig = USDINRSignal(window=10, threshold=0.01).compute(raw)
vix_sig    = IndiaVIXSignal(window=10, threshold=0.20).compute(raw)
score = (usdinr_sig * 1.5 + vix_sig * 1.5) / 3.0
entry_fires = (score > 0).fillna(False)

orig_nifty_pos = orig_res["nifty_position"]
orig_gold_pos  = orig_res["gold_position"]

# Walk through the position series and apply the gate
modified_nifty_pos = pd.Series(0.0, index=orig_nifty_pos.index)
sig_fired_since_flat = False
prev_mp = 1.0   # initial state: default-long (matches strategy.py)

orig_vals = orig_nifty_pos.values
fire_vals = entry_fires.values
n = len(orig_nifty_pos)

# Diagnostics: track blocked re-engagements
blocked_count = 0
blocked_dates = []

for i in range(n):
    orig = orig_vals[i]
    signal_today = bool(fire_vals[i])

    if orig == 1.0 and prev_mp != 1.0:
        # Trying to re-engage long from non-long state — check gate
        if sig_fired_since_flat or signal_today:
            mp = 1.0
        else:
            mp = 0.0
            blocked_count += 1
            if blocked_count <= 10:   # log first 10 for visibility
                blocked_dates.append(orig_nifty_pos.index[i])
    elif orig == 1.0:
        mp = 1.0
    elif orig == -1.0:
        mp = -1.0
    else:
        mp = 0.0

    modified_nifty_pos.iloc[i] = mp

    # Update flat-period signal tracker
    if mp == 0.0:
        if signal_today:
            sig_fired_since_flat = True
    else:
        sig_fired_since_flat = False

    prev_mp = mp


# ────────────────────────────────────────────────────────────────────────
# Recompute PnL with the modified nifty_position
# Gold position from original run stays unchanged (gold rotation depends on
# stress_flat_mask which is signal-driven, not position-driven).
# ────────────────────────────────────────────────────────────────────────

def recompute_pnl(nifty_pos, gold_pos):
    """Recompute strategy returns given a modified nifty_position series.
    Mirrors MacroStrategy.run() exactly.
    """
    nifty_returns = raw["^NSEI"].pct_change()
    long_returns  = raw["NIFTYMOM30"].pct_change().fillna(0.0)
    gold_returns  = raw["GOLDBEES.NS"].pct_change().fillna(0.0)
    gold_available = raw["GOLDBEES.NS"].notna()

    # Mask gold where data unavailable
    gold_pos = gold_pos.where(gold_available, 0.0)

    long_pos  = (nifty_pos ==  1.0).astype(float)
    short_pos = (nifty_pos == -1.0).astype(float)

    long_cost  = long_pos.diff().abs()  * (6 / 10000)
    short_cost = short_pos.diff().abs() * (3 / 10000)
    gold_cost  = gold_pos.diff().abs()  * (5 / 10000)

    long_pnl  =  long_pos.shift(1)  * long_returns
    short_pnl = -short_pos.shift(1) * nifty_returns
    asset_pnl = long_pnl + short_pnl - long_cost - short_cost
    gold_pnl  = gold_pos.shift(1) * gold_returns - gold_cost

    # Cash yield on fully-flat days
    cash_position = ((nifty_pos == 0.0) & (gold_pos == 0.0)).astype(float)
    repo_rate = build_rbi_repo_rate_series(raw.index)
    haircut_repo = (repo_rate - 100/10000).clip(lower=0)
    daily_cash_yield = haircut_repo / 252
    cash_pnl = cash_position.shift(1) * daily_cash_yield

    return (asset_pnl + gold_pnl + cash_pnl).rename("strategy_return")


orig_returns = orig_res["strategy_return"]
mod_returns  = recompute_pnl(modified_nifty_pos, orig_gold_pos)

# Build a DataFrame mirroring strategy.py's output for downstream metric calls
mod_res = pd.DataFrame({
    "nifty_return":    raw["^NSEI"].pct_change(),
    "gold_return":     raw["GOLDBEES.NS"].pct_change().fillna(0.0),
    "nifty_position":  modified_nifty_pos,
    "gold_position":   orig_gold_pos.where(raw["GOLDBEES.NS"].notna(), 0.0),
    "strategy_return": mod_returns,
})
mod_res["position"] = mod_res["nifty_position"].copy()


# ────────────────────────────────────────────────────────────────────────
# Sanity check on the gate mechanism
# ────────────────────────────────────────────────────────────────────────

print()
print("=" * 90)
print("  GATE MECHANISM SANITY CHECK")
print("=" * 90)
print(f"  Re-entry attempts blocked by the gate: {blocked_count}")
if blocked_dates:
    print(f"  First 10 blocked dates:")
    for d in blocked_dates[:10]:
        print(f"    {d.date()}")

# Compare day counts in each state
def state_counts(res, label):
    np_, gp_ = res["nifty_position"], res["gold_position"]
    long_n  = ((np_ ==  1.0)).sum()
    short_n = ((np_ == -1.0)).sum()
    long_g  = ((np_ ==  0.0) & (gp_ == 1.0)).sum()
    flat    = ((np_ ==  0.0) & (gp_ == 0.0)).sum()
    total   = long_n + short_n + long_g + flat
    return {"long": int(long_n), "short": int(short_n),
            "gold": int(long_g), "flat": int(flat), "total": int(total)}

bd_orig = state_counts(orig_res.loc[IS_START:IS_END], "orig")
bd_mod  = state_counts(mod_res.loc[IS_START:IS_END], "mod")
print(f"\n  Position breakdown (in-sample 2008-2025, 4632 days):")
print(f"  {'State':<14}{'Original':>12}{'Modified':>12}{'Δ':>10}")
for k in ["long", "short", "gold", "flat"]:
    d = bd_mod[k] - bd_orig[k]
    print(f"  {k:<14}{bd_orig[k]:>12d}{bd_mod[k]:>12d}{d:>+10d}")
print(f"  {'TOTAL':<14}{bd_orig['total']:>12d}{bd_mod['total']:>12d}")


# ────────────────────────────────────────────────────────────────────────
# Headline metrics comparison
# ────────────────────────────────────────────────────────────────────────

print()
print("=" * 90)
print("  HEADLINE METRICS — Original Config 6 vs Modified (entry-signal-gated re-entry)")
print("=" * 90)

orig_is = orig_res.loc[IS_START:IS_END]
mod_is  = mod_res.loc[IS_START:IS_END]

m_orig = metrics(orig_is["strategy_return"])
m_mod  = metrics(mod_is["strategy_return"])
m_nifty = metrics(orig_is["nifty_return"])

print()
print(f"  {'Metric':<25}{'Original v1.3':>16}{'Modified':>14}{'NIFTY B&H':>12}{'Δ Orig→Mod':>13}")
print("  " + "-" * 80)
print(f"  {'Cumulative return':<25}{m_orig['total']*100:>15.1f}%{m_mod['total']*100:>13.1f}%"
      f"{m_nifty['total']*100:>11.1f}%{(m_mod['total']-m_orig['total'])*100:>+12.1f}pp")
print(f"  {'CAGR':<25}{m_orig['cagr']*100:>15.2f}%{m_mod['cagr']*100:>13.2f}%"
      f"{m_nifty['cagr']*100:>11.2f}%{(m_mod['cagr']-m_orig['cagr'])*100:>+12.2f}pp")
print(f"  {'Sharpe (RF=6%)':<25}{m_orig['sharpe']:>16.2f}{m_mod['sharpe']:>14.2f}"
      f"{m_nifty['sharpe']:>12.2f}{m_mod['sharpe']-m_orig['sharpe']:>+13.2f}")
print(f"  {'Sortino':<25}{m_orig['sortino']:>16.2f}{m_mod['sortino']:>14.2f}"
      f"{m_nifty['sortino']:>12.2f}{m_mod['sortino']-m_orig['sortino']:>+13.2f}")
print(f"  {'Calmar':<25}{m_orig['calmar']:>16.2f}{m_mod['calmar']:>14.2f}"
      f"{m_nifty['calmar']:>12.2f}{m_mod['calmar']-m_orig['calmar']:>+13.2f}")
print(f"  {'Max drawdown':<25}{m_orig['max_dd']*100:>15.1f}%{m_mod['max_dd']*100:>13.1f}%"
      f"{m_nifty['max_dd']*100:>11.1f}%{(m_mod['max_dd']-m_orig['max_dd'])*100:>+12.1f}pp")
print(f"  {'Annualized vol':<25}{m_orig['vol']*100:>15.2f}%{m_mod['vol']*100:>13.2f}%"
      f"{m_nifty['vol']*100:>11.2f}%{(m_mod['vol']-m_orig['vol'])*100:>+12.2f}pp")


# ────────────────────────────────────────────────────────────────────────
# Year-by-year comparison
# ────────────────────────────────────────────────────────────────────────

print()
print("=" * 90)
print("  YEAR-BY-YEAR — Original v1.3 vs Modified")
print("=" * 90)
print(f"  {'Year':<6}{'NIFTY':>9}{'Original':>11}{'Modified':>11}{'Δ':>9}{'Orig-NIF':>11}{'Mod-NIF':>11}")
ann_n = (1 + orig_is["nifty_return"]).resample("YE").prod() - 1
ann_o = (1 + orig_is["strategy_return"]).resample("YE").prod() - 1
ann_m = (1 + mod_is["strategy_return"]).resample("YE").prod() - 1
for ts in ann_n.index:
    yr = ts.year
    n  = ann_n.loc[ts]  * 100
    o  = ann_o.loc[ts]  * 100
    m_ = ann_m.loc[ts]  * 100
    d  = m_ - o
    on = o - n
    mn = m_ - n
    print(f"  {yr:<6}{n:>+8.1f}%{o:>+10.1f}%{m_:>+10.1f}%{d:>+8.1f}pp{on:>+10.1f}pp{mn:>+10.1f}pp")


# ────────────────────────────────────────────────────────────────────────
# Crisis windows
# ────────────────────────────────────────────────────────────────────────

print()
print("=" * 90)
print("  CRISIS WINDOWS — Original v1.3 vs Modified")
print("=" * 90)
print(f"  {'Crisis':<18}{'Window':<26}{'NIFTY':>9}{'Orig':>8}{'Mod':>8}{'Δ':>9}")
crises = [
    ("GFC",            "2008-09-01", "2009-03-31"),
    ("Euro debt 2011", "2011-07-01", "2011-12-31"),
    ("Taper 2013",     "2013-05-01", "2013-09-30"),
    ("NBFC 2018",      "2018-09-01", "2019-02-28"),
    ("COVID 2020",     "2020-02-01", "2020-12-31"),
    ("Russia 2022",    "2022-02-01", "2022-06-30"),
    ("2025-26 sell",   "2025-10-01", "2026-04-30"),
]
for name, st, en in crises:
    sub_o = orig_res.loc[st:en]
    sub_m = mod_res.loc[st:en]
    if len(sub_o) == 0:
        continue
    nr  = (1 + sub_o["nifty_return"]).prod() - 1
    or_ = (1 + sub_o["strategy_return"]).prod() - 1
    mr  = (1 + sub_m["strategy_return"]).prod() - 1
    d   = mr - or_
    print(f"  {name:<18}{st} to {en[:7]:<8}{nr*100:>+8.1f}%{or_*100:>+7.1f}%{mr*100:>+7.1f}%{d*100:>+8.1f}pp")


# ────────────────────────────────────────────────────────────────────────
# 2026 OOS
# ────────────────────────────────────────────────────────────────────────

print()
print("=" * 90)
print("  2026 OOS — Original v1.3 vs Modified")
print("=" * 90)
oos_o = orig_res.loc[OOS_START:]
oos_m = mod_res.loc[OOS_START:]
ret_n_oos = (1 + oos_o["nifty_return"]).prod() - 1
ret_o_oos = (1 + oos_o["strategy_return"]).prod() - 1
ret_m_oos = (1 + oos_m["strategy_return"]).prod() - 1

print(f"\n  Trading days: {len(oos_o)}")
print(f"  NIFTY 50 B&H            : {ret_n_oos*100:>+6.2f}%")
print(f"  Original v1.3 (Config 6): {ret_o_oos*100:>+6.2f}%")
print(f"  Modified (gated)        : {ret_m_oos*100:>+6.2f}%")
print(f"  Δ Modified vs Original  : {(ret_m_oos - ret_o_oos)*100:>+6.2f}pp")
print(f"  Δ Modified vs NIFTY     : {(ret_m_oos - ret_n_oos)*100:>+6.2f}pp")


# ────────────────────────────────────────────────────────────────────────
# Detailed look at the blocked re-entries
# ────────────────────────────────────────────────────────────────────────

print()
print("=" * 90)
print("  ALL BLOCKED RE-ENTRY DATES — when the gate kept the strategy flat")
print("=" * 90)
print(f"  Total blocked re-entries (in-sample): {blocked_count}")

# How many days were the strategy in "waiting for signal" mode?
waiting_days = ((orig_nifty_pos.loc[IS_START:IS_END] == 1.0)
                & (modified_nifty_pos.loc[IS_START:IS_END] == 0.0)).sum()
print(f"  Total days flat-waiting-for-signal (in-sample): {waiting_days}")
print(f"  Equivalent to ~{waiting_days/252:.1f} years of additional flat exposure")

# Which years had the most waiting days?
waiting_mask = ((orig_nifty_pos == 1.0) & (modified_nifty_pos == 0.0))
waiting_by_year = waiting_mask.loc[IS_START:IS_END].groupby(waiting_mask.loc[IS_START:IS_END].index.year).sum()
print(f"\n  Waiting days by year (years with ≥1 waiting day):")
for yr, days in waiting_by_year.items():
    if days > 0:
        print(f"    {yr}: {days} days")
