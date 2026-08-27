"""Diagnose the -36% MaxDD in M_hard_rules (U500_hard_rules_buf45).
- Rebuild the winning variant's daily returns
- Find the peak-to-trough dates
- Show year-by-year attribution vs R1
- During the DD window: show what the market did, what nifty regime was, what
  basket names were held and their individual returns.
"""
import os, sys
import numpy as np
import pandas as pd

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, REPO_ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import warnings; warnings.filterwarnings('ignore')
import momentum_basket_bakeoff_v2 as v2
import defensive_sleeve_v6 as v6
import strategy as prod


def find_max_dd_window(ret_series):
    cum = (1 + ret_series).cumprod()
    running_max = cum.cummax()
    dd = cum / running_max - 1
    trough_date = dd.idxmin()
    peak_date = cum.loc[:trough_date].idxmax()
    max_dd = dd.min()
    # Recovery date = first day cum >= running_max at trough
    peak_val = cum.loc[peak_date]
    recovery_candidates = cum.loc[trough_date:][cum.loc[trough_date:] >= peak_val]
    recovery = recovery_candidates.index[0] if len(recovery_candidates) > 0 else None
    return peak_date, trough_date, recovery, max_dd


def year_attribution(ret_series):
    yr = ret_series.index.year
    return (1 + ret_series).groupby(yr).prod() - 1


def main():
    print("=" * 78)
    print("DIAGNOSTIC — where does the M_hard_rules -36% MaxDD come from?")
    print("=" * 78)

    print("\n[Loading data]", flush=True)
    raw, prices, quality, fund_wide, scored = v6.load_all_data()
    quality_scored = pd.read_parquet(os.path.join(REPO_ROOT, 'data', 'momentum_scores',
                                                    'quality_scored_universe.parquet'))
    quality_scored['rebalance_date'] = pd.to_datetime(quality_scored['rebalance_date'])

    print("\n[Running Config 7 native]", flush=True)
    cfg7_on      = v2.run_cfg7(raw)
    cfg7_no_gold = v2.run_cfg7(raw, rotate_stress=False, use_g10_gate=False, use_momentum_gold=False)

    print("[Building defensive basket]", flush=True)
    def_holdings, def_reb_dates = v6.compute_defensive_basket_holdings(
        quality, fund_wide, prices, raw['^NSEI'].copy())
    defensive_basket_ret, _ = v6.compute_daily_basket_returns(
        def_holdings, def_reb_dates, prices, cfg7_on.index)
    defensive_basket_ret = defensive_basket_ret.fillna(0)

    latch_id, day_in_latch, is_flat = v2.identify_latches(cfg7_on['nifty_position'])
    prices_wide = prices.pivot_table(index='Date', columns='symbol', values='close', aggfunc='last')
    prices_wide = prices_wide.reindex(cfg7_on.index).ffill()

    # Build R1 (defensive ON, Mom30 INDEX)
    r1_ret, _ = v2.apply_defensive_overlay(
        cfg7_no_gold['strategy_return'], defensive_basket_ret,
        latch_id, day_in_latch, is_flat, N=v2.DEFENSIVE_N, alloc=v2.DEFENSIVE_ALLOC)

    # Build M_hard_rules (U500_hard_rules_buf45 — best-OOS gated variant)
    print("[Building M_hard_rules basket]", flush=True)
    reb_dates = sorted(scored['rebalance_date'].unique())
    baskets = v2.select_quality_gated_momentum(
        scored, quality_scored, fund_wide, reb_dates,
        universe=500, gate_kind='hard_rules', buf=45, N=v2.N_HOLD)
    daily_basket_ret, turnover_by_reb = v2.compute_basket_daily_returns(baskets, prices_wide, cfg7_on.index)
    new_pretax, active_mask = v2.build_swap_pretax(
        cfg7_no_gold, raw, daily_basket_ret, turnover_by_reb, reb_dates,
        my_cost_bps_per_side=v2.BASKET_COST_BPS_PER_SIDE)
    new_ret_swap = v2.apply_annual_tax(new_pretax.fillna(0))
    m_ret, def_active = v2.apply_defensive_overlay(
        new_ret_swap, defensive_basket_ret, latch_id, day_in_latch, is_flat,
        N=v2.DEFENSIVE_N, alloc=v2.DEFENSIVE_ALLOC)

    END = pd.Timestamp('2026-05-11')
    r1 = r1_ret.loc[:END]
    m = m_ret.loc[:END]

    # ---- 1. Year-by-year attribution ----
    print("\n" + "=" * 78)
    print("YEAR-BY-YEAR RETURNS  (post-tax, net)")
    print("=" * 78)
    r1_yr = year_attribution(r1)
    m_yr = year_attribution(m)
    print(f"  {'year':6s} {'R1':>10s} {'M':>10s} {'Δ':>10s}")
    for y in r1_yr.index:
        print(f"  {y:>6d} {r1_yr[y]*100:>+9.2f}% {m_yr[y]*100:>+9.2f}% {(m_yr[y]-r1_yr[y])*100:>+9.2f}pp")

    # ---- 2. Max drawdown window ----
    print("\n" + "=" * 78)
    print("MAX-DRAWDOWN WINDOW — M_hard_rules (U500 hard_rules buf45)")
    print("=" * 78)
    peak_m, trough_m, recov_m, dd_m = find_max_dd_window(m)
    print(f"  Peak:     {peak_m.date()}  cum={((1+m.loc[:peak_m]).prod()):.3f}")
    print(f"  Trough:   {trough_m.date()}  cum={((1+m.loc[:trough_m]).prod()):.3f}")
    if recov_m is not None:
        print(f"  Recovery: {recov_m.date()}  ({(recov_m - trough_m).days} days to recover)")
    else:
        print(f"  Recovery: NOT YET RECOVERED (still under water on {END.date()})")
    print(f"  MaxDD:    {dd_m*100:+.2f}%")
    print(f"  Peak→trough days: {(trough_m - peak_m).days}")

    peak_r1, trough_r1, recov_r1, dd_r1 = find_max_dd_window(r1)
    print(f"\n  R1 comparison — Peak {peak_r1.date()} → Trough {trough_r1.date()}  MaxDD {dd_r1*100:+.2f}%")

    # ---- 3. What happened during the M-drawdown window ----
    print("\n" + "=" * 78)
    print(f"WHAT HAPPENED — {peak_m.date()} to {trough_m.date()}")
    print("=" * 78)

    nifty = raw['^NSEI'].reindex(cfg7_on.index).ffill()
    mom30 = raw['NIFTYMOM30'].reindex(cfg7_on.index).ffill()

    dd_slice = slice(peak_m, trough_m)
    nifty_ret_win  = (nifty.loc[trough_m] / nifty.loc[peak_m]) - 1
    mom30_ret_win  = (mom30.loc[trough_m] / mom30.loc[peak_m]) - 1
    basket_cum = (1 + daily_basket_ret.loc[dd_slice]).prod() - 1
    r1_cum     = (1 + r1.loc[dd_slice]).prod() - 1
    m_cum      = (1 + m.loc[dd_slice]).prod() - 1

    print(f"  During the M peak→trough window:")
    print(f"    NIFTY 50 index:       {nifty_ret_win*100:+.2f}%")
    print(f"    NIFTYMOM30 index:     {mom30_ret_win*100:+.2f}%")
    print(f"    My momentum basket:   {basket_cum*100:+.2f}%   ← the bull-lane asset for M")
    print(f"    R1 net return:        {r1_cum*100:+.2f}%")
    print(f"    M net return:         {m_cum*100:+.2f}%")

    # Fraction of days IN the DD window that were bull vs stress-flat
    pos_win = cfg7_on['nifty_position'].loc[dd_slice]
    print(f"\n  Regime days in this window (total {len(pos_win)} trading days):")
    print(f"    bull long (pos=1):    {(pos_win==1.0).sum():4d} days ({(pos_win==1.0).mean()*100:.1f}%)")
    print(f"    stress flat (pos=0):  {(pos_win==0.0).sum():4d} days ({(pos_win==0.0).mean()*100:.1f}%)")
    print(f"    panic short (pos=-1): {(pos_win==-1.0).sum():4d} days ({(pos_win==-1.0).mean()*100:.1f}%)")

    # Which rebalance basket was active during trough?
    reb_ts = [pd.Timestamp(x) for x in sorted(baskets.keys())]
    active_reb = max([rd for rd in reb_ts if rd <= trough_m], default=None)
    if active_reb is not None:
        held = list(baskets[active_reb].keys())
        print(f"\n  Basket in effect at trough ({trough_m.date()}) — from rebalance {active_reb.date()}:")
        print(f"    {held[:15]}")
        print(f"    ... and {len(held)-15} more" if len(held) > 15 else '')

        # Individual stock returns over the DD window
        stock_perf = []
        for s in held:
            if s in prices_wide.columns:
                p_start = prices_wide[s].loc[:peak_m].iloc[-1] if not prices_wide[s].loc[:peak_m].empty else np.nan
                p_end   = prices_wide[s].loc[:trough_m].iloc[-1] if not prices_wide[s].loc[:trough_m].empty else np.nan
                if pd.notna(p_start) and pd.notna(p_end) and p_start > 0:
                    stock_perf.append((s, (p_end / p_start) - 1))
        stock_perf.sort(key=lambda x: x[1])
        print(f"\n  Individual stock returns during {peak_m.date()} → {trough_m.date()}:")
        print(f"    WORST 5:")
        for s, r in stock_perf[:5]:
            print(f"      {s:14s} {r*100:>+8.2f}%")
        print(f"    BEST 5:")
        for s, r in stock_perf[-5:]:
            print(f"      {s:14s} {r*100:>+8.2f}%")
        print(f"    Basket-median stock:  {stock_perf[len(stock_perf)//2][1]*100:+.2f}%")
        print(f"    Basket-mean stock:    {np.mean([r for _, r in stock_perf])*100:+.2f}%")

    # ---- 4. Cost breakdown for M during that window ----
    print("\n" + "=" * 78)
    print("COST BREAKDOWN — did trading costs cause the DD?")
    print("=" * 78)
    # Approximate: sum absolute daily rebal-cost + entry/exit + tax during the window
    reb_costs_window = 0
    for rd, tvr in turnover_by_reb.items():
        if peak_m <= pd.Timestamp(rd) <= trough_m:
            reb_costs_window += 2 * tvr * (v2.BASKET_COST_BPS_PER_SIDE / 10000)
    # entry/exit — count active-mask edges
    edges = active_mask.diff().abs().fillna(0).astype(int)
    ent_exit_bps = int(edges.loc[dd_slice].sum()) * v2.BASKET_COST_BPS_PER_SIDE
    print(f"  Rebalance turnover costs during window: {reb_costs_window*100:+.3f}% (drag)")
    print(f"  Entry/exit events during window:        {int(edges.loc[dd_slice].sum())}  → {ent_exit_bps} bps total")
    print(f"  Compared to total DD:                   {dd_m*100:+.2f}%")
    print(f"  → Costs explain: {(reb_costs_window + ent_exit_bps/10000)/(-dd_m)*100:.1f}% of the drawdown")

    # ---- 5. Bull-day returns only, R1 vs M ----
    print("\n" + "=" * 78)
    print("BULL-DAY ONLY comparison (removes regime/panic contribution)")
    print("=" * 78)
    bull_mask = (cfg7_on['nifty_position'] == 1.0).loc[:END]
    bull_r1  = r1[bull_mask.values]
    bull_m   = m[bull_mask.values]
    for series, lbl in [(bull_r1, 'R1'), (bull_m, 'M_hard_rules')]:
        cum = (1 + series).cumprod()
        peak, trough, _, dd = find_max_dd_window(series)
        print(f"  {lbl:14s} bull-only: CAGR (annualized) {(1+series).prod()**(252/len(series))-1:.2%}  "
              f"AnnVol {series.std()*np.sqrt(252):.2%}  Sharpe {series.mean()*252/(series.std()*np.sqrt(252)):.2f}  "
              f"MaxDD {dd*100:+.2f}% ({peak.date()} → {trough.date()})")

    print(f"\nDone. Data → console only (no file output)")


if __name__ == '__main__':
    main()
