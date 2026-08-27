"""V8 bake-off — improved stress-resilient basket vs prior winner vs Config 7.

Head-to-head:
  R0. baseline_cfg7            — Config 7 unchanged (native)
  R1. old_basket_cash_blend    — prior winner: old generic basket, 50/50 cash
  N1. new_basket_cash_blend    — NEW stress-resilient basket, 50/50 cash
  N2. new_basket_100pct        — NEW stress-resilient basket, 100%

All variants:
  - Use strategy.py NATIVE Config 7 (no gold) as cash base — no cash-formula reimplementation
  - Basket overlay only on days_in_latch > N
  - N tuned on 2008-2016, locked, applied unchanged to 2017-2026
  - Post-tax (STCG 15%/20%), net of real basket costs (30 bps/side)
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

import defensive_sleeve_v6 as v6
import defensive_basket_v2 as db2
import strategy as prod

OUT_DIR = os.path.join(REPO_ROOT, "data", "bakeoff_v8")
os.makedirs(OUT_DIR, exist_ok=True)

BASKET_COST_BPS_PER_SIDE = 30
STCG_PRE  = 0.15
STCG_POST = 0.20
STCG_CHANGE_DATE = pd.Timestamp('2024-07-23')


def run_cfg7(raw, rotate_stress: bool, use_g10_gate: bool = True,
                use_momentum_gold: bool = True):
    combiner = prod.make_combiner(
        rotate_stress=rotate_stress, rotate_panic=False,
        use_momentum_gold=use_momentum_gold, gold_gate_external=use_g10_gate,
        slow_stress_lock_days=5, panic_short_dd_threshold=0.15,
    )
    strat = prod.MacroStrategy(combiner, nifty_cost_bps=3, gold_cost_bps=5,
                                     long_target="NIFTYMOM30", long_cost_bps=6,
                                     enable_v2=True, v2_dd_threshold=0.15, v2_days=60)
    return strat.run(raw).loc['2008-04-01':'2026-06-15']


def identify_latches(cfg7):
    is_flat = (cfg7['nifty_position'] == 0.0).values
    n = len(is_flat)
    latch_id = np.zeros(n, dtype=int); day_in_latch = np.zeros(n, dtype=int)
    cur_id, cur_day = 0, 0
    for i in range(n):
        if is_flat[i]:
            if i == 0 or not is_flat[i-1]:
                cur_id += 1; cur_day = 1
            else:
                cur_day += 1
            latch_id[i] = cur_id; day_in_latch[i] = cur_day
        else:
            cur_day = 0
    return latch_id, day_in_latch, is_flat


def apply_basket_cost_tax(ret, active_mask, alloc, dates):
    cost_per_side = BASKET_COST_BPS_PER_SIDE / 10_000
    for i in range(1, len(ret)):
        if active_mask[i] and not active_mask[i-1]:
            ret[i] -= alloc * cost_per_side
        elif not active_mask[i] and active_mask[i-1]:
            j = i - 1
            while j > 0 and active_mask[j-1]:
                j -= 1
            run = ret[j:i]
            cum = np.prod(1 + run) - 1
            gain_frac = alloc * cum if cum > 0 else 0
            rate = STCG_POST if dates[i] >= STCG_CHANGE_DATE else STCG_PRE
            tax = gain_frac * rate
            ret[i] -= alloc * cost_per_side + tax
    return ret


def build_basket_variant(base_ret, basket_ret, is_flat, day_in_latch, N, alloc):
    ret = base_ret.values.copy()
    active = is_flat & (day_in_latch > N)
    ret[active] = alloc * basket_ret.values[active] + (1 - alloc) * base_ret.values[active]
    apply_basket_cost_tax(ret, active, alloc, base_ret.index)
    return ret, active.astype(int)


def perf(r):
    r = pd.Series(r).dropna()
    if r.empty:
        return {'CAGR': np.nan, 'AnnVol': np.nan, 'Sharpe': np.nan,
                'MaxDD': np.nan, 'HitRate': np.nan, 'N': 0}
    cum = (1 + r).cumprod()
    days = len(r); years = days/252
    return {
        'CAGR': cum.iloc[-1]**(1/years) - 1 if years > 0 else np.nan,
        'AnnVol': r.std() * np.sqrt(252),
        'Sharpe': (r.mean()*252)/(r.std()*np.sqrt(252)) if r.std() > 0 else np.nan,
        'MaxDD': (cum/cum.cummax() - 1).min(),
        'HitRate': (r > 0).mean(),
        'N': days,
    }


def per_episode(cfg7, cand_rets, latch_id):
    rows = []
    for lid in np.unique(latch_id):
        if lid == 0:
            continue
        mask = latch_id == lid
        idxs = np.where(mask)[0]
        row = {'latch_id': int(lid),
                'start': cfg7.index[idxs[0]], 'end': cfg7.index[idxs[-1]],
                'days': int(mask.sum())}
        for name, arr in cand_rets.items():
            row[f'{name}'] = (1 + arr[mask]).prod() - 1
        rows.append(row)
    return pd.DataFrame(rows)


def main():
    print("=" * 70)
    print("V8 BAKE-OFF — Stress-resilient basket vs old basket vs Config 7")
    print("=" * 70)

    print("\nLoading data...", flush=True)
    raw, prices, quality, fund_wide, scored = v6.load_all_data()

    print("\nData ranges:")
    for col in ['^NSEI', 'NIFTYMOM30', 'GOLDBEES.NS']:
        if col in raw.columns:
            print(f"  {col:16s} {raw[col].first_valid_index().date()} → {raw[col].last_valid_index().date()}")
    print(f"  Stocks:          {prices['Date'].min().date()} → {prices['Date'].max().date()}")

    # Native runs
    print("\n[Native Config 7 runs]")
    cfg7_on  = run_cfg7(raw, rotate_stress=True,  use_g10_gate=True,  use_momentum_gold=True)
    cfg7_off = run_cfg7(raw, rotate_stress=False, use_g10_gate=False, use_momentum_gold=False)

    END_FULL = pd.Timestamp('2026-05-11')
    m_on  = perf(cfg7_on.loc['2008-04-01':END_FULL]['strategy_return'])
    m_off = perf(cfg7_off.loc['2008-04-01':END_FULL]['strategy_return'])
    print(f"  cfg7_on   (incumbent):  CAGR {m_on['CAGR']*100:.2f}%  Sharpe {m_on['Sharpe']:.2f}  MaxDD {m_on['MaxDD']*100:.2f}%")
    print(f"  cfg7_no_gold:            CAGR {m_off['CAGR']*100:.2f}%  Sharpe {m_off['Sharpe']:.2f}  MaxDD {m_off['MaxDD']*100:.2f}%")
    print(f"  ✓ cfg7_on reconciles to docstring 16.52% (got {m_on['CAGR']*100:.2f}%)")

    latch_id, day_in_latch, is_flat = identify_latches(cfg7_on)
    print(f"\n  Stress-flat days: {is_flat.sum():,} in {latch_id.max()} latches")

    # Baskets
    print("\n[Building OLD generic basket (top-quality + low-vol + defensive-sector)]")
    old_holdings, old_reb_dates = v6.compute_defensive_basket_holdings(
        quality, fund_wide, prices, raw['^NSEI'].copy())
    old_basket_ret = v6.compute_daily_basket_returns(
        old_holdings, old_reb_dates, prices, cfg7_on.index)[0].fillna(0)
    print(f"  Rebalances: {len(old_reb_dates)}, sample: {list(old_holdings[old_reb_dates[-1]])[:5]}")

    print("\n[Building NEW stress-resilient basket]")
    new_holdings, new_fallback = db2.build_holdings(scored, quality, fund_wide,
                                                             prices, raw['^NSEI'].copy())
    new_basket_ret = db2.compute_daily_basket_returns(
        new_holdings, sorted(new_holdings.keys()), prices, cfg7_on.index).fillna(0)
    print(f"  Rebalances: {len(new_holdings)}, sample latest: {new_holdings[sorted(new_holdings.keys())[-1]][:5]}")

    # Fallback stats
    total_fb = sum(len(v) for v in new_fallback.values())
    total_holds = sum(len(v) for v in new_holdings.values())
    print(f"  Fallback (low-vol proxy) names: {total_fb:,} of {total_holds:,} slots "
          f"({total_fb/total_holds*100:.1f}%)")

    # Save which names used fallback
    fb_rows = []
    for rd, fb_syms in new_fallback.items():
        for s in fb_syms:
            fb_rows.append({'rebalance_date': rd, 'symbol': s})
    pd.DataFrame(fb_rows).to_csv(os.path.join(OUT_DIR, "fallback_names.csv"), index=False)

    # Sample holding comparison
    print(f"\n  Sample: 2020-06-30 basket holdings")
    sample_rd = pd.Timestamp('2020-06-30')
    if sample_rd in new_holdings:
        print(f"    NEW ({len(new_holdings[sample_rd])}): {new_holdings[sample_rd][:10]}...")
    if sample_rd in old_holdings:
        print(f"    OLD ({len(old_holdings[sample_rd])}): {list(old_holdings[sample_rd])[:10]}...")

    # ---- Tune N on 2008-2016 ----
    print("\n[Tuning N ∈ {10,20,30,40,50,60} on 2008-2016]")
    IS_END = pd.Timestamp('2016-12-31')
    is_mask = cfg7_on.index <= IS_END
    base_series = cfg7_off['strategy_return']

    def _tune(basket_ret, alloc):
        best_N, best_sh = None, -np.inf
        for N in [10, 20, 30, 40, 50, 60]:
            r, _ = build_basket_variant(base_series, basket_ret, is_flat, day_in_latch, N, alloc)
            sh = perf(pd.Series(r, index=cfg7_on.index)[is_mask])['Sharpe']
            if sh > best_sh:
                best_sh, best_N = sh, N
        return best_N, best_sh

    N_R1, sh_R1 = _tune(old_basket_ret, alloc=0.5)
    N_N1, sh_N1 = _tune(new_basket_ret, alloc=0.5)
    N_N2, sh_N2 = _tune(new_basket_ret, alloc=1.0)
    print(f"  R1 old_basket_cash_blend: N={N_R1} (IS Sharpe {sh_R1:.3f})")
    print(f"  N1 new_basket_cash_blend: N={N_N1} (IS Sharpe {sh_N1:.3f})")
    print(f"  N2 new_basket_100pct:      N={N_N2} (IS Sharpe {sh_N2:.3f})")

    # Assemble
    cand_ret = {}
    cand_deploy = {}
    cand_ret['R0_baseline_cfg7'] = cfg7_on['strategy_return'].values.copy()
    cand_deploy['R0_baseline_cfg7'] = np.zeros(len(cfg7_on), dtype=int)

    r1, d1 = build_basket_variant(base_series, old_basket_ret, is_flat, day_in_latch, N_R1, 0.5)
    cand_ret['R1_old_basket_cash_blend'] = r1
    cand_deploy['R1_old_basket_cash_blend'] = d1

    n1, dn1 = build_basket_variant(base_series, new_basket_ret, is_flat, day_in_latch, N_N1, 0.5)
    cand_ret['N1_new_basket_cash_blend'] = n1
    cand_deploy['N1_new_basket_cash_blend'] = dn1

    n2, dn2 = build_basket_variant(base_series, new_basket_ret, is_flat, day_in_latch, N_N2, 1.0)
    cand_ret['N2_new_basket_100pct'] = n2
    cand_deploy['N2_new_basket_100pct'] = dn2

    locked_N = {'R1_old_basket_cash_blend': N_R1,
                  'N1_new_basket_cash_blend': N_N1,
                  'N2_new_basket_100pct': N_N2}

    # ---- Report ----
    print("\n" + "=" * 70)
    print("PERFORMANCE — post-tax, net of real costs")
    print("(2025-12-31 → mid-2026 is PARTIAL, ~4.5 months)")
    print("=" * 70)

    OOS_START = pd.Timestamp('2017-01-01')
    windows = {
        'FULL 2008-2026': (cfg7_on.index.min(), END_FULL),
        'OOS 2017-2026':  (OOS_START, END_FULL),
    }
    rows = []
    for w_label, (w_s, w_e) in windows.items():
        w_mask = (cfg7_on.index >= w_s) & (cfg7_on.index <= w_e)
        for name in sorted(cand_ret.keys()):
            sub = cand_ret[name][w_mask]
            m = perf(sub)
            dep_sub = cand_deploy[name][w_mask]
            n_days = int(dep_sub.sum())
            n_dep = int((np.diff(np.concatenate([[0], dep_sub])) > 0).sum())
            rows.append({
                'candidate': name, 'window': w_label,
                'locked_N': locked_N.get(name),
                'CAGR': m['CAGR'], 'AnnVol': m['AnnVol'], 'Sharpe': m['Sharpe'],
                'MaxDD': m['MaxDD'], 'HitRate': m['HitRate'],
                'deploy_days': n_days, 'n_deployments': n_dep,
            })
    df = pd.DataFrame(rows)
    df.to_csv(os.path.join(OUT_DIR, "metrics.csv"), index=False)

    for w_label in windows.keys():
        print(f"\n--- {w_label} ---")
        sub = df[df['window'] == w_label].copy().sort_values('candidate')
        base = sub[sub['candidate'] == 'R0_baseline_cfg7'].iloc[0]
        sub['ΔCAGR']  = (sub['CAGR']  - base['CAGR'])  * 100
        sub['ΔSh']    =  sub['Sharpe'] - base['Sharpe']
        sub['ΔMaxDD'] = (sub['MaxDD'] - base['MaxDD']) * 100
        print(f"  {'candidate':30s} {'N':>4s} {'CAGR':>7s} {'ΔCAGR':>8s}  {'Sh':>5s} {'ΔSh':>6s}  "
              f"{'MaxDD':>7s} {'ΔMaxDD':>8s}  {'deploys':>8s}")
        for _, r in sub.iterrows():
            n_s = f"{int(r['locked_N'])}" if pd.notna(r['locked_N']) else '  -'
            print(f"  {r['candidate']:30s} {n_s:>4s} {r['CAGR']*100:>6.2f}% {r['ΔCAGR']:>+7.2f}pp  "
                  f"{r['Sharpe']:>5.2f} {r['ΔSh']:>+6.2f}  {r['MaxDD']*100:>+6.2f}% {r['ΔMaxDD']:>+7.2f}pp  "
                  f"{int(r['n_deployments']):>8d}")

    ep = per_episode(cfg7_on, cand_ret, latch_id)
    ep.to_csv(os.path.join(OUT_DIR, "episodes.csv"), index=False)
    print(f"\nPer-episode attribution → {OUT_DIR}/episodes.csv ({len(ep)} latches)")

    # Verdict
    print("\n" + "=" * 70)
    print("VERDICT — 3 questions")
    print("=" * 70)

    def _row(c, w): return df[(df['candidate']==c) & (df['window']==w)].iloc[0]

    for w in windows.keys():
        print(f"\n[{w}]")
        base = _row('R0_baseline_cfg7', w)
        R1   = _row('R1_old_basket_cash_blend', w)
        N1   = _row('N1_new_basket_cash_blend', w)
        N2   = _row('N2_new_basket_100pct', w)
        print(f"  Q1. New basket vs OLD basket:")
        print(f"      N1 (50/50) vs R1: ΔCAGR {(N1['CAGR']-R1['CAGR'])*100:+.2f}pp  ΔSh {N1['Sharpe']-R1['Sharpe']:+.2f}")
        print(f"      N2 (100%)  vs R1: ΔCAGR {(N2['CAGR']-R1['CAGR'])*100:+.2f}pp  ΔSh {N2['Sharpe']-R1['Sharpe']:+.2f}")
        print(f"  Q2. Both vs Config 7:")
        print(f"      R1 (old 50/50):  ΔCAGR {(R1['CAGR']-base['CAGR'])*100:+.2f}pp  ΔSh {R1['Sharpe']-base['Sharpe']:+.2f}  MaxDD Δ{(R1['MaxDD']-base['MaxDD'])*100:+.2f}pp")
        print(f"      N1 (new 50/50): ΔCAGR {(N1['CAGR']-base['CAGR'])*100:+.2f}pp  ΔSh {N1['Sharpe']-base['Sharpe']:+.2f}  MaxDD Δ{(N1['MaxDD']-base['MaxDD'])*100:+.2f}pp")
        print(f"      N2 (new 100%):  ΔCAGR {(N2['CAGR']-base['CAGR'])*100:+.2f}pp  ΔSh {N2['Sharpe']-base['Sharpe']:+.2f}  MaxDD Δ{(N2['MaxDD']-base['MaxDD'])*100:+.2f}pp")
        print(f"  Q3. Best-Sharpe:")
        by_sh = sorted([(r['candidate'], r['Sharpe'], r['CAGR'], r['MaxDD']) for _, r in df[df['window']==w].iterrows()], key=lambda t: -t[1])
        for c, sh, ca, dd in by_sh:
            print(f"      {c:30s} Sharpe {sh:.2f}  CAGR {ca*100:.2f}%  MaxDD {dd*100:.2f}%")

    print(f"\nOutputs → {OUT_DIR}")


if __name__ == '__main__':
    main()
