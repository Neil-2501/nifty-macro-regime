"""
test_gold_gate_events.py — TEST ONLY (NOT for production).

Identifies every event where the gold momentum gate fired in Config 6
production over the 2008-2025 in-sample period. Two event types:

  1. ENTRY BLOCK: stress-flat latch began, but gold 10d momentum was
     not positive → strategy stayed in cash for the entire latch
  2. MID-LATCH EXIT: strategy entered gold at latch start, then gold
     10d momentum turned negative → strategy exited gold to cash for
     remainder of latch (one-way door, no re-entry)

Strategy.py is NOT modified. We compare Config 6 (with momentum gate)
to a hypothetical Config 2 (unconditional gold rotation, no gate) and
identify dates where they differ.
"""

import os
import sys
import pandas as pd
import yfinance as yf

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from strategy import (
    make_combiner, MacroStrategy, load_nse_index_csv,
)

# ────────────────────────────────────────────────────────────────────────
# Data loading
# ────────────────────────────────────────────────────────────────────────

WARMUP    = "2006-01-01"
IS_START  = "2008-04-01"
IS_END    = "2025-12-31"
TICKERS   = ["CL=F", "^NSEI", "INR=X", "^INDIAVIX", "GOLDBEES.NS"]

print("Downloading data ...", file=sys.stderr)
raw = yf.download(TICKERS, start=WARMUP, end=None, auto_adjust=True, progress=False)["Close"]
raw.dropna(how="all", inplace=True)
for col in ["CL=F", "^NSEI", "INR=X", "^INDIAVIX"]:
    raw[col] = raw[col].ffill()
fv = raw["GOLDBEES.NS"].first_valid_index()
raw.loc[raw.index >= fv, "GOLDBEES.NS"] = raw.loc[raw.index >= fv, "GOLDBEES.NS"].ffill()

_data_path = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data", "momentum30_history.csv",
)
mom30 = load_nse_index_csv(_data_path, "NIFTYMOM30")
raw["NIFTYMOM30"] = mom30.reindex(raw.index).ffill()


# ────────────────────────────────────────────────────────────────────────
# Run Config 6 (with gate) and Config 2 (no gate)
# ────────────────────────────────────────────────────────────────────────

# Config 6 — production: momentum-gated gold rotation
s6 = MacroStrategy(
    make_combiner(rotate_stress=True, rotate_panic=False, use_momentum_gold=True),
    nifty_cost_bps=3, gold_cost_bps=5,
    long_target="NIFTYMOM30", long_cost_bps=6,
)
res6 = s6.run(raw)

# Config 2 — same gold rotation logic but NO momentum gate (rotates on every stress-flat day)
s2 = MacroStrategy(
    make_combiner(rotate_stress=True, rotate_panic=False, use_momentum_gold=False),
    nifty_cost_bps=3, gold_cost_bps=5,
    long_target="NIFTYMOM30", long_cost_bps=6,
)
res2 = s2.run(raw)

# Gold 10-day momentum (the signal the gate uses)
gold = raw["GOLDBEES.NS"]
gold_10d = gold.pct_change(10)


# ────────────────────────────────────────────────────────────────────────
# Identify gold-rotation "latch events" — using Config 2 as ground truth
# (since Config 2 rotates on every stress-flat day without gating)
# ────────────────────────────────────────────────────────────────────────

# Restrict analysis to in-sample period
res2_is = res2.loc[IS_START:IS_END]
res6_is = res6.loc[IS_START:IS_END]

# A "latch event" = a consecutive period where Config 2 held gold
c2_gold = (res2_is["gold_position"] == 1.0)
c6_gold = (res6_is["gold_position"] == 1.0)

# Detect transitions (start of latch = day Config 2 first goes long gold)
c2_prev = c2_gold.shift(1, fill_value=False)
latch_starts = c2_gold & ~c2_prev    # day where Config 2 enters gold (from cash)
latch_ends   = ~c2_gold &  c2_prev   # day after Config 2 exits gold

start_dates = c2_gold.index[latch_starts].tolist()
end_dates   = c2_gold.index[latch_ends].tolist()
# Align: each start should have a corresponding end
if len(end_dates) < len(start_dates):
    end_dates.append(c2_gold.index[-1])

events = []
for start, end_after in zip(start_dates, end_dates):
    # End_after is the first non-gold day; the actual latch's last gold day is end_after-1 if continuous
    end_idx = c2_gold.index.get_loc(end_after)
    last_gold_day = c2_gold.index[end_idx - 1] if end_idx > 0 else start
    events.append({"start": start, "last_gold_day": last_gold_day})


# ────────────────────────────────────────────────────────────────────────
# For each event, determine what Config 6 did
# ────────────────────────────────────────────────────────────────────────

print()
print("=" * 100)
print("  GOLD MOMENTUM GATE FIRING EVENTS — Config 6 (v1.3 prod) vs unconditional rotation")
print("  In-sample period: 2008-2025 (excludes 2026 OOS)")
print("=" * 100)
print()
print(f"  {'Event':<25}{'C2 latch':<26}{'C6 outcome':<28}{'Gold 10d at start':>18}{'Gold during latch':>20}")
print("  " + "-" * 110)

blocked_events = []
mid_exit_events = []
matched_events = []

for ev in events:
    start = ev["start"]
    last_day = ev["last_gold_day"]
    n_days = c2_gold.index.get_loc(last_day) - c2_gold.index.get_loc(start) + 1

    # Did Config 6 enter gold at this latch?
    c6_window = c6_gold.loc[start:last_day]
    n_c6_gold_days = c6_window.sum()

    # Gold 10d momentum at start of latch
    g10_start = gold_10d.loc[start] * 100 if not pd.isna(gold_10d.loc[start]) else float("nan")

    # Gold performance during the full Config 2 latch
    g_start_price = gold.loc[start]
    g_end_price = gold.loc[last_day]
    g_during = (g_end_price / g_start_price - 1) * 100 if g_start_price > 0 else 0

    event_label = f"{start.date()} ({n_days}d)"
    c2_window_label = f"{start.date()} → {last_day.date()}"

    if n_c6_gold_days == 0:
        # Entry blocked
        outcome = f"BLOCKED (cash 0/{n_days}d)"
        blocked_events.append((start, last_day, n_days, g10_start, g_during))
    elif n_c6_gold_days < n_days:
        # Entered but exited mid-latch
        exit_day_idx = None
        for i, d in enumerate(c6_window.index):
            if c6_window.iloc[i] and (i + 1 < len(c6_window)) and not c6_window.iloc[i + 1]:
                exit_day_idx = i
                break
        if exit_day_idx is not None:
            exit_day = c6_window.index[exit_day_idx]
            n_held = exit_day_idx + 1
            outcome = f"MID-EXIT @ {exit_day.date()} ({n_held}/{n_days}d held)"
        else:
            outcome = f"MID-EXIT ({n_c6_gold_days}/{n_days}d held)"
        mid_exit_events.append((start, last_day, n_days, n_c6_gold_days, g10_start, g_during))
    else:
        # Held throughout — gate did not fire
        outcome = f"HELD ALL {n_days} DAYS"
        matched_events.append((start, last_day, n_days, g10_start, g_during))

    g10_str = f"{g10_start:>+7.2f}%" if not pd.isna(g10_start) else "    n/a"
    print(f"  {event_label:<25}{c2_window_label:<26}{outcome:<28}{g10_str:>17}  {g_during:>+8.2f}%")


# ────────────────────────────────────────────────────────────────────────
# Summary
# ────────────────────────────────────────────────────────────────────────

print()
print("=" * 100)
print("  SUMMARY")
print("=" * 100)
print(f"\n  Total stress-flat latches in 2008-2025: {len(events)}")
print(f"    - Held all days (gate did not fire):  {len(matched_events)}")
print(f"    - Entry blocked (cash entire latch):  {len(blocked_events)}")
print(f"    - Mid-latch exit (held then exited):  {len(mid_exit_events)}")

print()
print("  ENTRY BLOCKS (gate refused entry — gold 10d ≤ 0 at latch start)")
print("  " + "-" * 80)
for start, last_day, n_days, g10, g_during in blocked_events:
    interp = "gate helped (gold fell)" if g_during < -0.5 else ("gate hurt (gold rose)" if g_during > 0.5 else "neutral")
    print(f"    {start.date()} → {last_day.date()} ({n_days}d):  10d momentum {g10:>+6.2f}%  →  "
          f"gold during latch {g_during:>+6.2f}%  ({interp})")

print()
print("  MID-LATCH EXITS (gate exited gold after momentum turned negative)")
print("  " + "-" * 80)
for start, last_day, n_days, n_held, g10, g_during in mid_exit_events:
    interp = "gate helped" if g_during < -0.5 else "gate cost"
    print(f"    {start.date()} → {last_day.date()} ({n_held}/{n_days}d gold):  10d at entry {g10:>+6.2f}%  →  "
          f"gold during full latch {g_during:>+6.2f}%  ({interp})")
