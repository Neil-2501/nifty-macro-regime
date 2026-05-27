"""
diagnose_all_recovery_windows.py — DEEP DIVE.

For every long re-entry in C1's history (the ~115 recovery windows), produce
a per-window record covering:

  PRE-CONTEXT (leading up to the re-entry):
    - Length of the preceding non-long stretch (days)
    - Position mix during the stretch (flat / short / gold)
    - Reason the strategy was non-long (regime / slow-stress / panic-short)
    - Peak-to-trough drawdown on NIFTY 50 during the prior bear regime
    - Trailing 30/60/126-day returns of Mom30 / NIFTY / Gold at re-entry day
    - VIX level + VIX 90-day z-score at re-entry
    - INR 20-day trend at re-entry

  WINDOW OUTCOME (60 trading days after re-entry):
    - Latched? Days to latch (Mom30 ≥3% above own 100-DMA)
    - Mom30 / NIFTY / Gold / Cash cumulative returns
    - Mom30 daily-sign-flip count (choppiness)
    - NIFTY 100-DMA crossings inside the window
    - WINNING asset (best cumret over the window)
    - What the strategy actually held (Mom30 + costs)

  CONTEXT TAGS:
    - Clean / choppy / very-choppy (based on Mom30 days above DMA streak)
    - Mom30 won / NIFTY won / Gold won / Cash won
    - Strategy-vs-winner cost in pp

Outputs:
  - results/per_window_all_115_detail.txt  (long-form, ~6 lines/window)
  - results/per_window_all_115_summary.csv (machine-readable table)
"""

import os, sys
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                 "experiments"))
import strategy_lab as L

START, END = "2008-04-01", "2025-12-31"
RECOVERY_WINDOW = 60
RESULTS_DIR = os.path.normpath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "results"))
os.makedirs(RESULTS_DIR, exist_ok=True)

# ─── Load + run C1 ──────────────────────────────────────────────────────────
raw = L._load_data()
df0, _ = L.run_config("C0", L.CONFIG_CATALOG["C0"], raw, START, END, vol_target_annual=None)
target_vol = float(df0["strategy_return_pretax"].std() * np.sqrt(252))
df1, diag1 = L.run_config("C1", L.CONFIG_CATALOG["C1"], raw, START, END, vol_target_annual=target_vol)

idx = df1.index
nifty_pos = df1["nifty_position"]
gold_pos  = df1["gold_position"]
v2_active = diag1["v2_active"].reindex(idx).fillna(False)

# Aligned market data
nifty = raw["^NSEI"].reindex(idx).ffill()
mom30 = raw["NIFTYMOM30"].reindex(idx).ffill()
gold  = raw["GOLDBEES.NS"].reindex(idx).ffill()
vix   = raw["^INDIAVIX"].reindex(idx).ffill()
inr   = raw["INR=X"].reindex(idx).ffill()
us10y = raw["^TNX"].reindex(idx).ffill()
repo = L.build_rbi_repo_rate_series(idx)
ret_cash = ((repo - 100/10000).clip(lower=0) / 252).reindex(idx).fillna(0.0)

ret_nif = nifty.pct_change().fillna(0.0)
ret_mom = mom30.pct_change().fillna(0.0)
ret_gold = gold.pct_change().fillna(0.0).clip(-0.5, 0.5)

# Mom30 100-DMA for latch checks
mom_100dma = mom30.rolling(100, min_periods=1).mean()
nifty_100dma = nifty.rolling(100, min_periods=1).mean()
mom_above_3pct_dma = (mom30 / mom_100dma - 1) >= 0.03

# VIX z-score
vix_90z = (vix - vix.rolling(90).mean()) / vix.rolling(90).std()
inr_20d = inr.pct_change(20)

# Slow-stress and panic-short masks for classification
from strategy_lab import SlowStressSignal, PanicShortSignal
sss = SlowStressSignal(inr_window=20, inr_threshold=0.01,
                       vix_z_window=90, vix_z_threshold=1.5, vix_mom_window=5)
psg = PanicShortSignal(vix_level=25, vix_spike=0.50, window=10, dma=100)
ss_fire = (sss.compute(raw) < 0).reindex(idx).fillna(False)
ps_fire = (psg.compute(raw) < 0).reindex(idx).fillna(False)

# ─── Identify all long re-entries ───────────────────────────────────────────
long_mask = (nifty_pos == 1.0)
prev_long = long_mask.shift(1, fill_value=False)
re_entries = idx[(long_mask & ~prev_long).values]
n_windows = len(re_entries)

# ─── Per-window analysis ────────────────────────────────────────────────────
def trailing_return(series, end_date, days):
    if end_date not in series.index: return np.nan
    pos = series.index.get_loc(end_date)
    if pos - days < 0: return np.nan
    return float(series.iloc[pos] / series.iloc[pos - days] - 1)

records = []
for window_id, re_dt in enumerate(re_entries, 1):
    i_re = idx.get_loc(re_dt)
    # Walk backward to find start of non-long stretch
    j = i_re - 1
    while j >= 0 and not long_mask.iloc[j]:
        j -= 1
    stretch_start_i = j + 1
    stretch_len = i_re - stretch_start_i
    stretch_idx = idx[stretch_start_i:i_re]
    # Position mix during the stress stretch
    pos_in = nifty_pos.loc[stretch_idx]
    gold_in = gold_pos.loc[stretch_idx]
    n_flat  = int(((pos_in == 0) & (gold_in == 0)).sum())
    n_short = int((pos_in == -1).sum())
    n_gold  = int((gold_in == 1).sum())
    # Cause of stress on exit day (= the day before stretch start)
    cause = "regime"
    # Check what was firing on stretch_start (entry to non-long)
    if stretch_start_i > 0:
        i_e = stretch_start_i
        if bool(ps_fire.iloc[i_e]): cause = "panic-short"
        elif bool(ss_fire.iloc[i_e]): cause = "slow-stress"
    # Pre-bear NIFTY DD (peak-to-trough during stretch)
    nifty_pre = nifty.loc[stretch_idx]
    if len(nifty_pre) > 1:
        bear_dd = float((nifty_pre / nifty_pre.cummax() - 1).min())
    else:
        bear_dd = 0.0
    # Trailing returns at re-entry
    t30_n = trailing_return(nifty, re_dt, 30)
    t60_n = trailing_return(nifty, re_dt, 60)
    t126_n = trailing_return(nifty, re_dt, 126)
    t30_m = trailing_return(mom30, re_dt, 30)
    t60_m = trailing_return(mom30, re_dt, 60)
    t126_m = trailing_return(mom30, re_dt, 126)
    t60_g = trailing_return(gold, re_dt, 60)
    # Macro at re-entry
    vix_re   = float(vix.iloc[i_re]) if not pd.isna(vix.iloc[i_re]) else np.nan
    vix_z_re = float(vix_90z.iloc[i_re]) if not pd.isna(vix_90z.iloc[i_re]) else np.nan
    inr_re   = float(inr_20d.iloc[i_re]) if not pd.isna(inr_20d.iloc[i_re]) else np.nan

    # Window outcome — 60 trading days after re-entry
    win_end_i = min(i_re + RECOVERY_WINDOW, len(idx))
    win_idx = idx[i_re:win_end_i]
    if len(win_idx) < 2:
        records.append(None)
        continue
    cum_n = float((1 + ret_nif.loc[win_idx]).prod() - 1)
    cum_m = float((1 + ret_mom.loc[win_idx]).prod() - 1)
    cum_g = float((1 + ret_gold.loc[win_idx]).prod() - 1)
    cum_c = float((1 + ret_cash.loc[win_idx]).prod() - 1)
    winner = max([("Mom30", cum_m), ("NIFTY", cum_n), ("Gold", cum_g), ("Cash", cum_c)],
                 key=lambda x: x[1])

    # Latched? Find days when Mom30 ≥3% above 100-DMA inside the window
    above_in_window = mom_above_3pct_dma.loc[win_idx]
    # Find days the strategy was actually long Mom30 within window (could go non-long mid-window)
    long_in_window = long_mask.loc[win_idx]
    v2_in_window = v2_active.loc[win_idx]
    # The C1 strategy held Mom30 (or NIFTY if V2 active) on long-state days
    strat_ret_window = []
    for d in win_idx:
        if not long_mask.loc[d]:
            if nifty_pos.loc[d] == -1.0:
                strat_ret_window.append(-ret_nif.loc[d])
            elif gold_pos.loc[d] == 1.0:
                strat_ret_window.append(ret_gold.loc[d])
            else:
                strat_ret_window.append(ret_cash.loc[d])
        elif v2_active.loc[d]:
            strat_ret_window.append(ret_nif.loc[d])
        else:
            strat_ret_window.append(ret_mom.loc[d])
    cum_strat = float((1 + pd.Series(strat_ret_window)).prod() - 1)

    # Days to latch (first day Mom30 ≥3% above DMA inside window)
    # NOTE: this is academic — C1 doesn't have a latch mechanism; we're computing
    # what a hypothetical latch WOULD see.
    days_to_latch = None
    for k, d in enumerate(win_idx):
        if mom_above_3pct_dma.loc[d]:
            days_to_latch = k + 1
            break
    # Choppiness metrics
    sign_flips = int(((ret_mom.loc[win_idx].shift(1) * ret_mom.loc[win_idx]) < 0).sum())
    above = (nifty.loc[win_idx] > nifty_100dma.loc[win_idx]).astype(int)
    crossings = int((above != above.shift(1)).iloc[1:].sum())

    # Year context
    year = re_dt.year
    # Classification
    if days_to_latch is None:
        chop_class = "very-choppy (never latched in 60d)"
    elif days_to_latch <= 10:
        chop_class = "clean (latched ≤10d)"
    elif days_to_latch <= 30:
        chop_class = "choppy (latched 11-30d)"
    else:
        chop_class = "very-choppy (latched >30d)"

    records.append({
        "id": window_id,
        "year": year,
        "re_entry": re_dt,
        "stretch_start": idx[stretch_start_i] if stretch_start_i < len(idx) else None,
        "stretch_len": stretch_len,
        "n_flat": n_flat, "n_short": n_short, "n_gold": n_gold,
        "cause": cause,
        "bear_dd_pct": bear_dd,
        "t30_n_pct": t30_n, "t60_n_pct": t60_n, "t126_n_pct": t126_n,
        "t30_m_pct": t30_m, "t60_m_pct": t60_m, "t126_m_pct": t126_m,
        "t60_g_pct": t60_g,
        "vix_re": vix_re, "vix_z_re": vix_z_re, "inr_20d_re": inr_re,
        "nifty_at_re": float(nifty.iloc[i_re]),
        "mom30_at_re": float(mom30.iloc[i_re]),
        "gold_at_re": float(gold.iloc[i_re]) if not pd.isna(gold.iloc[i_re]) else None,
        "win_len": len(win_idx),
        "cum_n_pct": cum_n, "cum_m_pct": cum_m, "cum_g_pct": cum_g, "cum_c_pct": cum_c,
        "cum_strat_pct": cum_strat,
        "winner": winner[0],
        "winner_ret_pct": winner[1],
        "sign_flips": sign_flips,
        "crossings": crossings,
        "days_to_latch": days_to_latch if days_to_latch is not None else "never",
        "chop_class": chop_class,
        "ended_non_long_within_window": bool((~long_in_window).any()),
    })

records = [r for r in records if r is not None]

# ─── Save CSV summary ───────────────────────────────────────────────────────
df_sum = pd.DataFrame(records)
csv_path = os.path.join(RESULTS_DIR, "per_window_all_115_summary.csv")
df_sum.to_csv(csv_path, index=False)

# ─── Build long-form text report ────────────────────────────────────────────
lines = []
def out(s=""): lines.append(s)

out("=" * 130)
out(f"  PER-WINDOW DEEP DIVE — {len(records)} recovery windows in C1's history")
out("=" * 130)
out(f"  Each window = the 60 trading days following a long re-entry.")
out(f"  PRE-CONTEXT: stress preceding the re-entry; trailing returns and macro snapshot.")
out(f"  OUTCOME: cumulative returns of each asset in the 60-day window; which asset won.")
out(f"  TAGS: clean / choppy / very-choppy based on Mom30 ≥3% above 100-DMA timing.")
out()

# Top-level distribution stats
out("=" * 130)
out("  HIGH-LEVEL DISTRIBUTION (across all {} windows)".format(len(records)))
out("=" * 130)
chop_counts = pd.Series([r["chop_class"] for r in records]).value_counts()
for cls, n in chop_counts.items():
    out(f"  {cls:<40}  {n} windows ({n/len(records)*100:.0f}%)")
out()
winner_counts = pd.Series([r["winner"] for r in records]).value_counts()
out(f"  Winning asset across windows:")
for asset, n in winner_counts.items():
    avg_ret = df_sum.loc[df_sum["winner"] == asset, "winner_ret_pct"].mean() * 100
    out(f"    {asset:<8}  won {n} windows ({n/len(records)*100:.0f}%)   avg winning return {avg_ret:+.2f}%")
out()
# Year distribution
year_counts = pd.Series([r["year"] for r in records]).value_counts().sort_index()
out(f"  Windows per year:")
out("    " + "  ".join(f"{y}={n}" for y, n in year_counts.items()))
out()

# Per-window detail — compact, ~7 lines per window
out("=" * 130)
out("  PER-WINDOW DETAILS")
out("=" * 130)
for r in records:
    re_str = r["re_entry"].strftime("%Y-%m-%d")
    stretch_str = r["stretch_start"].strftime("%Y-%m-%d") if r["stretch_start"] is not None else "—"
    gold_str = f"{r['gold_at_re']:.1f}" if r['gold_at_re'] is not None else "n/a"
    t60g_str = f"{r['t60_g_pct']*100:+.1f}%" if r['t60_g_pct'] is not None and not pd.isna(r['t60_g_pct']) else "n/a"
    vix_re_str = f"{r['vix_re']:.1f}" if r['vix_re'] is not None and not pd.isna(r['vix_re']) else "n/a"
    vix_z_str = f"{r['vix_z_re']:+.2f}" if r['vix_z_re'] is not None and not pd.isna(r['vix_z_re']) else "n/a"
    inr_str = f"{r['inr_20d_re']*100:+.2f}%" if r['inr_20d_re'] is not None and not pd.isna(r['inr_20d_re']) else "n/a"
    out(f"")
    out(f"─── Window #{r['id']:>3} — re-entry {re_str} ({r['year']})   {r['chop_class']}   "
        f"winner={r['winner']} ({r['winner_ret_pct']*100:+.2f}%)")
    out(f"  Pre: prior non-long stretch {r['stretch_len']:>3}d "
        f"({r['n_flat']}F/{r['n_short']}S/{r['n_gold']}G) cause={r['cause']}  "
        f"prior NIFTY DD={r['bear_dd_pct']*100:+.1f}%")
    out(f"  Macro@re-entry: VIX={vix_re_str} (90d z={vix_z_str})  INR 20d={inr_str}")
    out(f"  Trailing-60d returns: NIFTY {r['t60_n_pct']*100:+.1f}%  Mom30 {r['t60_m_pct']*100:+.1f}%  Gold {t60g_str}")
    out(f"  Prices@re-entry: NIFTY={r['nifty_at_re']:.0f}  Mom30={r['mom30_at_re']:.0f}  Gold={gold_str}")
    out(f"  60d window: Mom30 {r['cum_m_pct']*100:+5.2f}%  NIFTY {r['cum_n_pct']*100:+5.2f}%  "
        f"Gold {r['cum_g_pct']*100:+5.2f}%  Cash {r['cum_c_pct']*100:+5.2f}%  | "
        f"strat (held)={r['cum_strat_pct']*100:+5.2f}%")
    # Mom30 vs strat (strategy held Mom30 mostly, so this should be close)
    # Mom30 vs winner: how much did the strategy miss?
    cost_vs_winner = (r["cum_m_pct"] - r["winner_ret_pct"]) * 100
    out(f"  Mom30 vs winner: {cost_vs_winner:+.2f}pp   choppiness: {r['sign_flips']} sign-flips, "
        f"{r['crossings']} NIFTY 100-DMA crossings  days→latch: {r['days_to_latch']}")

txt_path = os.path.join(RESULTS_DIR, "per_window_all_115_detail.txt")
with open(txt_path, "w") as f:
    f.write("\n".join(lines))

print(f"Saved {len(records)} windows to:", file=sys.stderr)
print(f"  {csv_path}", file=sys.stderr)
print(f"  {txt_path}", file=sys.stderr)

# ─── Print summary to stdout ────────────────────────────────────────────────
print("\n" + "=" * 100)
print(f"  Generated detailed records for {len(records)} recovery windows.")
print("=" * 100)
print(f"\n  Files:")
print(f"    {csv_path}")
print(f"    {txt_path}")
print()
print(f"  Distribution:")
for cls, n in chop_counts.items():
    print(f"    {cls:<40}  {n} windows ({n/len(records)*100:.0f}%)")
print()
print(f"  Winning asset per window:")
for asset, n in winner_counts.items():
    print(f"    {asset:<8}  {n} ({n/len(records)*100:.0f}%)")
