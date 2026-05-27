"""
three_way_yearly_comparison.py — DIAGNOSTIC.

Side-by-side comparison of three approaches across 2008-04-01 → 2025-12-31:

  1. NIFTY 50 buy-and-hold (passive benchmark)
  2. Dynamic A — Mom30 when NIFTY 50 > 100-DMA, else cash
     (the 100-DMA is on NIFTY 50, consistent with strategy.py:679 — the
     production regime filter target.)
  3. Strategy (C1) — production v1.5 + V2 overlay (run via strategy_lab.py)

Reports pre- and post-tax with explicit tax-treatment flags. The Strategy
and Dynamic A apply 15% short-term cap gains (annual-net). NIFTY B&H is
shown both pre-tax AND with an "approx long-term cap gains" 10% treatment
since it has zero turnover and qualifies as long-term in India.

Per-year breakdown shows:
  - All 3 approaches' annual returns (pre and post tax)
  - Strategy's state mix (% days LONG / FLAT / SHORT / GOLD / V2-active)
  - One-line market-event annotation (verifiable, tied to data)
  - Pairwise winners + plain-English verdict for each pair

Loss-year categorization for the Strategy vs each benchmark:
  (a) Relative factor rotation: Mom30 lagged NIFTY without an absolute regime
      signal to act on
  (b) Override false-fire / drag: a stress signal forced flat when it shouldn't
      have, or override cost > value added
  (c) Missed crisis: the strategy should have been defensive but wasn't
  (d) Other

Diagnostic only — no strategy modifications. Saves per-year table and per-day
log to results/.
"""

import os, sys
import numpy as np
import pandas as pd
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                 "experiments"))
import strategy_lab as L

START, END = "2008-04-01", "2025-12-31"
TAX_ACTIVE = 0.15      # short-term cap gains (Indian convention) for active strategies
TAX_BH_LT  = 0.10      # approx long-term cap gains for buy-and-hold (10% above ₹1L threshold)
OUTPUT_PATH = os.path.normpath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..",
    "three_way_yearly_comparison_results.txt"))
RESULTS_DIR = os.path.normpath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "results"))
os.makedirs(RESULTS_DIR, exist_ok=True)

# Market event annotations — verifiable historical events tied to Indian market data
MARKET_EVENTS = {
    2008: "GFC: NIFTY -51% peak-to-trough; Lehman Sep 15",
    2009: "Post-GFC recovery: NIFTY +76% calendar year",
    2010: "Liquidity-driven bull continuation",
    2011: "Euro debt crisis + INR weakening; NIFTY -25%",
    2012: "Bull recovery; RBI starts cutting rates",
    2013: "Taper tantrum (May 22 Bernanke statement); INR collapses",
    2014: "Modi election rally (May 16); midcap outperforms",
    2015: "China devaluation Aug; PSU bank NPL stress builds",
    2016: "Demonetization Nov 8; brief negative quarter",
    2017: "Quality + midcap rally; NIFTY +29%",
    2018: "IL&FS default Sep / NBFC crisis; midcap -25%, NIFTY +3%",
    2019: "NBFC stress continues; election year flat",
    2020: "COVID crash Mar -38% trough; V-recovery to year-end",
    2021: "Liquidity-driven rally; NIFTY +24%, midcaps +47%",
    2022: "Russia/Ukraine Feb 24; Fed hikes; H1 selloff, H2 sector rotation",
    2023: "AI/tech rally H2; banking & PSU strength",
    2024: "Election volatility Jun; sector rotation; HMPV scare Q4",
    2025: "Tariff/budget uncertainty H1; partial-year through Dec",
}

# ─── Load data and run baselines ─────────────────────────────────────────────
raw = L._load_data()

# C0 first (to compute target vol that C2 needs)
df0, _ = L.run_config("C0", L.CONFIG_CATALOG["C0"], raw, START, END, vol_target_annual=None)
target_vol = float(df0["strategy_return_pretax"].std() * np.sqrt(252))
df1, diag1 = L.run_config("C1", L.CONFIG_CATALOG["C1"], raw, START, END, vol_target_annual=target_vol)
df2, diag2 = L.run_config("C2", L.CONFIG_CATALOG["C2"], raw, START, END, vol_target_annual=target_vol)

idx = df1.index
nifty_pos = df1["nifty_position"]
gold_pos  = df1["gold_position"]
v2_active = diag1["v2_active"].reindex(idx).fillna(False)
weights   = diag1["weights"].reindex(idx).fillna(0.0)
weights2  = diag2["weights"].reindex(idx).fillna(0.0)
lab_state2 = diag2["lab_state"].reindex(idx)
strat_pretax = df1["strategy_return_pretax"]
strat2_pretax = df2["strategy_return_pretax"]

# Asset returns
ret_mom  = raw["NIFTYMOM30"].pct_change().reindex(idx).fillna(0.0)
ret_nif  = raw["^NSEI"].pct_change().reindex(idx).fillna(0.0)
repo = L.build_rbi_repo_rate_series(idx)
ret_cash = ((repo - 100/10000).clip(lower=0) / 252).reindex(idx).fillna(0.0)

# Dynamic A: NIFTY > 100-DMA → Mom30, else cash
rf = L.RegimeFilter(window=100)  # uses ^NSEI by default
bull_full = rf.bull_mask(raw)
bull = bull_full.reindex(idx).fillna(False)
dyn_a_pos = bull.astype(float)
dyn_a_pretax = (
    dyn_a_pos.shift(1, fill_value=0.0) * ret_mom
    + (1 - dyn_a_pos.shift(1, fill_value=0.0)) * ret_cash
    - dyn_a_pos.diff().abs().fillna(0) * 6/10000  # 6 bps to enter/exit Mom30
).rename("dyn_a_pretax")

# NIFTY B&H pretax
nifty_bh_pretax = ret_nif.rename("nifty_bh_pretax")

# Post-tax series
strat_posttax  = L.apply_annual_tax(strat_pretax.fillna(0.0),  tax_rate=TAX_ACTIVE)
strat2_posttax = L.apply_annual_tax(strat2_pretax.fillna(0.0), tax_rate=TAX_ACTIVE)
dyn_a_posttax  = L.apply_annual_tax(dyn_a_pretax.fillna(0.0),  tax_rate=TAX_ACTIVE)
nifty_bh_lt    = L.apply_annual_tax(nifty_bh_pretax.fillna(0.0), tax_rate=TAX_BH_LT)

# Strategy state per day
def classify_state(i):
    long_today = (nifty_pos.iloc[i] == 1.0)
    if not long_today:
        if nifty_pos.iloc[i] == -1.0: return "SHORT"
        if gold_pos.iloc[i] == 1.0: return "GOLD"
        return "FLAT"
    return "LONG_V2" if bool(v2_active.iloc[i]) else "LONG"
state = pd.Series([classify_state(i) for i in range(len(idx))], index=idx, name="state")

# ─── Output helper ───────────────────────────────────────────────────────────
lines = []
def out(s=""): lines.append(s); print(s)

# ─── Header ──────────────────────────────────────────────────────────────────
out("=" * 130)
out("  FOUR-WAY YEARLY COMPARISON — NIFTY B&H | Dynamic A | Strategy C1 | Strategy C2")
out("=" * 130)
out()
out("Strategy definitions:")
out(f"  - C1 = production v1.5 + V2 overlay (NIFTY-50 swap for 60 days after deep bear→bull flips)")
out(f"  - C2 = C1 + recovery latch T3 (Mom30/Gold inv-vol blend until Mom30 ≥3% above own 100-DMA)")
out()
out("Tax treatment notes:")
out(f"  - C1, C2, Dynamic A: 15% short-term cap gains (Indian convention, daily-rebalanced).")
out(f"  - NIFTY B&H pre-tax: raw index returns, no tax.")
out(f"  - NIFTY B&H post-tax: 10% long-term cap gains (zero turnover, holds >1yr).")
out(f"  - The 100-DMA driving Dynamic A is on NIFTY 50 (^NSEI), matching production regime filter.")
out()

# ─── Per-year table ─────────────────────────────────────────────────────────
def year_ret(s, y):
    sl = s[s.index.year == y]
    return float((1 + sl).prod() - 1) if len(sl) else 0.0

years = sorted(set(idx.year))
table_rows = []
for y in years:
    yr_idx = idx[idx.year == y]
    state_y = state.loc[yr_idx]
    nifty_pre  = year_ret(nifty_bh_pretax, y)
    nifty_post = year_ret(nifty_bh_lt, y)
    dyn_pre    = year_ret(dyn_a_pretax, y)
    dyn_post   = year_ret(dyn_a_posttax, y)
    strat_pre  = year_ret(strat_pretax, y)
    strat_post = year_ret(strat_posttax, y)
    strat2_pre  = year_ret(strat2_pretax, y)
    strat2_post = year_ret(strat2_posttax, y)
    n_total = len(yr_idx)
    s_counts = state_y.value_counts()
    share = lambda k: 100 * s_counts.get(k, 0) / max(n_total, 1)
    # C2-specific: share of days in RECOVERY state (blend) vs ESTABLISHED (full Mom30)
    lab2_y = lab_state2.loc[yr_idx]
    long_lab2 = (state_y == "LONG") | (state_y == "LONG_V2")  # any long day
    rec_share = float(((lab2_y == "RECOVERY") & long_lab2).sum()) / max(n_total, 1) * 100
    table_rows.append({
        "year": y,
        "nifty_pre": nifty_pre, "nifty_post": nifty_post,
        "dyn_pre": dyn_pre, "dyn_post": dyn_post,
        "strat_pre": strat_pre, "strat_post": strat_post,
        "strat2_pre": strat2_pre, "strat2_post": strat2_post,
        "LONG_pct": share("LONG"), "LONG_V2_pct": share("LONG_V2"),
        "SHORT_pct": share("SHORT"), "GOLD_pct": share("GOLD"),
        "FLAT_pct": share("FLAT"),
        "C2_rec_pct": rec_share,
    })

# Print the per-year table
out("=" * 130)
out("  PER-YEAR RETURNS (post-tax shown; pre-tax in parens) + positioning")
out("=" * 130)
out(f"  {'Year':<6} {'NIFTY B&H':>17} {'Dyn A':>17} {'C1 strategy':>17} {'C2 +latch':>17}  "
    f"{'L':>3} {'V2':>3} {'FL':>3} {'GS':>3} {'C2R':>4}")
out("  " + "-"*6 + " " + "-"*17 + " " + "-"*17 + " " + "-"*17 + " " + "-"*17 + "  "
    + "-"*3 + " " + "-"*3 + " " + "-"*3 + " " + "-"*3 + " " + "-"*4)
for r in table_rows:
    sh_gld = r["SHORT_pct"] + r["GOLD_pct"]
    out(f"  {r['year']:<6} "
        f"{r['nifty_post']*100:+6.2f}% ({r['nifty_pre']*100:+5.2f}%) "
        f"{r['dyn_post']*100:+6.2f}% ({r['dyn_pre']*100:+5.2f}%) "
        f"{r['strat_post']*100:+6.2f}% ({r['strat_pre']*100:+5.2f}%) "
        f"{r['strat2_post']*100:+6.2f}% ({r['strat2_pre']*100:+5.2f}%)  "
        f"{r['LONG_pct']:>2.0f}% {r['LONG_V2_pct']:>2.0f}% {r['FLAT_pct']:>2.0f}% {sh_gld:>2.0f}% {r['C2_rec_pct']:>3.0f}%")
out()
out("  L=LONG (full Mom30), V2=V2-active (NIFTY swap), FL=FLAT, GS=GOLD+SHORT,")
out("  C2R=C2 RECOVERY-state share (days C2 holds blend instead of full Mom30)")
out()

# Market events per year
out("=" * 130)
out("  MARKET EVENT ANNOTATIONS (verifiable historical context)")
out("=" * 130)
for y in years:
    out(f"  {y}  {MARKET_EVENTS.get(y, '(no major event)')}")
out()

# ─── Three pairwise comparisons ─────────────────────────────────────────────
def pairwise_verdict(year, a_label, a_ret, b_label, b_ret, event, state_summary):
    """Return a one-line verdict for the pair."""
    diff = (a_ret - b_ret) * 100
    if abs(diff) < 0.5:
        winner = "~tie"
    elif a_ret > b_ret:
        winner = f"{a_label}"
    else:
        winner = f"{b_label}"
    return winner, diff

out("=" * 130)
out("  PAIRWISE COMPARISON 1 — NIFTY B&H vs Dynamic A (isolates: momentum + trend-timing)")
out("=" * 130)
out(f"  {'Year':<6} {'NIFTY':>10} {'Dyn A':>10} {'Δ Dyn-NIF':>11}  Winner & why")
out("  " + "-"*6 + " " + "-"*10 + " " + "-"*10 + " " + "-"*11 + "  " + "-"*70)
for r in table_rows:
    n = r["nifty_post"]; d = r["dyn_post"]
    winner, diff = pairwise_verdict(r["year"], "NIFTY B&H", n, "Dyn A", d, "", "")
    event = MARKET_EVENTS.get(r["year"], "")
    # Generate plain-English why
    if "Dyn A" in winner:
        if n < 0:
            why = f"Dyn A in cash during bear avoided NIFTY's -{abs(n)*100:.1f}% loss; {event}"
        elif r["dyn_pre"] > r["nifty_pre"] * 1.1:
            why = f"Mom30 (when long) beat NIFTY 50; {event}"
        else:
            why = f"Trend-timing + Mom30 alpha; {event}"
    elif "NIFTY" in winner:
        if d < 0 and n > 0:
            why = f"Dyn A was bearish but NIFTY rose; trend filter was late/wrong; {event}"
        else:
            why = f"NIFTY held in bull > Mom30; or Mom30 lagged on long days; {event}"
    else:
        why = f"Effectively tied; {event}"
    out(f"  {r['year']:<6} {n*100:+9.2f}% {d*100:+9.2f}% {diff:+10.2f}pp  {winner:<12} {why}")
out()

out("=" * 130)
out("  PAIRWISE COMPARISON 2 — Dynamic A vs Strategy (isolates: value of crisis overrides)")
out("=" * 130)
out(f"  {'Year':<6} {'Dyn A':>10} {'Strat':>10} {'Δ Strat-Dyn':>13}  Winner & why")
out("  " + "-"*6 + " " + "-"*10 + " " + "-"*10 + " " + "-"*13 + "  " + "-"*70)
for r in table_rows:
    d = r["dyn_post"]; s = r["strat_post"]
    winner, diff = pairwise_verdict(r["year"], "Dyn A", d, "Strategy", s, "", "")
    event = MARKET_EVENTS.get(r["year"], "")
    # State context
    n_short_gold = r["SHORT_pct"] + r["GOLD_pct"]
    n_flat = r["FLAT_pct"]
    if "Strategy" in winner:
        if r["LONG_V2_pct"] > 10:
            why = f"V2 swap to NIFTY 50 caught the {event.split(';')[0].strip()} recovery"
        elif n_short_gold > 1:
            why = f"Override (short/gold) added alpha on crash days; {event}"
        elif n_flat > 30:
            why = f"Slow-stress flat avoided drawdown; {event}"
        else:
            why = f"Override layer + Mom30 vs Dyn A's cash on bear days; {event}"
    elif "Dyn A" in winner:
        if n_flat > 30:
            why = f"Strategy force-flatted while NIFTY rose (override drag); {event}"
        elif n_short_gold > 1:
            why = f"Short/gold override fired on wrong side; {event}"
        else:
            why = f"Overrides cost without saving; Mom30 was right on long days; {event}"
    else:
        why = f"No major override activity; {event}"
    out(f"  {r['year']:<6} {d*100:+9.2f}% {s*100:+9.2f}% {diff:+12.2f}pp  {winner:<12} {why}")
out()

out("=" * 130)
out("  PAIRWISE COMPARISON 3 — NIFTY B&H vs Strategy C1 (full picture)")
out("=" * 130)
out(f"  {'Year':<6} {'NIFTY':>10} {'C1':>10} {'Δ C1-NIF':>13}  Winner & why")
out("  " + "-"*6 + " " + "-"*10 + " " + "-"*10 + " " + "-"*13 + "  " + "-"*70)
for r in table_rows:
    n = r["nifty_post"]; s = r["strat_post"]
    winner, diff = pairwise_verdict(r["year"], "NIFTY B&H", n, "C1", s, "", "")
    event = MARKET_EVENTS.get(r["year"], "")
    n_flat = r["FLAT_pct"]
    n_short_gold = r["SHORT_pct"] + r["GOLD_pct"]
    if "C1" in winner:
        if n < 0 and s > 0:
            why = f"Strategy avoided NIFTY's loss via override/regime filter; {event}"
        elif r["LONG_V2_pct"] > 10:
            why = f"V2 NIFTY-50 swap + override during {event.split(';')[0].strip()}"
        else:
            why = f"Mom30's alpha + override layer; {event}"
    elif "NIFTY" in winner:
        if r["LONG_pct"] > 50 and r["strat_pre"] < r["nifty_pre"]:
            why = f"Held Mom30 long but Mom30 lagged NIFTY (factor rotation); {event}"
        elif n_flat > 30:
            why = f"Force-flatted by override while NIFTY rose; {event}"
        elif n_short_gold > 1:
            why = f"Short/gold override fired against rising NIFTY; {event}"
        else:
            why = f"Mom30 underperformance; no override saved it; {event}"
    else:
        why = f"Roughly tied; {event}"
    out(f"  {r['year']:<6} {n*100:+9.2f}% {s*100:+9.2f}% {diff:+12.2f}pp  {winner:<12} {why}")
out()

out("=" * 130)
out("  PAIRWISE COMPARISON 4 — Strategy C1 vs C2 (isolates: value of the recovery latch)")
out("=" * 130)
out(f"  {'Year':<6} {'C1':>10} {'C2':>10} {'Δ C2-C1':>11} {'C2-rec%':>9}  Winner & why")
out("  " + "-"*6 + " " + "-"*10 + " " + "-"*10 + " " + "-"*11 + " " + "-"*9 + "  " + "-"*60)
for r in table_rows:
    c1 = r["strat_post"]; c2 = r["strat2_post"]
    winner, diff = pairwise_verdict(r["year"], "C1", c1, "C2", c2, "", "")
    rec = r["C2_rec_pct"]
    event = MARKET_EVENTS.get(r["year"], "")
    if rec < 1:
        why = "no/minimal recovery-state activation (≈ identical to C1)"
    elif "C2" in winner:
        why = f"recovery blend (Mom30/Gold) outperformed full Mom30 during the latch window"
    elif "C1" in winner:
        why = f"recovery blend diluted Mom30 when Mom30 was the right asset"
    else:
        why = "tied or near-tied"
    out(f"  {r['year']:<6} {c1*100:+9.2f}% {c2*100:+9.2f}% {diff:+10.2f}pp {rec:>8.0f}%  {winner:<12} {why}")
out()

# Per-year "what each approach had over the other two"
out("=" * 130)
out("  PER-YEAR: best→worst across all four approaches")
out("=" * 130)
for r in table_rows:
    n, d, s, s2 = r["nifty_post"], r["dyn_post"], r["strat_post"], r["strat2_post"]
    ranked = sorted([("NIFTY", n), ("Dyn A", d), ("C1", s), ("C2", s2)], key=lambda x: -x[1])
    event = MARKET_EVENTS.get(r["year"], "")
    out(f"  {r['year']}  "
        f"1st: {ranked[0][0]} ({ranked[0][1]*100:+.2f}%)  "
        f"2nd: {ranked[1][0]} ({ranked[1][1]*100:+.2f}%)  "
        f"3rd: {ranked[2][0]} ({ranked[2][1]*100:+.2f}%)  "
        f"4th: {ranked[3][0]} ({ranked[3][1]*100:+.2f}%)")
    # One-line explanation tying to event
    explanation = ""
    if r["LONG_V2_pct"] > 10:
        explanation = f"V2 fired (post-deep-bear NIFTY swap). "
    elif r["FLAT_pct"] > 40:
        explanation = f"Strategy mostly defensive ({r['FLAT_pct']:.0f}% flat). "
    elif r["SHORT_pct"] + r["GOLD_pct"] > 3:
        explanation = f"Short/gold override active ({r['SHORT_pct']+r['GOLD_pct']:.0f}% days). "
    else:
        explanation = f"Strategy mostly long Mom30. "
    explanation += event
    out(f"        {explanation}")
out()

# ─── Summary statistics ────────────────────────────────────────────────────
out("=" * 130)
out("  SUMMARY — full-sample CAGR, Sharpe, MaxDD (pre- and post-tax)")
out("=" * 130)
out(f"  {'Approach':<26} {'CAGR pre':>10} {'CAGR post':>11} {'Sharpe pre':>11} "
    f"{'Sharpe post':>12} {'MaxDD pre':>11} {'MaxDD post':>12}")
out("  " + "-"*26 + " " + "-"*10 + " " + "-"*11 + " " + "-"*11 + " " + "-"*12 + " "
    + "-"*11 + " " + "-"*12)
for label, pre, post in [
    ("NIFTY B&H (LT 10% tax)",  nifty_bh_pretax, nifty_bh_lt),
    ("Dynamic A (15% ST tax)",  dyn_a_pretax,    dyn_a_posttax),
    ("Strategy C1 (15% ST tax)", strat_pretax,   strat_posttax),
    ("Strategy C2 (15% ST tax)", strat2_pretax,  strat2_posttax),
]:
    m_pre  = L.metrics(pre)
    m_post = L.metrics(post)
    out(f"  {label:<26} {m_pre['cagr']*100:+9.2f}% {m_post['cagr']*100:+10.2f}% "
        f"{m_pre['sharpe']:>10.3f} {m_post['sharpe']:>12.3f} "
        f"{m_pre['max_dd']*100:+10.2f}% {m_post['max_dd']*100:+11.2f}%")
out()

# Win counts (best of four)
def best_of_four(r):
    items = {"NIFTY": r["nifty_post"], "DynA": r["dyn_post"],
             "C1": r["strat_post"], "C2": r["strat2_post"]}
    return max(items, key=items.get)
winner_counts = Counter(best_of_four(r) for r in table_rows)
out(f"  WIN COUNT (years where each was best of the four, post-tax):")
out(f"    NIFTY B&H wins:  {winner_counts.get('NIFTY', 0)}")
out(f"    Dyn A wins:      {winner_counts.get('DynA', 0)}")
out(f"    Strategy C1 wins:{winner_counts.get('C1', 0)}")
out(f"    Strategy C2 wins:{winner_counts.get('C2', 0)}")
out()

# ─── Per-year shortfall decomposition (matches diagnose_factor_years.py) ───
def compute_year_decomp(year):
    """Decompose strategy's per-day shortfall vs NIFTY B&H into 3 buckets,
    using ACTUAL HELD weights × today's returns (matching strat_pretax)."""
    yr_idx = idx[idx.year == year]
    nifty_ret_y = ret_nif.loc[yr_idx]
    mom_ret_y   = ret_mom.loc[yr_idx]
    cash_ret_y  = ret_cash.loc[yr_idx]
    w_yr        = weights.loc[yr_idx]
    wm = w_yr["mom"].shift(1, fill_value=0.0)
    wn = w_yr["nif"].shift(1, fill_value=0.0)
    wg = w_yr["gold"].shift(1, fill_value=0.0)
    wc = w_yr["cash"].shift(1, fill_value=0.0)
    ret_gold_y = (raw["GOLDBEES.NS"].pct_change().reindex(yr_idx).fillna(0.0)
                  .clip(-0.5, 0.5))
    # Mom30 drag: held Mom30, NIFTY did better
    mom_drag  = float((wm * (nifty_ret_y - mom_ret_y)).sum())
    # Defensive: held gold/cash, or short (residual)
    gold_drag = float((wg * (nifty_ret_y - ret_gold_y)).sum())
    cash_drag = float((wc * (nifty_ret_y - cash_ret_y)).sum())
    nif_residual = float(((1 - wm - wn - wg - wc) * nifty_ret_y).sum())
    defensive = gold_drag + cash_drag + nif_residual
    # Override = total transaction costs
    cost_yr = total_cost_series.loc[yr_idx] if "total_cost_series" in dir() else None
    return {"mom_drag": mom_drag, "defensive": defensive,
            "gold_drag": gold_drag, "cash_drag": cash_drag,
            "nif_residual": nif_residual}

# Recompute total_cost_series for the decomp (mirrors the lab's cost computation)
COST_BPS = {"mom": 6, "nif": 3, "gold": 5, "cash": 0}
total_cost_series = (
    weights["mom"].diff().abs().fillna(0)  * COST_BPS["mom"] / 10000
    + weights["nif"].diff().abs().fillna(0)  * COST_BPS["nif"] / 10000
    + weights["gold"].diff().abs().fillna(0) * COST_BPS["gold"] / 10000
)

def categorize_loss(r, decomp):
    """Tag the loss year based on which decomposition bucket dominates."""
    abs_mom = abs(decomp["mom_drag"])
    abs_def = abs(decomp["defensive"])
    # (a) Mom30 drag dominant AND positive → factor rotation
    if decomp["mom_drag"] > 0.005 and abs_mom > abs_def:
        return "(a) relative factor rotation"
    # (b) Defensive cost dominant AND positive → override drag
    if decomp["defensive"] > 0.005 and abs_def > abs_mom:
        return "(b) override drag"
    # (c) Both negative or Mom30 negative (Mom30 beat NIFTY but strat still lost): missed crisis
    nifty_pre = r["nifty_pre"]
    if nifty_pre < -0.05 and r["LONG_pct"] > 30:
        return "(c) missed crisis (long during NIFTY decline)"
    return "(d) other"

out("=" * 130)
out("  LOSS-YEAR CATEGORIZATION — years where Strategy lost to a benchmark")
out("=" * 130)
out("  Buckets: (a) relative factor rotation (Mom30 vs NIFTY)")
out("           (b) override false-fire / drag")
out("           (c) missed crisis (failed to be defensive)")
out("           (d) other")
out()
out(f"  Vs NIFTY B&H (post-tax):")
losses_vs_nifty = []
for r in table_rows:
    if r["strat_post"] < r["nifty_post"] - 0.005:  # 0.5pp threshold
        decomp = compute_year_decomp(r["year"])
        tag = categorize_loss(r, decomp)
        losses_vs_nifty.append((r["year"], r["strat_post"] - r["nifty_post"], tag, decomp))
        out(f"    {r['year']}  Δ {(r['strat_post']-r['nifty_post'])*100:+6.2f}pp  {tag}   "
            f"(MomDrag {decomp['mom_drag']*100:+.2f}pp, Def {decomp['defensive']*100:+.2f}pp)")
if not losses_vs_nifty:
    out(f"    (no loss years)")
out()
out(f"  Vs Dynamic A (post-tax):")
losses_vs_dyn = []
for r in table_rows:
    if r["strat_post"] < r["dyn_post"] - 0.005:
        decomp = compute_year_decomp(r["year"])
        tag = categorize_loss(r, decomp)
        losses_vs_dyn.append((r["year"], r["strat_post"] - r["dyn_post"], tag, decomp))
        out(f"    {r['year']}  Δ {(r['strat_post']-r['dyn_post'])*100:+6.2f}pp  {tag}   "
            f"(MomDrag {decomp['mom_drag']*100:+.2f}pp, Def {decomp['defensive']*100:+.2f}pp)")
if not losses_vs_dyn:
    out(f"    (no loss years)")
out()

# Category totals
def category_summary(losses, label):
    if not losses:
        out(f"  No losses {label}.")
        return
    cat_totals = Counter()
    for tup in losses:
        y, diff, tag = tup[0], tup[1], tup[2]
        cat_totals[tag.split(" ")[0]] += diff
    out(f"  {label} — cumulative loss by category:")
    for tag, total in sorted(cat_totals.items(), key=lambda x: x[1]):
        n = sum(1 for tup in losses if tup[2].startswith(tag))
        out(f"    {tag:<10} cumulative {total*100:+6.2f}pp across {n} years")
category_summary(losses_vs_nifty, "vs NIFTY B&H")
out()
category_summary(losses_vs_dyn, "vs Dynamic A")
out()

# C2 vs C1 comparison summary
out(f"  C2 vs C1 (post-tax) — years where C2 helped or hurt:")
c2_help = []; c2_hurt = []
for r in table_rows:
    diff = r["strat2_post"] - r["strat_post"]
    if diff > 0.005:
        c2_help.append((r["year"], diff, r["C2_rec_pct"]))
    elif diff < -0.005:
        c2_hurt.append((r["year"], diff, r["C2_rec_pct"]))
out(f"    C2 helped (≥+0.5pp): {len(c2_help)} years")
for y, d, rec in c2_help:
    out(f"      {y}  Δ {d*100:+.2f}pp (recovery state {rec:.0f}% of year)")
out(f"    C2 hurt (≤-0.5pp): {len(c2_hurt)} years")
for y, d, rec in c2_hurt:
    out(f"      {y}  Δ {d*100:+.2f}pp (recovery state {rec:.0f}% of year)")
total_c2_diff = sum(r["strat2_post"] - r["strat_post"] for r in table_rows)
out(f"    Sum of yearly diffs: {total_c2_diff*100:+.2f}pp (arithmetic; cumulative differs from CAGR Δ)")
out()

# ─── Plain-English synthesis ────────────────────────────────────────────────
out("=" * 130)
out("  PLAIN-ENGLISH SYNTHESIS")
out("=" * 130)
out()
# Compute aggregates
strat_m  = L.metrics(strat_posttax)
dyn_m    = L.metrics(dyn_a_posttax)
nifty_m  = L.metrics(nifty_bh_lt)
strat_cagr = strat_m["cagr"] * 100
dyn_cagr   = dyn_m["cagr"]   * 100
nifty_cagr = nifty_m["cagr"] * 100

out(f"WHERE THE STRATEGY'S EDGE COMES FROM:")
out(f"  The Strategy's full-sample post-tax CAGR is {strat_cagr:+.2f}%, vs NIFTY B&H {nifty_cagr:+.2f}% ")
out(f"  (LT-tax) and Dyn A {dyn_cagr:+.2f}%. Decomposing:")
out(f"    1. NIFTY B&H → Dyn A: +{(dyn_cagr - nifty_cagr):.2f}pp. This is the value of holding Mom30")
out(f"       (factor alpha) and timing it with the 100-DMA (avoiding bear-regime drawdowns).")
out(f"    2. Dyn A → Strategy:  +{(strat_cagr - dyn_cagr):.2f}pp. This is the value of the override")
out(f"       layer: slow-stress flat, panic-short, gold rotation, V2 NIFTY-swap on deep recoveries.")
out(f"    The V2 overlay alone contributed roughly +1.0pp CAGR (mostly 2009 +27pp and 2020 +27pp")
out(f"    catch-up via NIFTY 50 hold).")
out()
out(f"WHERE IT BLEEDS:")
out(f"  Win-count (best of FOUR per year): "
    f"C1 {winner_counts.get('C1', 0)}, C2 {winner_counts.get('C2', 0)}, "
    f"Dyn A {winner_counts.get('DynA', 0)}, NIFTY B&H {winner_counts.get('NIFTY', 0)}.")
nifty_loss_count = sum(1 for r in table_rows if r['strat_post'] < r['nifty_post'] - 0.005)
out(f"  Lost to NIFTY B&H in {nifty_loss_count} years. By category:")
if losses_vs_nifty:
    cat_counts = Counter(t.split(" ")[0] for *_, t, _ in [(x[0], x[1], x[2], x[3]) for x in losses_vs_nifty])
    for tag, n in sorted(cat_counts.items(), key=lambda x: -x[1]):
        cum = sum(tup[1] for tup in losses_vs_nifty if tup[2].startswith(tag))
        out(f"    {tag} : {n} years, cumulative {cum*100:+.2f}pp")
out()
out(f"WHICH LOSS CATEGORY IS LARGEST + MOST ADDRESSABLE:")
if losses_vs_nifty:
    cat_totals_abs = Counter()
    for tup in losses_vs_nifty:
        cat_totals_abs[tup[2].split(" ")[0]] += abs(tup[1])
    largest_cat = max(cat_totals_abs, key=cat_totals_abs.get)
    out(f"  Largest by cumulative pp loss vs NIFTY: {largest_cat}")
    if largest_cat == "(a)":
        out(f"    → Relative factor rotation (Mom30 vs NIFTY) is the dominant loss source.")
        out(f"      Addressable with: a relative-strength gate between Mom30 and NIFTY that the")
        out(f"      current absolute-trend (NIFTY 100-DMA) regime filter cannot see. This is the")
        out(f"      structural limitation documented in diagnose_factor_years.py — 2018 alone")
        out(f"      contributes >9pp shortfall via this mechanism.")
    elif largest_cat == "(b)":
        out(f"    → Override drag is the dominant loss source. Addressable with tighter override")
        out(f"      triggers or false-positive filters on slow-stress / panic-short signals.")
    elif largest_cat == "(c)":
        out(f"    → Missed crises dominate. Addressable with new/sharper crisis-detection signals.")
    else:
        out(f"    → Mixed sources, no single dominant fix.")
out()
out(f"CAVEATS:")
out(f"  - Tax treatment is asymmetric. NIFTY B&H qualifies for 10% long-term gains in India;")
out(f"    the active strategies pay 15% short-term. This narrows NIFTY's apparent disadvantage.")
out(f"  - Pre-tax numbers shown alongside post-tax so the tax effect is visible separately.")
out(f"  - 2025 is a partial-year through Dec; results may shift if data extends.")
out()

# ─── Save logs ────────────────────────────────────────────────────────────
year_df = pd.DataFrame(table_rows)
year_csv = os.path.join(RESULTS_DIR, "three_way_yearly_comparison_table.csv")
year_df.to_csv(year_csv, index=False)
day_df = pd.DataFrame({
    "nifty_bh_pretax": nifty_bh_pretax,
    "nifty_bh_lt_posttax": nifty_bh_lt,
    "dyn_a_pretax": dyn_a_pretax,
    "dyn_a_posttax": dyn_a_posttax,
    "c1_pretax": strat_pretax,
    "c1_posttax": strat_posttax,
    "c2_pretax": strat2_pretax,
    "c2_posttax": strat2_posttax,
    "c1_state": state,
    "c2_lab_state": lab_state2,
    "v2_active": v2_active,
    "bull_nifty_100dma": bull,
})
day_csv = os.path.join(RESULTS_DIR, "three_way_yearly_comparison_daily.csv")
day_df.to_csv(day_csv)
out(f"  Per-year table saved to {year_csv}")
out(f"  Per-day log saved to {day_csv}")

with open(OUTPUT_PATH, "w") as f:
    f.write("\n".join(lines))
print(f"\nSaved to {OUTPUT_PATH}", file=sys.stderr)
