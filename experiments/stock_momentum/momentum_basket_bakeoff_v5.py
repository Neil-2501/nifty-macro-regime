"""Momentum-basket bake-off V5 — vol-cap sweep.

V4 finding: vol_cap=40% cut MaxDD by 5.5pp but hurt FULL CAGR by 2.5pp
(vol cap too strict in early years when high-vol names ripped).

V5 sweeps vol_cap ∈ {30, 40, 50, 60, no_cap} with everything else fixed at
V4-variant-C (best OOS Sharpe):
  U200 @ 15bps, buffer=45, N=30, hard_rules gate, pledging filter,
  Novy-Marx combined score (λ=0.3), equal-weight, no persistence gate.

Answers: is there a vol-cap sweet spot that keeps most of the DD win
without giving up CAGR?
"""
from __future__ import annotations

import os
import sys
import warnings

import numpy as np
import pandas as pd

warnings.filterwarnings('ignore')

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, REPO_ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import backtest_defensive_rotation as brd
import defensive_sleeve_v6 as v6
import momentum_basket_bakeoff_v4 as v4    # reuse all helpers
import strategy as prod

OUT_DIR = os.path.join(REPO_ROOT, "data", "momentum_basket_bakeoff_v5")
os.makedirs(OUT_DIR, exist_ok=True)

END_FULL  = pd.Timestamp('2026-05-11')
IS_END    = pd.Timestamp('2016-12-31')
OOS_START = pd.Timestamp('2017-01-01')


def select_basket_with_vol_cap(scored, fund_wide, quality_by_rd, prices, nifty_close,
                                  rebalance_dates, vol_cap: float | None,
                                  beta_vol_cache):
    """Copy of v4.select_basket, but with vol_cap as a runtime param.
    vol_cap=None → no vol filter.
    Uses pledging=True, use_novy_marx=True (fixed to V4 variant C setup).
    """
    fund_by_fy = {int(fy): grp.set_index('symbol') for fy, grp in fund_wide.groupby('fiscal_year')}
    baskets = {}
    prev_holdings = []
    for rd in rebalance_dates:
        rd_ts = pd.Timestamp(rd)
        sub = scored[scored['rebalance_date'] == rd_ts].copy()
        sub = sub[sub['universe_rank_turnover'] <= v4.UNIVERSE]
        sub = sub[~sub['symbol'].map(v4._is_etf)]
        sub['hard_ok'] = [v4.passes_hard_rules(s, rd_ts, fund_by_fy) for s in sub['symbol']]
        sub = sub[sub['hard_ok']].reset_index(drop=True)

        # Pledging filter (always on for V5)
        sub['pledge_ok'] = [v4.get_pledging_ok(s, rd_ts, quality_by_rd) for s in sub['symbol']]
        sub = sub[sub['pledge_ok']].reset_index(drop=True)

        # Vol cap (only if specified)
        if vol_cap is not None:
            vol_ok = []
            for s in sub['symbol']:
                key = (s, rd_ts)
                if key not in beta_vol_cache:
                    b, v = brd.compute_beta_vol(prices, s, rd_ts, nifty_close)
                    beta_vol_cache[key] = (b, v)
                b, v = beta_vol_cache[key]
                vol_ok.append(v is not None and v <= vol_cap)
            sub['vol_ok'] = vol_ok
            sub = sub[sub['vol_ok']].reset_index(drop=True)

        # Novy-Marx ranking (always on for V5)
        sub['z_mom'] = (sub['composite_risk_adj'] - sub['composite_risk_adj'].mean()) / \
                          (sub['composite_risk_adj'].std() or 1)
        sub['F_score_pt'] = [v4.get_fscore(s, rd_ts, quality_by_rd) for s in sub['symbol']]
        fs_present = sub['F_score_pt'].dropna()
        fallback = fs_present.quantile(0.25) if len(fs_present) >= 5 else 3.0
        sub['F_score_use'] = sub['F_score_pt'].fillna(fallback)
        sub['z_qual'] = (sub['F_score_use'] - sub['F_score_use'].mean()) / \
                          (sub['F_score_use'].std() or 1)
        sub['combined_z'] = 0.7 * sub['z_mom'] + 0.3 * sub['z_qual']
        sub = sub.sort_values('combined_z', ascending=False).reset_index(drop=True)

        # Buffered incumbent retention
        if len(sub) < v4.N_HOLD:
            picks = sub['symbol'].tolist()
        else:
            elig_set = set(sub['symbol'].tolist())
            buffer_set = set(sub.head(v4.BUF)['symbol'].tolist())
            top_N_names = sub.head(v4.N_HOLD)['symbol'].tolist()
            held = [s for s in prev_holdings if s in elig_set and s in buffer_set]
            new_names = [s for s in top_N_names if s not in held]
            picks = (held + new_names)[:v4.N_HOLD]

        baskets[rd_ts] = {s: 1.0 / len(picks) for s in picks}
        prev_holdings = picks

    return baskets


def perf(r):
    r = pd.Series(r).dropna()
    if r.empty: return {'CAGR': np.nan, 'AnnVol': np.nan, 'Sharpe': np.nan, 'MaxDD': np.nan}
    cum = (1 + r).cumprod()
    days = len(r); years = days / 252
    return {'CAGR': cum.iloc[-1] ** (1/years) - 1 if years > 0 else np.nan,
              'AnnVol': r.std() * np.sqrt(252),
              'Sharpe': (r.mean() * 252) / (r.std() * np.sqrt(252)) if r.std() > 0 else np.nan,
              'MaxDD': (cum / cum.cummax() - 1).min()}


def main():
    print("=" * 78)
    print("V5 — vol-cap sweep (30 / 40 / 50 / 60 / no_cap)")
    print("Fixed: U200 @ 15bps, buf=45, N=30, hard_rules, pledging, Novy-Marx (λ=0.3)")
    print("=" * 78)

    print("\n[Loading data]", flush=True)
    raw, prices, quality, fund_wide, scored = v6.load_all_data()
    quality_scored = pd.read_parquet(os.path.join(REPO_ROOT, 'data', 'momentum_scores',
                                                    'quality_scored_universe.parquet'))
    quality_scored['rebalance_date'] = pd.to_datetime(quality_scored['rebalance_date'])
    quality_by_rd = v4.build_quality_lookup(quality_scored)

    print("[Config 7 native]", flush=True)
    cfg7_on      = v4.run_cfg7(raw)
    cfg7_no_gold = v4.run_cfg7(raw, rotate_stress=False, use_g10_gate=False, use_momentum_gold=False)
    m_baseline = perf(cfg7_on.loc[:END_FULL]['strategy_return'])
    print(f"  Config 7: {m_baseline['CAGR']*100:.4f}% / Sh {m_baseline['Sharpe']:.4f}")

    print("[Defensive basket]", flush=True)
    def_holdings, def_reb_dates = v6.compute_defensive_basket_holdings(
        quality, fund_wide, prices, raw['^NSEI'].copy())
    def_ret, _ = v6.compute_daily_basket_returns(def_holdings, def_reb_dates, prices, cfg7_on.index)
    def_ret = def_ret.fillna(0)
    latch_id, day_in_latch, is_flat = v4.identify_latches(cfg7_on['nifty_position'])
    prices_wide = prices.pivot_table(index='Date', columns='symbol', values='close', aggfunc='last')
    prices_wide = prices_wide.reindex(cfg7_on.index).ffill()
    nifty_close = raw['^NSEI'].copy()

    # Identity checks
    print("\n[Identity checks]")
    ic2_ret = v4.apply_defensive_overlay(cfg7_no_gold['strategy_return'], def_ret,
                                            latch_id, day_in_latch, is_flat)
    ic2 = perf(ic2_ret.loc[:END_FULL])
    print(f"  IC2 (defensive ON, R1): {ic2['CAGR']*100:.4f}% CAGR / Sh {ic2['Sharpe']:.4f} / "
          f"MaxDD {ic2['MaxDD']*100:.2f}%  (target V7 16.85%)")
    mom30_ret_series = raw['NIFTYMOM30'].reindex(cfg7_on.index).pct_change().fillna(0)
    ic3_pretax, _ = v4.build_swap_pretax(cfg7_no_gold, raw, mom30_ret_series, {}, [], v4.MOM30_COST_BPS)
    ic3 = perf(v4.apply_annual_tax(ic3_pretax.fillna(0)).loc[:END_FULL])
    m_ng = perf(cfg7_no_gold.loc[:END_FULL]['strategy_return'])
    diff3 = (ic3['CAGR'] - m_ng['CAGR']) * 100
    print(f"  IC3 (swap identity): {ic3['CAGR']*100:.4f}% vs cfg7_no_gold {m_ng['CAGR']*100:.4f}%  Δ {diff3:+.6f}pp")
    if abs(diff3) > 1e-3:
        print("  ⚠ IC3 drift — check")
        return
    print("  ✓ IC OK")

    # Sweep
    reb_dates = sorted(scored['rebalance_date'].unique())
    beta_vol_cache = {}
    vol_caps = [0.30, 0.40, 0.50, 0.60, None]     # None = no cap
    labels   = ['vc30', 'vc40', 'vc50', 'vc60', 'no_cap']

    results = {'R1': ic2_ret.loc[:END_FULL]}
    rows = []

    for vc, lbl in zip(vol_caps, labels):
        print(f"\n[Building {lbl} (vol_cap={vc})]", flush=True)
        baskets = select_basket_with_vol_cap(
            scored, fund_wide, quality_by_rd, prices, nifty_close,
            reb_dates, vol_cap=vc, beta_vol_cache=beta_vol_cache)
        n_names = [len(v) for v in baskets.values()]
        print(f"  Median basket size: {int(np.median(n_names))}  (target {v4.N_HOLD})")

        daily_ret, tvr = v4.compute_basket_daily_returns(baskets, prices_wide, cfg7_on.index)
        new_pretax, _ = v4.build_swap_pretax(cfg7_no_gold, raw, daily_ret, tvr, reb_dates, v4.BASKET_COST_BPS)
        new_ret = v4.apply_annual_tax(new_pretax.fillna(0))
        final_ret = v4.apply_defensive_overlay(new_ret, def_ret, latch_id, day_in_latch, is_flat)
        results[lbl] = final_ret.loc[:END_FULL]

        m_full = perf(final_ret.loc[:END_FULL])
        oos = perf(final_ret.loc[OOS_START:END_FULL])
        rows.append({'label': lbl, 'vol_cap': vc,
                     'FULL_CAGR': m_full['CAGR'], 'FULL_Sh': m_full['Sharpe'], 'FULL_DD': m_full['MaxDD'],
                     'OOS_CAGR': oos['CAGR'], 'OOS_Sh': oos['Sharpe'], 'OOS_DD': oos['MaxDD']})

    df = pd.DataFrame(rows)
    df.to_csv(os.path.join(OUT_DIR, 'sweep.csv'), index=False)

    # Report
    print("\n" + "=" * 78)
    print("HEADLINE — vol-cap sweep")
    print("=" * 78)
    base = perf(results['R1'])
    print(f"\n  R1 (Mom30 index):  FULL CAGR {base['CAGR']*100:.2f}%  Sh {base['Sharpe']:.2f}  DD {base['MaxDD']*100:+.2f}%")
    for w_label in ['FULL 2008-2026', 'OOS 2017-2026']:
        w_start = cfg7_on.index.min() if 'FULL' in w_label else OOS_START
        print(f"\n--- {w_label} ---")
        print(f"  {'variant':10s} {'CAGR':>8s} {'ΔCAGR':>8s} {'Sharpe':>7s} {'ΔSh':>7s} "
              f"{'MaxDD':>8s} {'ΔMaxDD':>8s}")
        base_r = perf(results['R1'].loc[w_start:END_FULL])
        for lbl in ['R1'] + labels:
            r = perf(results[lbl].loc[w_start:END_FULL])
            print(f"  {lbl:10s} {r['CAGR']*100:>7.2f}% {(r['CAGR']-base_r['CAGR'])*100:>+7.2f}pp "
                  f"{r['Sharpe']:>7.2f} {r['Sharpe']-base_r['Sharpe']:>+7.2f} "
                  f"{r['MaxDD']*100:>+7.2f}% {(r['MaxDD']-base_r['MaxDD'])*100:>+7.2f}pp")

    # 2018-19 window drill-down
    print("\n" + "=" * 78)
    print("2018-2019 WINDOW — where V4 helped MaxDD")
    print("=" * 78)
    ws, we = pd.Timestamp('2018-01-01'), pd.Timestamp('2019-12-31')
    print(f"  {'variant':10s} {'2018':>8s} {'2019':>8s} {'DD-in-win':>10s}")
    for lbl in ['R1'] + labels:
        s = results[lbl].loc[ws:we]
        r18 = (1 + s.loc['2018-01-01':'2018-12-31']).prod() - 1
        r19 = (1 + s.loc['2019-01-01':'2019-12-31']).prod() - 1
        cum = (1 + s).cumprod(); dd = (cum / cum.cummax() - 1).min()
        print(f"  {lbl:10s} {r18*100:>+7.2f}% {r19*100:>+7.2f}% {dd*100:>+9.2f}%")

    # Verdict
    print("\n" + "=" * 78)
    print("VERDICT")
    print("=" * 78)
    best_full_sh = df.loc[df['FULL_Sh'].idxmax()]
    best_oos_sh  = df.loc[df['OOS_Sh'].idxmax()]
    best_full_cagr = df.loc[df['FULL_CAGR'].idxmax()]
    best_oos_cagr  = df.loc[df['OOS_CAGR'].idxmax()]
    print(f"  Best FULL Sharpe: {best_full_sh['label']} (vol_cap={best_full_sh['vol_cap']}) "
          f"→ {best_full_sh['FULL_Sh']:.2f}")
    print(f"  Best OOS  Sharpe: {best_oos_sh['label']}  (vol_cap={best_oos_sh['vol_cap']})  "
          f"→ {best_oos_sh['OOS_Sh']:.2f}")
    print(f"  Best FULL CAGR:   {best_full_cagr['label']} (vol_cap={best_full_cagr['vol_cap']}) "
          f"→ {best_full_cagr['FULL_CAGR']*100:.2f}%")
    print(f"  Best OOS  CAGR:   {best_oos_cagr['label']}  (vol_cap={best_oos_cagr['vol_cap']})  "
          f"→ {best_oos_cagr['OOS_CAGR']*100:.2f}%")

    print(f"\nR1 targets: FULL 16.85% CAGR / 1.34 Sh / -13.92% DD  |  OOS 16.10% / 1.24 / -10.88%")
    print(f"\nOutputs → {OUT_DIR}")


if __name__ == '__main__':
    main()
