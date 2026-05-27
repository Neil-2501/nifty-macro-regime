"""
test_relative_momentum.py — DIAGNOSTIC.

Tests a "relative momentum" overlay on C1 (production v1.5 + V2):
  - On calm long days (long-state AND NOT inside a V2 window):
      hold Mom30 if Mom30 trailing-X-day return > NIFTY 50 trailing-X-day
      return, else hold NIFTY 50.
  - On V2-active long days: hold NIFTY 50 (V2 behavior — unchanged).
  - On all other days (flat / short / gold): identical to C1.

Pre-specified lookback windows: X = 30, 60, 126, 252 trading days.

Architecture: post-processing splice on top of two pre-computed runs (Mom30
long-side and NIFTY 50 long-side), gated by the trailing-momentum comparison.
9 bps swap cost on calm-long days where the chosen asset flips.

Sanity check: on non-long days, V2-active days, and short/gold/flat days,
the variant's pretax must equal C1's pretax exactly. Verified at end.

Reports per window: post-tax CAGR / Sharpe / MaxDD / annual turnover; full
year-by-year; effect in 2018/2022/2025; generalization spread; forward
whipsaw hit rate (when rule switches Mom30→NIFTY, does NIFTY actually
outperform over the next 60 days, or does Mom30 snap back?); and how often
each window holds NIFTY vs Mom30.

Saves per-day log per window to results/.
"""

import os, sys
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                 "experiments"))
import strategy_lab as L

START, END = "2008-04-01", "2025-12-31"
LOOKBACKS = [30, 60, 126, 252]
FORWARD_CHECK_DAYS = 60
SWAP_COST_BPS = 9       # exit Mom30 (6) + enter NIFTY (3), or vice versa
LOSS_YEARS = [2018, 2022, 2025]
OUTPUT_PATH = os.path.normpath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..",
    "test_relative_momentum_results.txt"))
RESULTS_DIR = os.path.normpath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "results"))
os.makedirs(RESULTS_DIR, exist_ok=True)

# ─── Data ────────────────────────────────────────────────────────────────────
raw = L._load_data()

# Run C0 to compute target_vol (not used here but required by lab's run_config signature)
df0, _ = L.run_config("C0", L.CONFIG_CATALOG["C0"], raw, START, END, vol_target_annual=None)
target_vol = float(df0["strategy_return_pretax"].std() * np.sqrt(252))

# ─── Helper: run the strategy with a swappable long-side asset ──────────────
# We need two baselines:
#   Cfg_mom: production strategy with long_target=NIFTYMOM30 (this IS C1's Mom30 baseline)
#   Cfg_nif: production strategy with long_target=^NSEI
# Both with V2 ENABLED so we can pick V2 days from either equivalently.
#
# Run them both, get their pretax series. Build the variant by splicing:
#   On non-long days: take Cfg_mom's pretax (will equal Cfg_nif on those days, since
#     position state is identical between the two — only long asset differs).
#   On V2-active long days: take Cfg_nif's pretax (V2 behavior = 100% NIFTY).
#   On calm long days: based on rotation rule, take Cfg_mom or Cfg_nif pretax.
#   When the choice flips between consecutive calm-long days, charge SWAP_COST_BPS.

def run_with_long_target(long_target, long_bps):
    """Wraps lab's run_config with a custom long-target. Same V2 settings as C1."""
    # Build combiner identically to lab.run_config (production combiner)
    rf = L.RegimeFilter(window=100)
    combiner = L.SignalCombiner(regime_filter=rf,
                                rotate_to_gold_on_stress_flat=True,
                                rotate_to_gold_on_panic_short=False,
                                rotate_with_momentum=True,
                                gold_gate_external=True)
    combiner.add_entry(L.USDINRSignal(window=10, threshold=0.01), weight=1.5)
    combiner.add_entry(L.IndiaVIXSignal(window=10, threshold=0.20), weight=1.5)
    combiner.add_exit_no_cooldown(L.SlowStressSignal(
        inr_window=20, inr_threshold=0.01,
        vix_z_window=90, vix_z_threshold=1.5, vix_mom_window=5))
    combiner.add_short(L.PanicShortSignal(vix_level=25, vix_spike=0.50, window=10, dma=100),
                       hold=False, max_hold_days=60, exit_ma_fast=5, exit_ma_slow=20)
    s = L.MacroStrategyLab(
        combiner, target="^NSEI", gold_target="GOLDBEES.NS",
        long_target=long_target, long_cost_bps=long_bps,
        nifty_cost_bps=3, gold_cost_bps=5, cash_yield_haircut_bps=100,
        apply_tax=False,
        enable_v2=True, v2_dd_threshold=0.15, v2_days=60,
        recovery_latch=None, recovery_allocation="mom_gold_blend",
    )
    res = s.run(raw)
    if isinstance(res, tuple): df, diag = res
    else: df, diag = res, {}
    return df.loc[START:END], diag

print("Running Mom30 long-target baseline ...", file=sys.stderr)
df_mom, diag_mom = run_with_long_target("NIFTYMOM30", 6)
print("Running NIFTY 50 long-target baseline ...", file=sys.stderr)
df_nif, diag_nif = run_with_long_target("^NSEI", 3)

# This is C1 (per the lab's convention)
c1_pretax = df_mom["strategy_return_pretax"]
nif_alt_pretax = df_nif["strategy_return_pretax"]

# Common index and per-day state from C1
idx = c1_pretax.index
nifty_pos = df_mom["nifty_position"]
gold_pos  = df_mom["gold_position"]
v2_active = diag_mom["v2_active"].reindex(idx).fillna(False)

# Asset returns
ret_mom = raw["NIFTYMOM30"].pct_change().reindex(idx).fillna(0.0)
ret_nif = raw["^NSEI"].pct_change().reindex(idx).fillna(0.0)

# Long-state mask
long_mask = (nifty_pos == 1.0)
calm_long = long_mask & (~v2_active)

# ─── Build relative-momentum splice per window ──────────────────────────────
def build_rotation_variant(X):
    """Returns (pretax, chosen_series, swap_count, holdings_summary)."""
    # Trailing X-day returns (no lookahead: use prior X days, decision applies today)
    mom_X = (raw["NIFTYMOM30"] / raw["NIFTYMOM30"].shift(X) - 1).reindex(idx)
    nif_X = (raw["^NSEI"]      / raw["^NSEI"].shift(X)      - 1).reindex(idx)
    # Decision rule (no lookahead): made at end of t-1, applies on day t
    # i.e. shift the decision by 1 so day t uses comparisons through close of t-1
    chose_mom_raw = mom_X >= nif_X  # True = hold Mom30
    chose_mom = chose_mom_raw.shift(1, fill_value=True)  # default first day = Mom30

    # Build chosen series: on non-calm-long days, "chose" is undefined; for tracking
    # we set it to NaN. For pnl purposes we only use it on calm-long days.
    chosen = pd.Series("Mom30", index=idx)
    chosen[calm_long & ~chose_mom] = "NIFTY"
    chosen[~calm_long] = ""  # not applicable

    # Build the variant's daily pretax:
    #   Non-long days OR V2-active long days: use C1 (Mom30 baseline) pretax for those days.
    #     But wait: on V2-active days, the Mom30-baseline strategy ALSO uses NIFTY 50
    #     (since V2 is enabled inside MacroStrategyLab regardless of long_target).
    #     So c1_pretax already reflects V2 behavior. ✓
    #   Calm long days: pick either c1_pretax (Mom30) or nif_alt_pretax (NIFTY).
    variant_pretax = c1_pretax.copy()
    # Where calm-long AND chose NIFTY: use nif_alt_pretax instead
    use_nifty_mask = calm_long & ~chose_mom
    variant_pretax.loc[use_nifty_mask] = nif_alt_pretax.loc[use_nifty_mask]

    # Apply swap cost on calm-long days where the choice flipped from yesterday's
    # choice (and yesterday was ALSO a calm-long day — flips out of/into long state
    # don't add cost beyond what's already in baselines).
    yest_chose_mom = chose_mom.shift(1, fill_value=True)
    yest_calm_long = calm_long.shift(1, fill_value=False)
    flip_today = calm_long & yest_calm_long & (chose_mom != yest_chose_mom)
    variant_pretax = variant_pretax - flip_today.astype(float) * (SWAP_COST_BPS / 10000)

    # Holdings summary
    hold_mom_pct = float((calm_long & chose_mom).sum()) / max(int(calm_long.sum()), 1) * 100
    hold_nif_pct = 100 - hold_mom_pct
    swap_count = int(flip_today.sum())

    return variant_pretax, chosen, swap_count, hold_mom_pct, hold_nif_pct, chose_mom

# Run for each X
runs = {}
for X in LOOKBACKS:
    pretax, chosen, swaps, hm, hn, chose_mom = build_rotation_variant(X)
    posttax = L.apply_annual_tax(pretax.fillna(0.0), tax_rate=0.15)
    runs[X] = {"pretax": pretax, "posttax": posttax, "chosen": chosen,
               "swaps": swaps, "hold_mom_pct": hm, "hold_nif_pct": hn,
               "chose_mom_series": chose_mom}

c1_posttax = L.apply_annual_tax(c1_pretax.fillna(0.0), tax_rate=0.15)

# ─── NIFTY B&H for reference ────────────────────────────────────────────────
nifty_bh_pretax = ret_nif
nifty_bh_post   = L.apply_annual_tax(nifty_bh_pretax.fillna(0.0), tax_rate=0.10)  # LT tax

# ─── Sanity check ───────────────────────────────────────────────────────────
non_long_or_v2 = (~calm_long)  # everything that's NOT calm-long
sanity_pass = {}
for X, r in runs.items():
    diff_on_other = (r["pretax"] - c1_pretax)[non_long_or_v2]
    max_diff = float(diff_on_other.abs().max())
    sanity_pass[X] = max_diff < 1e-10

# ─── Output ──────────────────────────────────────────────────────────────────
lines = []
def out(s=""): lines.append(s); print(s)

out("=" * 130)
out("  RELATIVE-MOMENTUM ROTATION TEST — Mom30 vs NIFTY 50 trailing-X day comparison")
out("=" * 130)
out(f"  IS window: {START} → {END}  ({len(idx)} trading days)")
out(f"  Rule: on calm-long days (long state AND not in V2 window), hold whichever of")
out(f"        Mom30 or NIFTY 50 had the higher trailing-X-day return through yesterday.")
out(f"  On V2-active days: hold NIFTY 50 (V2 default). Non-long days: unchanged from C1.")
out(f"  Swap cost: {SWAP_COST_BPS} bps when the choice flips between consecutive calm-long days.")
out(f"  Lookback windows tested: {LOOKBACKS} trading days.")
out()
out(f"  Day counts:  total {len(idx)}, long-state {int(long_mask.sum())}, "
    f"V2-active long {int((long_mask & v2_active).sum())}, "
    f"calm long (rule applies) {int(calm_long.sum())}.")
out()

# ─── Sanity check ──────────────────────────────────────────────────────────
out("=" * 130)
out("  SANITY — non-calm-long days (V2 / short / flat / gold) unchanged from C1")
out("=" * 130)
all_pass = all(sanity_pass.values())
out(f"  {'Window':<10} {'Max diff on other days':>25} {'Pass?':>8}")
out("  " + "-"*10 + " " + "-"*25 + " " + "-"*8)
for X in LOOKBACKS:
    diff_on_other = (runs[X]["pretax"] - c1_pretax)[non_long_or_v2]
    max_d = float(diff_on_other.abs().max())
    out(f"  X={X:<7} {max_d*100:+23.6f}pp {'✓' if sanity_pass[X] else '❌':>8}")
out()
if not all_pass:
    out("  ⚠️  WARNING: short/gold/flat/V2 P&L not exactly preserved.")
else:
    out("  ✓ All windows preserve C1's pretax on non-calm-long days exactly.")
out()

# ─── Headline metrics ──────────────────────────────────────────────────────
out("=" * 130)
out("  HEADLINE METRICS (post-tax)")
out("=" * 130)
out(f"  {'Variant':<22} {'CAGR':>8} {'Sharpe':>8} {'Calmar':>8} {'MaxDD':>9} "
    f"{'Swaps':>7} {'TO/yr':>8} {'%Mom':>6} {'%NIF':>6}")
out("  " + "-"*22 + " " + "-"*8 + " " + "-"*8 + " " + "-"*8 + " " + "-"*9 + " "
    + "-"*7 + " " + "-"*8 + " " + "-"*6 + " " + "-"*6)
n_years = len(idx) / 252.0
c1_m = L.metrics(c1_posttax)
nifty_m = L.metrics(nifty_bh_post)
out(f"  {'NIFTY B&H (LT 10%)':<22} {nifty_m['cagr']*100:+7.2f}% {nifty_m['sharpe']:>8.3f} "
    f"{nifty_m['calmar']:>8.2f} {nifty_m['max_dd']*100:+8.2f}% {'—':>7} {'—':>8} {'—':>6} {'—':>6}")
out(f"  {'C1 reference':<22} {c1_m['cagr']*100:+7.2f}% {c1_m['sharpe']:>8.3f} "
    f"{c1_m['calmar']:>8.2f} {c1_m['max_dd']*100:+8.2f}% {0:>7d} {'0%':>8} {'100%':>6} {'0%':>6}")
for X in LOOKBACKS:
    m = L.metrics(runs[X]["posttax"])
    swaps = runs[X]["swaps"]
    to_yr = swaps * 2.0 / n_years * 100  # 2× swap = round-trip flip rate
    out(f"  {'Rotation X=' + str(X):<22} {m['cagr']*100:+7.2f}% {m['sharpe']:>8.3f} "
        f"{m['calmar']:>8.2f} {m['max_dd']*100:+8.2f}% {swaps:>7d} "
        f"{to_yr:>7.0f}% {runs[X]['hold_mom_pct']:>5.0f}% {runs[X]['hold_nif_pct']:>5.0f}%")
out()
out("  (%Mom / %NIF are the share of CALM-LONG days the rule held each asset.")
out("   Turnover = swap count × 2 / years × 100%.)")
out()

# ─── Year-by-year ──────────────────────────────────────────────────────────
def year_ret(s, y):
    sl = s[s.index.year == y]
    return float((1 + sl).prod() - 1) if len(sl) else 0.0
years = sorted(set(idx.year))
out("=" * 130)
out("  YEAR-BY-YEAR (post-tax)")
out("=" * 130)
hdr = f"  {'Year':<6} {'NIFTY':>9} {'C1':>9}"
for X in LOOKBACKS: hdr += f" {'X='+str(X):>9}"
out(hdr)
out("  " + "-"*6 + " " + "-"*9 + " " + "-"*9 + (" " + "-"*9) * len(LOOKBACKS))
for y in years:
    n = year_ret(nifty_bh_post, y)
    c = year_ret(c1_posttax, y)
    row = f"  {y:<6} {n*100:+8.2f}% {c*100:+8.2f}%"
    for X in LOOKBACKS:
        v = year_ret(runs[X]["posttax"], y)
        row += f" {v*100:+8.2f}%"
    out(row)
out()

# ─── Year-by-year delta vs C1 ──────────────────────────────────────────────
out("=" * 130)
out("  YEAR-BY-YEAR Δ vs C1 (post-tax)")
out("=" * 130)
hdr = f"  {'Year':<6} {'C1 ret':>9}"
for X in LOOKBACKS: hdr += f" {'X='+str(X):>10}"
out(hdr)
out("  " + "-"*6 + " " + "-"*9 + (" " + "-"*10) * len(LOOKBACKS))
for y in years:
    c = year_ret(c1_posttax, y)
    row = f"  {y:<6} {c*100:+8.2f}%"
    for X in LOOKBACKS:
        v = year_ret(runs[X]["posttax"], y)
        d = (v - c) * 100
        row += f" {d:+9.2f}pp"
    out(row)
out()

# ─── Loss year focus ────────────────────────────────────────────────────────
out("=" * 130)
out("  LOSS-YEAR FOCUS — does the rotation fix 2018 / 2022 / 2025?")
out("=" * 130)
out(f"  {'Year':<6} {'C1':>9} {'X=30':>9} {'X=60':>9} {'X=126':>9} {'X=252':>9}  Comment")
out("  " + "-"*6 + " " + "-"*9 + " " + "-"*9 + " " + "-"*9 + " " + "-"*9 + " " + "-"*9 + "  " + "-"*40)
for y in LOSS_YEARS:
    c = year_ret(c1_posttax, y)
    vals = [year_ret(runs[X]["posttax"], y) for X in LOOKBACKS]
    best_X_idx = int(np.argmax(vals))
    best = vals[best_X_idx]
    fixed = "FIXED (Δ>+2pp)" if best - c > 0.02 else (
        "PARTIAL (Δ>0)" if best - c > 0.005 else "NOT FIXED")
    out(f"  {y:<6} {c*100:+8.2f}% " +
        " ".join(f"{v*100:+8.2f}%" for v in vals) +
        f"  best={LOOKBACKS[best_X_idx]} → {fixed}")
out()

# ─── Generalization check ───────────────────────────────────────────────────
out("=" * 130)
out("  GENERALIZATION CHECK — is improvement spread across years or only 2018?")
out("=" * 130)
for X in LOOKBACKS:
    win_years = []
    lose_years = []
    for y in years:
        c = year_ret(c1_posttax, y)
        v = year_ret(runs[X]["posttax"], y)
        if v - c > 0.005:
            win_years.append((y, v - c))
        elif c - v > 0.005:
            lose_years.append((y, v - c))
    out(f"  X={X}d  "
        f"wins (≥+0.5pp): {len(win_years)} years | "
        f"losses (≤-0.5pp): {len(lose_years)} years")
    if win_years:
        out(f"    Win years: " + ", ".join(f"{y} ({d*100:+.2f}pp)" for y, d in win_years))
    if lose_years:
        out(f"    Loss years: " + ", ".join(f"{y} ({d*100:+.2f}pp)" for y, d in lose_years))
out()

# ─── Forward whipsaw check ──────────────────────────────────────────────────
out("=" * 130)
out(f"  FORWARD WHIPSAW CHECK — on each Mom30→NIFTY switch, did NIFTY actually")
out(f"  outperform Mom30 over the next {FORWARD_CHECK_DAYS} trading days?")
out("=" * 130)
out(f"  {'Window':<8} {'#Mom→NIF':>10} {'#NIF wins next 60d':>20} {'Hit rate':>10}  "
    f"{'Mean Δ next 60d':>18}")
out("  " + "-"*8 + " " + "-"*10 + " " + "-"*20 + " " + "-"*10 + "  " + "-"*18)
for X in LOOKBACKS:
    chose_mom = runs[X]["chose_mom_series"]
    yest_chose_mom = chose_mom.shift(1, fill_value=True)
    yest_calm_long = calm_long.shift(1, fill_value=False)
    # Switch Mom30 → NIFTY: yesterday chose Mom30 (or wasn't in calm-long), today calm-long and chose NIFTY
    switch_to_nif = calm_long & yest_calm_long & yest_chose_mom & ~chose_mom
    switch_dates = idx[switch_to_nif.values]
    n_switches = len(switch_dates)
    if n_switches == 0:
        out(f"  X={X:<5} {'0':>10} {'—':>20} {'—':>10}  {'—':>18}")
        continue
    # For each switch date, look forward FORWARD_CHECK_DAYS and compare Mom30 vs NIFTY cum return
    hits = 0
    diffs = []
    for d in switch_dates:
        i = idx.get_loc(d)
        end_i = min(i + FORWARD_CHECK_DAYS, len(idx))
        if end_i - i < 5:
            continue
        period_mom = float((1 + ret_mom.iloc[i:end_i]).prod() - 1)
        period_nif = float((1 + ret_nif.iloc[i:end_i]).prod() - 1)
        diffs.append(period_nif - period_mom)
        if period_nif > period_mom:
            hits += 1
    hit_rate = hits / len(diffs) * 100 if diffs else 0
    mean_diff = np.mean(diffs) * 100 if diffs else 0
    out(f"  X={X:<5} {n_switches:>10d} {hits:>20d} {hit_rate:>9.1f}%  {mean_diff:+17.2f}pp")
out()

# ─── Per-day logs ───────────────────────────────────────────────────────────
for X in LOOKBACKS:
    log = pd.DataFrame({
        "long_state": long_mask,
        "v2_active": v2_active,
        "calm_long": calm_long,
        "chosen_asset": runs[X]["chosen"],
        "chose_mom": runs[X]["chose_mom_series"],
        "ret_mom": ret_mom,
        "ret_nif": ret_nif,
        "c1_pretax": c1_pretax,
        "variant_pretax": runs[X]["pretax"],
        "diff_vs_c1": runs[X]["pretax"] - c1_pretax,
    })
    log.to_csv(os.path.join(RESULTS_DIR, f"test_relative_momentum_X{X}.csv"))
out(f"  Per-day logs saved to {RESULTS_DIR}/test_relative_momentum_X<window>.csv")
out()

# ─── Plain-English verdict ──────────────────────────────────────────────────
out("=" * 130)
out("  PLAIN-ENGLISH VERDICT")
out("=" * 130)
out()
# Identify best variant
results = {X: L.metrics(runs[X]["posttax"]) for X in LOOKBACKS}
best_X = max(LOOKBACKS, key=lambda X: results[X]["sharpe"])
n_beat = sum(1 for X in LOOKBACKS
             if results[X]["cagr"] > c1_m["cagr"] and results[X]["sharpe"] > c1_m["sharpe"])
out(f"Best variant by post-tax Sharpe: X={best_X}d")
out(f"  CAGR {results[best_X]['cagr']*100:+.2f}% (Δ {(results[best_X]['cagr']-c1_m['cagr'])*100:+.2f}pp vs C1)")
out(f"  Sharpe {results[best_X]['sharpe']:.3f} (Δ {results[best_X]['sharpe']-c1_m['sharpe']:+.3f})")
out(f"  MaxDD {results[best_X]['max_dd']*100:+.2f}% (Δ {(results[best_X]['max_dd']-c1_m['max_dd'])*100:+.2f}pp)")
out()
out(f"  Windows beating C1 on BOTH CAGR and Sharpe: {n_beat} of {len(LOOKBACKS)}")
out()

# 2018 fix question
fix_2018 = {X: year_ret(runs[X]["posttax"], 2018) - year_ret(c1_posttax, 2018)
            for X in LOOKBACKS}
best_2018 = max(LOOKBACKS, key=lambda X: fix_2018[X])
out(f"2018 fix:")
for X in LOOKBACKS:
    out(f"  X={X}d  Δ {fix_2018[X]*100:+.2f}pp")
out()

# Other-year cost while fixing 2018
out(f"Trade-off check — if 2018 is fixed, what happens elsewhere?")
for X in LOOKBACKS:
    win_total = sum(max(year_ret(runs[X]["posttax"], y) - year_ret(c1_posttax, y), 0) for y in years)
    loss_total = sum(min(year_ret(runs[X]["posttax"], y) - year_ret(c1_posttax, y), 0) for y in years)
    out(f"  X={X}d  total wins: {win_total*100:+.2f}pp, total losses: {loss_total*100:+.2f}pp, "
        f"net {(win_total + loss_total)*100:+.2f}pp")
out()

with open(OUTPUT_PATH, "w") as f:
    f.write("\n".join(lines))
print(f"\nSaved to {OUTPUT_PATH}", file=sys.stderr)
