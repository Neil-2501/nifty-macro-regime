"""compare_v20_vs_nifty.py — clean Strategy v2.0 vs NIFTY 50 B&H comparison."""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd

import strategy as s
from strategy_lab import _load_data


def main():
    raw = _load_data()
    START, END = "2008-04-01", "2025-12-31"

    # Config 7 — v2.0 production
    combiner = s.make_combiner(rotate_stress=True, rotate_panic=False,
                                use_momentum_gold=True,
                                slow_stress_lock_days=5)
    strat = s.MacroStrategy(combiner, nifty_cost_bps=3, gold_cost_bps=5,
                             long_target="NIFTYMOM30", long_cost_bps=6,
                             enable_v2=True, v2_dd_threshold=0.15, v2_days=60)
    df = strat.run(raw).loc[START:END]

    # NIFTY 50 B&H — pretax and with 10% long-term tax
    nifty_close = raw["^NSEI"].loc[START:END]
    nifty_pretax = nifty_close.pct_change().fillna(0.0)
    nifty_posttax = s.apply_annual_tax(nifty_pretax, tax_rate=0.10)

    strat_r = df["strategy_return"]
    strat_pre = df["strategy_return_pretax"]

    m_strat = s.metrics(strat_r)
    m_strat_pre = s.metrics(strat_pre)
    m_nifty_pre = s.metrics(nifty_pretax)
    m_nifty = s.metrics(nifty_posttax)

    out = []
    def p(text=""): print(text); out.append(text)

    p("\n" + "=" * 130)
    p("  STRATEGY v2.0 (Config 7 = Mom30 + V2 + 5-day lock) vs NIFTY 50 B&H")
    p("  2008-04-01 → 2025-12-31  (17.75 years)")
    p("=" * 130)
    p()

    p("=" * 130)
    p("  HEADLINE METRICS")
    p("=" * 130)
    p(f"  {'':<22} {'POST-TAX':>32} | {'PRE-TAX':>32}")
    p(f"  {'Metric':<22} {'Strategy v2.0':>13} {'NIFTY B&H (LT)':>17} | "
      f"{'Strategy v2.0':>13} {'NIFTY B&H':>17}")
    p("  " + "-"*22 + " " + "-"*13 + " " + "-"*17 + " | " + "-"*13 + " " + "-"*17)
    p(f"  {'CAGR':<22} {m_strat['cagr']*100:>+12.2f}% {m_nifty['cagr']*100:>+16.2f}%  "
      f" {m_strat_pre['cagr']*100:>+12.2f}% {m_nifty_pre['cagr']*100:>+16.2f}%")
    p(f"  {'Sharpe':<22} {m_strat['sharpe']:>13.3f} {m_nifty['sharpe']:>17.3f}  "
      f" {m_strat_pre['sharpe']:>13.3f} {m_nifty_pre['sharpe']:>17.3f}")
    p(f"  {'Sortino':<22} {m_strat['sortino']:>13.3f} {m_nifty['sortino']:>17.3f}  "
      f" {m_strat_pre['sortino']:>13.3f} {m_nifty_pre['sortino']:>17.3f}")
    p(f"  {'Calmar':<22} {m_strat['calmar']:>13.2f} {m_nifty['calmar']:>17.2f}  "
      f" {m_strat_pre['calmar']:>13.2f} {m_nifty_pre['calmar']:>17.2f}")
    p(f"  {'Max drawdown':<22} {m_strat['max_dd']*100:>+12.2f}% {m_nifty['max_dd']*100:>+16.2f}%  "
      f" {m_strat_pre['max_dd']*100:>+12.2f}% {m_nifty_pre['max_dd']*100:>+16.2f}%")
    p(f"  {'Ann. vol':<22} {m_strat['vol']*100:>+12.2f}% {m_nifty['vol']*100:>+16.2f}%  "
      f" {m_strat_pre['vol']*100:>+12.2f}% {m_nifty_pre['vol']*100:>+16.2f}%")
    cum_strat = (1+strat_r).cumprod().iloc[-1]
    cum_nifty = (1+nifty_posttax).cumprod().iloc[-1]
    cum_strat_pre = (1+strat_pre).cumprod().iloc[-1]
    cum_nifty_pre = nifty_close.iloc[-1]/nifty_close.iloc[0]
    p(f"  {'Rs1 →':<22} Rs{cum_strat:>11.2f}  Rs{cum_nifty:>15.2f}   "
      f"Rs{cum_strat_pre:>11.2f}  Rs{cum_nifty_pre:>15.2f}")
    p(f"  {'Cumulative return':<22} {(cum_strat-1)*100:>+12.0f}% {(cum_nifty-1)*100:>+16.0f}%  "
      f" {(cum_strat_pre-1)*100:>+12.0f}% {(cum_nifty_pre-1)*100:>+16.0f}%")
    p()

    # Spread vs benchmark
    p("=" * 130)
    p("  STRATEGY ALPHA (post-tax)")
    p("=" * 130)
    p(f"  CAGR alpha:     {(m_strat['cagr'] - m_nifty['cagr'])*100:+.2f}pp/yr")
    p(f"  Sharpe alpha:   {m_strat['sharpe'] - m_nifty['sharpe']:+.3f}")
    p(f"  MaxDD alpha:    {(m_strat['max_dd'] - m_nifty['max_dd'])*100:+.2f}pp shallower")
    p(f"  Terminal alpha: Rs{cum_strat - cum_nifty:+.2f}  ({(cum_strat/cum_nifty-1)*100:+.1f}% multiplier)")
    p()

    # Year-by-year
    p("=" * 130)
    p("  YEAR-BY-YEAR")
    p("=" * 130)
    p(f"  {'Year':<6} {'Strategy v2.0':>14} {'NIFTY 50 B&H':>14} {'Δ vs NIFTY':>13}  Best")
    p("  " + "-"*6 + " " + "-"*14 + " " + "-"*14 + " " + "-"*13 + "  " + "-"*8)
    s_wins = 0; n_wins = 0
    for y in sorted(set(df.index.year)):
        sr = float((1 + strat_r[strat_r.index.year == y]).prod() - 1) * 100
        nr = float((1 + nifty_posttax[nifty_posttax.index.year == y]).prod() - 1) * 100
        diff = sr - nr
        winner = "Strategy" if sr > nr else "NIFTY"
        if sr > nr: s_wins += 1
        else: n_wins += 1
        p(f"  {y:<6} {sr:>+12.2f}% {nr:>+12.2f}% {diff:>+11.2f}pp  {winner}")
    p()
    p(f"  Win count: Strategy {s_wins}, NIFTY {n_wins}  ({s_wins}/{s_wins+n_wins} years)")
    p()

    # Crisis windows
    p("=" * 130)
    p("  CRISIS WINDOWS (post-tax cumulative returns)")
    p("=" * 130)
    crises = [
        ("GFC",            "2008-09-01", "2009-03-31"),
        ("Euro debt 2011", "2011-07-01", "2011-12-31"),
        ("Taper 2013",     "2013-05-01", "2013-09-30"),
        ("NBFC 2018",      "2018-09-01", "2019-02-28"),
        ("COVID 2020",     "2020-02-01", "2020-12-31"),
        ("2022 inflation", "2022-01-01", "2022-12-31"),
    ]
    p(f"  {'Crisis':<18} {'Window':<26} {'Strategy v2.0':>14} {'NIFTY B&H':>13} {'Δ':>10}")
    p("  " + "-"*18 + " " + "-"*26 + " " + "-"*14 + " " + "-"*13 + " " + "-"*10)
    for name, sd, ed in crises:
        s_ret = float((1 + strat_r.loc[sd:ed]).prod() - 1) * 100
        n_ret = float((1 + nifty_posttax.loc[sd:ed]).prod() - 1) * 100
        p(f"  {name:<18} {sd} to {ed}   {s_ret:>+12.2f}% {n_ret:>+11.2f}% {s_ret-n_ret:>+8.2f}pp")
    p()

    # Drawdown comparison
    p("=" * 130)
    p("  DRAWDOWN PROFILE")
    p("=" * 130)
    dd_s = ((1+strat_r).cumprod() / (1+strat_r).cumprod().cummax() - 1)
    dd_n = ((1+nifty_posttax).cumprod() / (1+nifty_posttax).cumprod().cummax() - 1)
    p(f"  Max drawdown:        Strategy {dd_s.min()*100:+.2f}%   NIFTY {dd_n.min()*100:+.2f}%")
    p(f"  Avg drawdown:        Strategy {dd_s.mean()*100:+.2f}%   NIFTY {dd_n.mean()*100:+.2f}%")
    p(f"  Days DD > -10%:      Strategy {((dd_s < -0.10) & (dd_s >= -0.20)).sum()}     NIFTY {((dd_n < -0.10) & (dd_n >= -0.20)).sum()}")
    p(f"  Days DD > -20%:      Strategy {((dd_s < -0.20) & (dd_s >= -0.30)).sum()}     NIFTY {((dd_n < -0.20) & (dd_n >= -0.30)).sum()}")
    p(f"  Days DD < -30%:      Strategy {(dd_s < -0.30).sum()}     NIFTY {(dd_n < -0.30).sum()}")
    p()

    # State breakdown
    p("=" * 130)
    p("  STRATEGY STATE BREAKDOWN (over 17.75 years = ~4475 trading days)")
    p("=" * 130)
    long_d = int((df["nifty_position"] == 1.0).sum())
    short_d = int((df["nifty_position"] == -1.0).sum())
    gold_d = int(((df["nifty_position"] == 0.0) & (df["gold_position"] == 1.0)).sum())
    flat_d = int(((df["nifty_position"] == 0.0) & (df["gold_position"] == 0.0)).sum())
    v2_d = int(df["v2_active"].sum())
    total = long_d + short_d + gold_d + flat_d
    p(f"  Long days:    {long_d:>5} ({long_d/total*100:>5.1f}%)  -- including {v2_d} V2-active days holding NIFTY 50")
    p(f"  Short days:   {short_d:>5} ({short_d/total*100:>5.1f}%)")
    p(f"  Gold days:    {gold_d:>5} ({gold_d/total*100:>5.1f}%)")
    p(f"  Flat (cash):  {flat_d:>5} ({flat_d/total*100:>5.1f}%)")
    p(f"  TOTAL:        {total:>5}")
    p()

    txt = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "results", "compare_v20_vs_nifty.txt")
    with open(txt, "w") as f:
        f.write("\n".join(out))
    print(f"\nSaved to {txt}", file=sys.stderr)


if __name__ == "__main__":
    main()
