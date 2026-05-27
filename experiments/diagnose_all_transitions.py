"""
diagnose_all_transitions.py — DEEP DIVE.

For every state transition in C1's history (every day the strategy changes
position type), produce a per-transition record:

  - Date and transition (e.g. LONG → FLAT, FLAT → SHORT, etc.)
  - Triggers active that day (regime-bear, slow-stress, panic-short, G10 gate, V2)
  - Pre-context: NIFTY/Mom30/Gold prices, VIX + 90d z, INR trend, trailing 20d returns
  - Outcome: next-20-day returns of each asset, what the strategy actually held,
    and a strategy-vs-counterfactual P&L delta
  - Verdict: WORKED / FALSE SIGNAL / MIXED / NEUTRAL — automated tag based on
    whether the transition actually helped vs hurt

States are the 5 production C1 states:
  LONG       — long Mom30 (calm long, V2 not active)
  LONG_V2    — long, V2 active (NIFTY 50 swap)
  FLAT       — cash
  SHORT      — short NIFTY 50 (panic-short)
  GOLD       — long gold (G10 gate fired during stress-flat)

Output:
  results/all_transitions_detail.txt   (chronological, ~5-7 lines per transition)
  results/all_transitions_summary.csv  (machine-readable)
"""

import os, sys
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                 "experiments"))
import strategy_lab as L

START, END = "2008-04-01", "2025-12-31"
FORWARD_DAYS = 20
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
strat_pretax = df1["strategy_return_pretax"]

# Asset returns
nifty = raw["^NSEI"].reindex(idx).ffill()
mom30 = raw["NIFTYMOM30"].reindex(idx).ffill()
gold  = raw["GOLDBEES.NS"].reindex(idx).ffill()
vix   = raw["^INDIAVIX"].reindex(idx).ffill()
inr   = raw["INR=X"].reindex(idx).ffill()

ret_nif  = nifty.pct_change().fillna(0.0)
ret_mom  = mom30.pct_change().fillna(0.0)
ret_gold = gold.pct_change().fillna(0.0).clip(-0.5, 0.5)
repo = L.build_rbi_repo_rate_series(idx)
ret_cash = ((repo - 100/10000).clip(lower=0) / 252).reindex(idx).fillna(0.0)

# Macro indicators
vix_90z = (vix - vix.rolling(90).mean()) / vix.rolling(90).std()
inr_20d = inr.pct_change(20)
nifty_100dma = nifty.rolling(100, min_periods=1).mean()
bull = nifty > nifty_100dma

# Signal firing masks
from strategy_lab import SlowStressSignal, PanicShortSignal
sss = SlowStressSignal(inr_window=20, inr_threshold=0.01,
                       vix_z_window=90, vix_z_threshold=1.5, vix_mom_window=5)
psg = PanicShortSignal(vix_level=25, vix_spike=0.50, window=10, dma=100)
ss_fire = (sss.compute(raw) < 0).reindex(idx).fillna(False)
ps_fire = (psg.compute(raw) < 0).reindex(idx).fillna(False)

# G10 gate
gold_10d  = raw["GOLDBEES.NS"].pct_change(10).reindex(idx)
inr_10d   = raw["INR=X"].pct_change(10).reindex(idx)
us10y_20d = raw["^TNX"].pct_change(20).reindex(idx)
g10_gate = (
    (gold_10d > 0) & (gold_10d <= 0.10) &
    (inr_10d > 0.005) &
    (us10y_20d < 0.0)
).fillna(False)

# ─── State classification ───────────────────────────────────────────────────
def classify_state(i):
    long_today = (nifty_pos.iloc[i] == 1.0)
    if not long_today:
        if nifty_pos.iloc[i] == -1.0: return "SHORT"
        if gold_pos.iloc[i] == 1.0:   return "GOLD"
        return "FLAT"
    return "LONG_V2" if bool(v2_active.iloc[i]) else "LONG"

state = pd.Series([classify_state(i) for i in range(len(idx))], index=idx, name="state")

# ─── Identify transitions ──────────────────────────────────────────────────
state_yest = state.shift(1, fill_value=state.iloc[0])
is_transition = state != state_yest
transition_dates = idx[is_transition.values]
# Drop the very first day (no prior to transition from)
transition_dates = transition_dates[1:]

# ─── Per-transition analysis ───────────────────────────────────────────────
def trailing_return(series, end_date, days):
    if end_date not in series.index: return np.nan
    pos = series.index.get_loc(end_date)
    if pos - days < 0: return np.nan
    return float(series.iloc[pos] / series.iloc[pos - days] - 1)

def forward_return(series, start_date, days):
    if start_date not in series.index: return np.nan
    pos = series.index.get_loc(start_date)
    end_pos = min(pos + days, len(series) - 1)
    if end_pos <= pos: return np.nan
    return float(series.iloc[end_pos] / series.iloc[pos] - 1)

def forward_strat(start_date, days):
    if start_date not in idx: return np.nan
    pos = idx.get_loc(start_date)
    end_pos = min(pos + days, len(idx) - 1)
    if end_pos <= pos: return np.nan
    return float((1 + strat_pretax.iloc[pos:end_pos+1]).prod() - 1)

records = []
for trans_dt in transition_dates:
    i = idx.get_loc(trans_dt)
    from_s = state.iloc[i - 1]
    to_s   = state.iloc[i]
    # Triggers on the day of transition
    trig_ss     = bool(ss_fire.iloc[i])
    trig_ps     = bool(ps_fire.iloc[i])
    trig_bear   = not bool(bull.iloc[i])
    trig_g10    = bool(g10_gate.iloc[i])
    trig_v2     = bool(v2_active.iloc[i])
    # Pre-context
    n_close = float(nifty.iloc[i])
    m_close = float(mom30.iloc[i])
    g_close = float(gold.iloc[i]) if not pd.isna(gold.iloc[i]) else None
    vix_lvl = float(vix.iloc[i]) if not pd.isna(vix.iloc[i]) else None
    vix_z = float(vix_90z.iloc[i]) if not pd.isna(vix_90z.iloc[i]) else None
    inr_t = float(inr_20d.iloc[i]) if not pd.isna(inr_20d.iloc[i]) else None
    t20_n = trailing_return(nifty, trans_dt, 20)
    t20_m = trailing_return(mom30, trans_dt, 20)
    # Forward
    f20_n = forward_return(nifty, trans_dt, FORWARD_DAYS)
    f20_m = forward_return(mom30, trans_dt, FORWARD_DAYS)
    f20_g = forward_return(gold, trans_dt, FORWARD_DAYS)
    f20_strat = forward_strat(trans_dt, FORWARD_DAYS)
    # Cause inference
    cause = "regime"
    if trig_ps and to_s == "SHORT": cause = "panic-short"
    elif trig_ss and to_s == "FLAT": cause = "slow-stress"
    elif trig_g10 and to_s == "GOLD": cause = "G10 gate"
    elif trig_v2 and to_s == "LONG_V2": cause = "V2 overlay"
    elif trig_bear and to_s == "FLAT": cause = "regime (bear)"
    elif not trig_bear and to_s == "LONG": cause = "regime (bull) clears"
    elif from_s == "GOLD" and to_s == "FLAT": cause = "G10 exit / gold momentum negative"
    elif from_s == "SHORT" and to_s == "FLAT": cause = "panic-short exit (MA cross or time cap)"
    elif from_s == "FLAT" and to_s == "LONG":
        cause = "stress cleared / regime bull"
    # Verdict
    verdict = "NEUTRAL"
    is_defensive_move = to_s in ("FLAT", "SHORT", "GOLD") and from_s in ("LONG", "LONG_V2")
    is_risk_on = to_s in ("LONG", "LONG_V2") and from_s in ("FLAT", "SHORT", "GOLD")
    if is_defensive_move:
        if f20_n is not None and f20_n < -0.02:
            verdict = "WORKED — went defensive before drop"
        elif f20_n is not None and f20_n > 0.02:
            verdict = "FALSE SIGNAL — went defensive but NIFTY rose"
        else:
            verdict = "NEUTRAL — small move next 20d"
    elif is_risk_on:
        if f20_m is not None and f20_m > 0.02:
            verdict = "WORKED — re-engaged into rising Mom30"
        elif f20_m is not None and f20_m < -0.02:
            verdict = "FALSE SIGNAL — re-engaged but Mom30 fell"
        else:
            verdict = "NEUTRAL — flat next 20d"
    elif to_s == "SHORT" and from_s != "SHORT":
        if f20_n is not None and f20_n < -0.02:
            verdict = "WORKED — short caught the drop"
        elif f20_n is not None and f20_n > 0.02:
            verdict = "FALSE SIGNAL — short fired against rising NIFTY"

    records.append({
        "id": len(records) + 1,
        "date": trans_dt,
        "year": trans_dt.year,
        "from": from_s, "to": to_s, "cause": cause,
        "trig_ss": trig_ss, "trig_ps": trig_ps, "trig_bear": trig_bear,
        "trig_g10": trig_g10, "trig_v2": trig_v2,
        "n_close": n_close, "m_close": m_close, "g_close": g_close,
        "vix": vix_lvl, "vix_z": vix_z, "inr_20d": inr_t,
        "t20_n": t20_n, "t20_m": t20_m,
        "f20_n": f20_n, "f20_m": f20_m, "f20_g": f20_g, "f20_strat": f20_strat,
        "verdict": verdict,
    })

# ─── Save CSV ─────────────────────────────────────────────────────────────
df_trans = pd.DataFrame(records)
csv_path = os.path.join(RESULTS_DIR, "all_transitions_summary.csv")
df_trans.to_csv(csv_path, index=False)

# ─── Build long-form text report ──────────────────────────────────────────
lines = []
def out(s=""): lines.append(s)

out("=" * 130)
out(f"  ALL TRANSITIONS DEEP DIVE — {len(records)} state changes in C1's history "
    f"(2008-04-01 → 2025-12-31)")
out("=" * 130)
out()
out(f"  States: LONG (Mom30) | LONG_V2 (NIFTY 50 in V2 window) | FLAT (cash) | "
    f"SHORT (-NIFTY) | GOLD (long gold)")
out(f"  For each transition: triggers active, pre-context, next {FORWARD_DAYS}-day outcome, verdict.")
out(f"  Verdict logic: WORKED if defensive transition was followed by NIFTY drop ≥2%, or risk-on")
out(f"  transition was followed by Mom30 rise ≥2%. FALSE SIGNAL if the opposite. NEUTRAL if small move.")
out()

# Transition-type distribution
trans_types = df_trans.apply(lambda r: f"{r['from']} → {r['to']}", axis=1).value_counts()
out("=" * 130)
out(f"  HIGH-LEVEL DISTRIBUTION ({len(records)} transitions)")
out("=" * 130)
out(f"  By transition type:")
for tt, n in trans_types.items():
    out(f"    {tt:<22}  {n} transitions")
out()
verdict_counts = df_trans["verdict"].apply(lambda v: v.split(" ")[0]).value_counts()
out(f"  By verdict (first word):")
for v, n in verdict_counts.items():
    out(f"    {v:<14}  {n} transitions ({n/len(records)*100:.0f}%)")
out()
cause_counts = df_trans["cause"].value_counts()
out(f"  By cause:")
for c, n in cause_counts.items():
    out(f"    {c:<35}  {n} transitions")
out()

# Per-transition records — chronological
out("=" * 130)
out("  PER-TRANSITION DETAILS (chronological)")
out("=" * 130)
for r in records:
    date_str = r["date"].strftime("%Y-%m-%d")
    g_str = f"{r['g_close']:.1f}" if r['g_close'] is not None else "n/a"
    vix_str = f"{r['vix']:.1f}" if r['vix'] is not None else "n/a"
    vix_z_str = f"{r['vix_z']:+.2f}" if r['vix_z'] is not None and not pd.isna(r['vix_z']) else "n/a"
    inr_str = f"{r['inr_20d']*100:+.2f}%" if r['inr_20d'] is not None and not pd.isna(r['inr_20d']) else "n/a"
    t20n_str = f"{r['t20_n']*100:+.1f}%" if r['t20_n'] is not None and not pd.isna(r['t20_n']) else "n/a"
    t20m_str = f"{r['t20_m']*100:+.1f}%" if r['t20_m'] is not None and not pd.isna(r['t20_m']) else "n/a"
    f20n_str = f"{r['f20_n']*100:+.1f}%" if r['f20_n'] is not None and not pd.isna(r['f20_n']) else "n/a"
    f20m_str = f"{r['f20_m']*100:+.1f}%" if r['f20_m'] is not None and not pd.isna(r['f20_m']) else "n/a"
    f20g_str = f"{r['f20_g']*100:+.1f}%" if r['f20_g'] is not None and not pd.isna(r['f20_g']) else "n/a"
    f20s_str = f"{r['f20_strat']*100:+.1f}%" if r['f20_strat'] is not None and not pd.isna(r['f20_strat']) else "n/a"
    trigs = []
    if r["trig_ss"]: trigs.append("slow-stress")
    if r["trig_ps"]: trigs.append("panic-short")
    if r["trig_bear"]: trigs.append("bear regime")
    if r["trig_g10"]: trigs.append("G10 gate")
    if r["trig_v2"]: trigs.append("V2 window")
    trigs_str = ", ".join(trigs) if trigs else "none active"
    out(f"")
    out(f"─── #{r['id']:>3} — {date_str} ({r['year']})   {r['from']} → {r['to']}   "
        f"cause: {r['cause']}")
    out(f"  Triggers active: {trigs_str}")
    out(f"  Pre: NIFTY={r['n_close']:.0f}  Mom30={r['m_close']:.0f}  Gold={g_str}  "
        f"VIX={vix_str} (90d z={vix_z_str})  INR 20d={inr_str}")
    out(f"  Trailing 20d: NIFTY {t20n_str}  Mom30 {t20m_str}")
    out(f"  Forward 20d: NIFTY {f20n_str}  Mom30 {f20m_str}  Gold {f20g_str}  "
        f"Strategy actually earned: {f20s_str}")
    out(f"  Verdict: {r['verdict']}")

txt_path = os.path.join(RESULTS_DIR, "all_transitions_detail.txt")
with open(txt_path, "w") as f:
    f.write("\n".join(lines))

print(f"Saved {len(records)} transitions to:", file=sys.stderr)
print(f"  {csv_path}", file=sys.stderr)
print(f"  {txt_path}", file=sys.stderr)

# ─── Print summary to stdout ────────────────────────────────────────────────
print("\n" + "=" * 100)
print(f"  Generated detailed records for {len(records)} state transitions.")
print("=" * 100)
print()
print(f"  By transition type:")
for tt, n in trans_types.items():
    print(f"    {tt:<22}  {n}")
print()
print(f"  By verdict (first word):")
for v, n in verdict_counts.items():
    print(f"    {v:<14}  {n} ({n/len(records)*100:.0f}%)")
print()
print(f"  By cause:")
for c, n in cause_counts.items():
    print(f"    {c:<35}  {n}")
