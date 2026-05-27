"""
diagnose_losing_years_v2.py — CORRECTED decomposition of the loss vs NIFTY B&H
in 2013, 2019, 2022, 2025.

Previous version's −110pp was a sum of window-level Mom30-vs-best-asset gaps —
a hindsight oracle metric, not a P&L cost. This version uses real strategy
P&L vs NIFTY B&H using a clean multiplicative decomposition by state.

For each year:
  gap = NIFTY B&H annual − Strategy annual    (the real loss to explain)
  decompose:
    LONG-day contribution  = strategy_cum_on_long_days  vs NIFTY_cum_on_long_days
    FLAT-day contribution  = strategy_cum_on_flat_days  vs NIFTY_cum_on_flat_days
    SHORT-day contribution = strategy_cum_on_short_days vs NIFTY_cum_on_short_days
    GOLD-day contribution  = strategy_cum_on_gold_days  vs NIFTY_cum_on_gold_days

  Each "contribution" tells us: had the strategy held NIFTY (instead of what
  it did) on those days, how much would it have gained/lost?

  Then split LONG-day contribution further:
    Asset cost  = strategy_cum_on_long  vs  Mom30_cum_on_long
                  (entry-lag — strategy missed Mom30 P&L on entry days)
    Mom30-vs-NIFTY cost = Mom30_cum_on_long vs NIFTY_cum_on_long
                  (the actual asset-choice cost)
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd

import strategy as s
from strategy_lab import _load_data


def run_v20(raw):
    combiner = s.make_combiner(rotate_stress=True, rotate_panic=False,
                                use_momentum_gold=True,
                                slow_stress_lock_days=5)
    strat = s.MacroStrategy(combiner, nifty_cost_bps=3, gold_cost_bps=5,
                             long_target="NIFTYMOM30", long_cost_bps=6,
                             enable_v2=True, v2_dd_threshold=0.15, v2_days=60)
    return strat.run(raw).loc["2008-04-01":"2025-12-31"]


def decompose_year(df, raw, year):
    yr = df[df.index.year == year]
    nif_r = raw["^NSEI"].pct_change().reindex(yr.index).fillna(0.0)
    mom_r = raw["NIFTYMOM30"].pct_change().reindex(yr.index).fillna(0.0)

    long_mask = (yr["nifty_position"] == 1.0)
    flat_mask = (yr["nifty_position"] == 0.0) & (yr["gold_position"] == 0.0)
    short_mask = (yr["nifty_position"] == -1.0)
    gold_mask = (yr["gold_position"] == 1.0)

    strat_pre = yr["strategy_return_pretax"]

    def cum(s_, mask): return float((1 + s_[mask]).prod() - 1) * 100

    out = {
        "year": year,
        "n_days": len(yr),
        "n_long":  int(long_mask.sum()),
        "n_flat":  int(flat_mask.sum()),
        "n_short": int(short_mask.sum()),
        "n_gold":  int(gold_mask.sum()),
        # Strategy P&L on each subset (compound)
        "strat_long":  cum(strat_pre, long_mask),
        "strat_flat":  cum(strat_pre, flat_mask),
        "strat_short": cum(strat_pre, short_mask),
        "strat_gold":  cum(strat_pre, gold_mask),
        # NIFTY return on those same calendar days
        "nif_long":  cum(nif_r, long_mask),
        "nif_flat":  cum(nif_r, flat_mask),
        "nif_short": cum(nif_r, short_mask),
        "nif_gold":  cum(nif_r, gold_mask),
        # Mom30 return on long days (to split asset vs entry-lag)
        "mom_long":  cum(mom_r, long_mask),
        # Full year
        "strat_year": cum(strat_pre, pd.Series(True, index=yr.index)),
        "nif_year":   cum(nif_r,    pd.Series(True, index=yr.index)),
        "mom_year":   cum(mom_r,    pd.Series(True, index=yr.index)),
    }
    return out


def main():
    raw = _load_data()
    print("Running L5 production ...", file=sys.stderr)
    df = run_v20(raw)

    out = []
    def p(text=""): print(text); out.append(text)

    p("\n" + "=" * 130)
    p("  CORRECTED DECOMPOSITION — what really drives the loss vs NIFTY B&H")
    p("  Years 2013, 2019, 2022, 2025 under L5 production (current v2.0)")
    p("=" * 130)
    p()
    p("  Framework: full-year P&L gap = (NIFTY B&H − strategy) pretax")
    p("             decomposed by state (LONG/FLAT/SHORT/GOLD)")
    p()
    p("  For each state:")
    p("    'Strategy P&L'         = compound of strategy daily returns on those days")
    p("    'NIFTY-on-those-days'  = compound of NIFTY daily returns on those days")
    p("    'Mom30-on-those-days'  = compound of Mom30 daily returns on those days")
    p("    'Gap (vs NIFTY)'       = strategy P&L − NIFTY-on-those-days")
    p()
    p("  Note: cumulative returns compound multiplicatively, so the year-level gap")
    p("  approximates the sum of subset gaps but isn't a perfect arithmetic sum.")
    p()

    summary = []
    for y in [2013, 2019, 2022, 2025]:
        d = decompose_year(df, raw, y)
        p("=" * 130)
        p(f"  {y} — actual loss = NIFTY {d['nif_year']:+.2f}% − Strategy {d['strat_year']:+.2f}% "
          f"= {d['nif_year']-d['strat_year']:+.2f}pp pretax loss vs NIFTY B&H")
        p("=" * 130)
        p()
        p(f"  Days: LONG={d['n_long']}  FLAT={d['n_flat']}  SHORT={d['n_short']}  GOLD={d['n_gold']}")
        p()
        p(f"  {'State':<7} {'Days':>5} {'Strategy P&L':>14} {'NIFTY-on-days':>15} {'Gap vs NIFTY':>14}  Interpretation")
        p("  " + "-"*7 + " " + "-"*5 + " " + "-"*14 + " " + "-"*15 + " " + "-"*14 + "  " + "-"*50)
        # LONG state
        gap_long = d['strat_long'] - d['nif_long']
        interp = "strategy underperformed (entry-lag + Mom30 vs NIFTY)" if gap_long < -0.5 else \
                 "strategy slightly outperformed" if gap_long > 0.5 else "approx matched"
        p(f"  {'LONG':<7} {d['n_long']:>5} {d['strat_long']:>+12.2f}% {d['nif_long']:>+13.2f}% {gap_long:>+12.2f}pp  {interp}")
        # FLAT state
        gap_flat = d['strat_flat'] - d['nif_flat']
        if d['nif_flat'] < -2:
            interp = "strategy correctly avoided NIFTY drop"
        elif d['nif_flat'] > 2:
            interp = "strategy MISSED NIFTY rally on flat days"
        else:
            interp = "neutral"
        p(f"  {'FLAT':<7} {d['n_flat']:>5} {d['strat_flat']:>+12.2f}% {d['nif_flat']:>+13.2f}% {gap_flat:>+12.2f}pp  {interp}")
        # SHORT state
        if d['n_short'] > 0:
            gap_short = d['strat_short'] - d['nif_short']
            interp = "short worked" if d['nif_short'] < 0 else "short got squeezed"
            p(f"  {'SHORT':<7} {d['n_short']:>5} {d['strat_short']:>+12.2f}% {d['nif_short']:>+13.2f}% {gap_short:>+12.2f}pp  {interp}")
        # GOLD state
        if d['n_gold'] > 0:
            gap_gold = d['strat_gold'] - d['nif_gold']
            p(f"  {'GOLD':<7} {d['n_gold']:>5} {d['strat_gold']:>+12.2f}% {d['nif_gold']:>+13.2f}% {gap_gold:>+12.2f}pp  gold rotation")
        p()

        # LONG day breakdown: asset vs entry-lag
        p("  LONG-day breakdown (where did the long-day cost come from?):")
        gap_asset = d['mom_long'] - d['nif_long']    # Mom30 vs NIFTY (the asset penalty)
        gap_entry_lag = d['strat_long'] - d['mom_long']  # strategy vs Mom30 on those days (entry-lag)
        p(f"    Mom30 on LONG days:   {d['mom_long']:+.2f}%   (vs NIFTY-on-LONG {d['nif_long']:+.2f}%)")
        p(f"    Strategy on LONG days:{d['strat_long']:+.2f}%   (what we actually got)")
        p(f"    → Asset cost (Mom30 vs NIFTY on those days): {gap_asset:+.2f}pp")
        p(f"    → Entry-lag cost (strategy vs Mom30 on those days): {gap_entry_lag:+.2f}pp")
        p(f"    → Total LONG-day gap vs NIFTY: {gap_asset + gap_entry_lag:+.2f}pp  (≈ {gap_long:+.2f}pp computed directly)")
        p()

        # Aggregate net
        p(f"  Net year gap = LONG ({gap_long:+.2f}pp) + FLAT ({gap_flat:+.2f}pp) + "
          f"others ≈ {d['nif_year']-d['strat_year']:+.2f}pp (actual)")
        p()

        summary.append((y, d['nif_year']-d['strat_year'], gap_long, gap_flat, gap_asset, gap_entry_lag))

    # Cross-year summary
    p("=" * 130)
    p("  CROSS-YEAR SUMMARY — REAL pp costs vs NIFTY B&H (pretax)")
    p("=" * 130)
    p(f"  {'Year':<6} {'Total gap':>11} {'LONG gap':>10} {'FLAT gap':>10}  || {'Asset (Mom30 v NIFTY)':>22} {'Entry-lag':>12}")
    p("  " + "-"*6 + " " + "-"*11 + " " + "-"*10 + " " + "-"*10 + "  -- " + "-"*22 + " " + "-"*12)
    for y, total, long_gap, flat_gap, asset, entry_lag in summary:
        p(f"  {y:<6} {total:>+9.2f}pp {long_gap:>+8.2f}pp {flat_gap:>+8.2f}pp     {asset:>+20.2f}pp {entry_lag:>+10.2f}pp")
    p()
    p("  How to read:")
    p("    Total gap   = NIFTY B&H − strategy (pretax). Negative on year strategy lost.")
    p("    LONG gap    = strategy P&L on LONG days − what NIFTY did on those days.")
    p("    FLAT gap    = strategy P&L on FLAT days − what NIFTY did on those days (positive = strategy")
    p("                  protected on a NIFTY-down day; negative = strategy missed a NIFTY-up day).")
    p("    Asset cost  = Mom30 return − NIFTY return on LONG days (the real Mom30 underperformance).")
    p("    Entry-lag   = strategy P&L − Mom30 P&L on LONG days. Captures days when strategy entered")
    p("                  LONG today but was FLAT yesterday (today's P&L uses yesterday's weight).")
    p()

    txt = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "results", "diagnose_losing_years_v2.txt")
    with open(txt, "w") as f:
        f.write("\n".join(out))
    print(f"\nSaved to {txt}", file=sys.stderr)


if __name__ == "__main__":
    main()
