"""
nifty_long_vs_nifty_bh.py — does v2.0 still beat NIFTY B&H if we swap
Mom30 → NIFTY 50 as the long-side asset?

Compares 3 series year-by-year:
  - v2.0 Mom30 (production)         : Config 7 production
  - v2.0 NIFTY 50 (long-side swap)  : Config 7 with long_target=^NSEI
  - NIFTY 50 B&H (10% LT tax)       : pure buy-and-hold

For the NIFTY-long-side variant, decompose the years it LOSES to NIFTY B&H
to show where the bleed comes from (FLAT-during-rally, costs, etc.).
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd

import strategy as s
from strategy_lab import _load_data


def run_v20(raw, long_target, long_cost_bps):
    combiner = s.make_combiner(rotate_stress=True, rotate_panic=False,
                                use_momentum_gold=True,
                                slow_stress_lock_days=5)
    strat = s.MacroStrategy(combiner, nifty_cost_bps=3, gold_cost_bps=5,
                             long_target=long_target, long_cost_bps=long_cost_bps,
                             enable_v2=True, v2_dd_threshold=0.15, v2_days=60)
    return strat.run(raw).loc["2008-04-01":"2025-12-31"]


def main():
    raw = _load_data()

    df_mom = run_v20(raw, "NIFTYMOM30", 6)
    df_nif = run_v20(raw, "^NSEI", 3)
    nifty_close = raw["^NSEI"].loc["2008-04-01":"2025-12-31"]
    nifty_pretax = nifty_close.pct_change().fillna(0.0)
    nifty_bh = s.apply_annual_tax(nifty_pretax, tax_rate=0.10)

    out = []
    def p(text=""): print(text); out.append(text)

    p("\n" + "=" * 130)
    p("  v2.0 with NIFTY-LONG-SIDE vs NIFTY 50 B&H — year-by-year wins/losses")
    p("=" * 130)
    p()

    # Headline summary
    m_mom = s.metrics(df_mom["strategy_return"])
    m_nif = s.metrics(df_nif["strategy_return"])
    m_bh = s.metrics(nifty_bh)
    p(f"  v2.0 Mom30 (PROD):    CAGR={m_mom['cagr']*100:+.2f}%, Sharpe={m_mom['sharpe']:.3f}, MaxDD={m_mom['max_dd']*100:.2f}%")
    p(f"  v2.0 NIFTY 50 long:   CAGR={m_nif['cagr']*100:+.2f}%, Sharpe={m_nif['sharpe']:.3f}, MaxDD={m_nif['max_dd']*100:.2f}%")
    p(f"  NIFTY 50 B&H (LT):    CAGR={m_bh['cagr']*100:+.2f}%, Sharpe={m_bh['sharpe']:.3f}, MaxDD={m_bh['max_dd']*100:.2f}%")
    p()

    # ====== Year-by-year comparison ======
    p("=" * 130)
    p("  YEAR-BY-YEAR — wins (W) and losses (L) vs NIFTY 50 B&H")
    p("=" * 130)
    p(f"  {'Year':<6} {'v2.0 Mom30':>11} {'vs BH':>8}  {'v2.0 NIFTY':>11} {'vs BH':>8}  {'NIFTY B&H':>10}")
    p("  " + "-"*6 + " " + "-"*11 + " " + "-"*8 + "  " + "-"*11 + " " + "-"*8 + "  " + "-"*10)
    mom_wins = 0; mom_losses = 0
    nif_wins = 0; nif_losses = 0; nif_ties = 0
    nif_loss_years = []
    for y in sorted(set(df_mom.index.year)):
        m_yr = float((1 + df_mom["strategy_return"][df_mom.index.year == y]).prod() - 1) * 100
        n_yr = float((1 + df_nif["strategy_return"][df_nif.index.year == y]).prod() - 1) * 100
        b_yr = float((1 + nifty_bh[nifty_bh.index.year == y]).prod() - 1) * 100
        m_vs_bh = m_yr - b_yr
        n_vs_bh = n_yr - b_yr
        m_tag = "W" if m_vs_bh > 0 else "L"
        if m_vs_bh > 0: mom_wins += 1
        else: mom_losses += 1
        if n_vs_bh > 0.05:
            n_tag = "W"; nif_wins += 1
        elif n_vs_bh < -0.05:
            n_tag = "L"; nif_losses += 1
            nif_loss_years.append((y, n_yr, b_yr, n_vs_bh))
        else:
            n_tag = "T"; nif_ties += 1
        p(f"  {y:<6} {m_yr:>+9.2f}% {m_vs_bh:>+6.1f}pp {m_tag:>1}  "
          f"{n_yr:>+9.2f}% {n_vs_bh:>+6.1f}pp {n_tag:>1}  {b_yr:>+8.2f}%")
    p()
    p(f"  v2.0 Mom30 (PROD):   {mom_wins} wins vs B&H,  {mom_losses} losses")
    p(f"  v2.0 NIFTY 50 long:  {nif_wins} wins vs B&H,  {nif_losses} losses,  {nif_ties} ties")
    p()

    # ====== For NIFTY-long-side losses, decompose the bleed ======
    p("=" * 130)
    p("  WHERE v2.0 NIFTY-LONG-SIDE LOSES TO NIFTY B&H")
    p("  (decomposing the years where the active strategy underperformed)")
    p("=" * 130)
    p()
    p("  For each loss year, decompose strategy P&L vs B&H by state:")
    p("    LONG-days: strategy held NIFTY 50 (same asset as B&H, just timing/days)")
    p("    FLAT-days: strategy was flat (cash yield); B&H was in NIFTY")
    p("    Other:    transaction costs, short days, gold days")
    p()

    for y, n_yr, b_yr, gap in nif_loss_years:
        yr_df = df_nif[df_nif.index.year == y]
        yr_nif = nifty_close[nifty_close.index.year == y].pct_change().fillna(0.0)
        yr_bh = nifty_bh[nifty_bh.index.year == y]

        long_mask = (yr_df["nifty_position"] == 1.0)
        flat_mask = (yr_df["nifty_position"] == 0.0) & (yr_df["gold_position"] == 0.0)
        short_mask = (yr_df["nifty_position"] == -1.0)
        gold_mask = (yr_df["gold_position"] == 1.0)

        # Strategy pretax on each state
        strat_pre = yr_df["strategy_return_pretax"]
        cum_long_strat  = float((1 + strat_pre[long_mask]).prod() - 1) * 100
        cum_flat_strat  = float((1 + strat_pre[flat_mask]).prod() - 1) * 100
        cum_short_strat = float((1 + strat_pre[short_mask]).prod() - 1) * 100 if short_mask.any() else 0.0
        cum_gold_strat  = float((1 + strat_pre[gold_mask]).prod() - 1) * 100 if gold_mask.any() else 0.0

        # NIFTY's actual return on each subset of days
        cum_long_nif  = float((1 + yr_nif[long_mask]).prod() - 1) * 100
        cum_flat_nif  = float((1 + yr_nif[flat_mask]).prod() - 1) * 100
        cum_short_nif = float((1 + yr_nif[short_mask]).prod() - 1) * 100 if short_mask.any() else 0.0
        cum_gold_nif  = float((1 + yr_nif[gold_mask]).prod() - 1) * 100 if gold_mask.any() else 0.0
        cum_full_nif  = float((1 + yr_nif).prod() - 1) * 100

        days_long = int(long_mask.sum())
        days_flat = int(flat_mask.sum())
        days_short = int(short_mask.sum())
        days_gold = int(gold_mask.sum())

        p(f"  ===== {y} =====")
        p(f"  v2.0 NIFTY-long-side post-tax: {n_yr:+.2f}%   NIFTY B&H post-tax: {b_yr:+.2f}%   Strategy lost: {gap:+.2f}pp")
        p(f"  Days: LONG={days_long}  FLAT={days_flat}  SHORT={days_short}  GOLD={days_gold}")
        p(f"  {'Subset':<10} {'Strategy P&L':>14} {'NIFTY on those days':>22} {'Opportunity':>14}")
        p(f"  {'-'*10} {'-'*14} {'-'*22} {'-'*14}")
        p(f"  {'LONG':<10} {cum_long_strat:>+12.2f}% {cum_long_nif:>+20.2f}% {(cum_long_strat - cum_long_nif):>+12.2f}pp")
        p(f"  {'FLAT':<10} {cum_flat_strat:>+12.2f}% {cum_flat_nif:>+20.2f}% {(cum_flat_strat - cum_flat_nif):>+12.2f}pp")
        if short_mask.any():
            p(f"  {'SHORT':<10} {cum_short_strat:>+12.2f}% {cum_short_nif:>+20.2f}% {(cum_short_strat - cum_short_nif):>+12.2f}pp")
        if gold_mask.any():
            p(f"  {'GOLD':<10} {cum_gold_strat:>+12.2f}% {cum_gold_nif:>+20.2f}% {(cum_gold_strat - cum_gold_nif):>+12.2f}pp")
        p(f"  {'FULL':<10} {n_yr:>+12.2f}% {cum_full_nif:>+20.2f}%  (NIFTY pretax full year)")
        p()
        # One-line takeaway
        if cum_flat_nif > 2:
            p(f"    → KEY: NIFTY rose +{cum_flat_nif:.2f}% on the {days_flat} days strategy was FLAT.")
            p(f"      Strategy earned ~{cum_flat_strat:.2f}% (cash yield only). Opportunity cost = -{cum_flat_nif:.2f}pp.")
        elif cum_flat_nif < -2:
            p(f"    → NIFTY fell {cum_flat_nif:.2f}% on the {days_flat} FLAT days — strategy correctly avoided it.")
            p(f"      But still lost overall because LONG days underperformed slightly.")
        p()

    # Save
    txt = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "results", "nifty_long_vs_nifty_bh.txt")
    with open(txt, "w") as f:
        f.write("\n".join(out))
    print(f"\nSaved to {txt}", file=sys.stderr)


if __name__ == "__main__":
    main()
